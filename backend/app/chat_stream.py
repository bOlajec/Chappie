"""Streaming model/tool loop with persistent, visible script results."""
import asyncio
import json
import logging
from time import monotonic
from . import db, ollama, config
from .tools import scripts
from .tools.history import normalize_calls

logger = logging.getLogger(__name__)


def event(kind, **payload):
    return json.dumps({'type': kind, **payload}) + '\n'


async def stream_chat(*, chat_id, assistant_id, model, history, system_prompt, think, entries, started, release):
    content, status, assistant_complete = '', 'interrupted', False
    pending_tool_id = None
    used_calls = 0
    first_chunk_ms = first_text_ms = None
    totals = {}
    offered = {'saved_' + entry['name']: entry for entry in entries}
    max_calls = config.settings.script_max_calls
    messages = ([{'role': 'system', 'content': system_prompt}] if system_prompt else []) + history
    try:
        yield event('start', message_id=assistant_id)
        async with ollama.client() as http:
            for round_number in range(max_calls + 1):
                calls, thinking, thinking_reported, done = [], '', False, False
                last_checkpoint = monotonic()
                payload = {'model': model, 'messages': messages, 'stream': True, 'keep_alive': config.settings.ollama_keep_alive}
                if entries and used_calls < max_calls:
                    payload['tools'] = scripts.definitions(entries)
                if think is not None:
                    payload['think'] = think
                async with http.stream('POST', '/api/chat', json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if first_chunk_ms is None:
                            first_chunk_ms = round((monotonic() - started) * 1000)
                        if chunk.get('error'):
                            raise ValueError(str(chunk['error']))
                        message = chunk.get('message', {})
                        thought = message.get('thinking', '')
                        if thought:
                            if not isinstance(thought, str):
                                raise ValueError('Invalid model thinking content')
                            if entries:
                                thinking += thought
                                if len(thinking) > 131072:
                                    raise ValueError('Model reasoning exceeded the tool-loop limit')
                            if not thinking_reported:
                                thinking_reported = True
                                yield event('status', detail='Model is thinking…')
                        token = message.get('content', '')
                        if not isinstance(token, str):
                            raise ValueError('Invalid Ollama message content')
                        if token:
                            if first_text_ms is None:
                                first_text_ms = round((monotonic() - started) * 1000)
                            content += token
                            yield event('delta', content=token)
                            if monotonic() - last_checkpoint >= 0.5:
                                with db.Session.begin() as session:
                                    session.get(db.Message, assistant_id).content = content
                                last_checkpoint = monotonic()
                        if message.get('tool_calls'):
                            if not isinstance(message['tool_calls'], list):
                                raise ValueError('Invalid tool-call list')
                            calls.extend(message['tool_calls'])
                            if len(calls) > max_calls:
                                raise ValueError('The model requested too many scripts in one response')
                        if chunk.get('done'):
                            for key in ('load_duration', 'prompt_eval_duration', 'eval_duration', 'eval_count'):
                                value = chunk.get(key)
                                if isinstance(value, (int, float)) and value >= 0:
                                    totals[key] = totals.get(key, 0) + value
                            done = True
                            break
                if not done:
                    raise ValueError('Ollama stream ended before completion')
                calls = normalize_calls(calls)
                if calls and not entries:
                    raise ValueError('The model requested a tool but saved-script access is off')
                if used_calls + len(calls) > max_calls:
                    raise ValueError(f'Saved-script limit reached ({max_calls} calls per message)')
                with db.Session.begin() as session:
                    message = session.get(db.Message, assistant_id)
                    message.content, message.status, message.tool_calls = content, 'complete', calls or None
                assistant_complete = True
                if not calls:
                    status = 'complete'
                    break
                model_message = {'role': 'assistant', 'content': content, 'tool_calls': calls}
                if thinking:
                    model_message['thinking'] = thinking
                messages.append(model_message)
                yield event('tool_calls', message_id=assistant_id, calls=calls)
                for call in calls:
                    used_calls += 1
                    function = call['function']
                    name, arguments = function['name'], function['arguments']
                    entry = offered.get(name)
                    script_name = entry['name'] if entry else name
                    with db.Session.begin() as session:
                        tool_message = db.Message(chat_id=chat_id, role='tool', model=model, tool_name=name,
                            status='streaming', content=json.dumps({'script': script_name, 'arguments': arguments, 'status': 'running'}))
                        session.add(tool_message)
                        session.flush()
                        pending_tool_id = tool_message.id
                        visible_message = {'id': tool_message.id, 'role': 'tool', 'model': model, 'tool_name': name,
                                           'status': 'streaming', 'content': tool_message.content}
                    yield event('tool_start', message=visible_message)
                    result = {'script': script_name, 'arguments': arguments, 'status': 'rejected', 'exit_code': None,
                              'stdout': '', 'stderr': 'Tool is not in the registered saved-script list', 'duration_ms': 0, 'truncated': False}
                    if entry:
                        try:
                            result = await scripts.run(script_name, arguments)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            result.update(status='error', stderr=f'Script runner failed: {exc}')
                    tool_content = json.dumps(result)
                    with db.Session.begin() as session:
                        saved = session.get(db.Message, pending_tool_id)
                        saved.content, saved.status = tool_content, 'complete'
                    visible_message.update(content=tool_content, status='complete')
                    messages.append({'role': 'tool', 'tool_name': name, 'content': tool_content})
                    pending_tool_id = None
                    yield event('tool_result', message=visible_message)
                with db.Session.begin() as session:
                    assistant = db.Message(chat_id=chat_id, role='assistant', model=model, status='streaming')
                    session.add(assistant)
                    session.flush()
                    assistant_id = assistant.id
                content, status, assistant_complete = '', 'interrupted', False
                yield event('assistant_start', message_id=assistant_id)
            else:
                raise ValueError('Saved-script round limit reached')
        timings = {'first_chunk_ms': first_chunk_ms, 'first_text_ms': first_text_ms,
                   'total_ms': round((monotonic() - started) * 1000)}
        for source, target in [('load_duration', 'load_ms'), ('prompt_eval_duration', 'prompt_ms'), ('eval_duration', 'generation_ms')]:
            if source in totals:
                timings[target] = round(totals[source] / 1_000_000, 1)
        if totals.get('eval_duration', 0) > 0:
            timings['tokens_per_second'] = round(totals.get('eval_count', 0) / totals['eval_duration'] * 1_000_000_000, 1)
        yield event('done', message_id=assistant_id, timings=timings)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        status = 'error'
        logger.warning('Chat generation failed: %s', exc)
        if not assistant_complete:
            with db.Session.begin() as session:
                message = session.get(db.Message, assistant_id)
                message.content, message.status = content, status
        yield event('error', detail=f'Generation failed: {exc}')
    finally:
        try:
            with db.Session.begin() as session:
                if not assistant_complete:
                    message = session.get(db.Message, assistant_id)
                    message.content, message.status = content, status
                if pending_tool_id:
                    message = session.get(db.Message, pending_tool_id)
                    data = json.loads(message.content)
                    data.update(status='interrupted', stderr='Request interrupted; output is unavailable. Runner cancellation requested.')
                    message.content, message.status = json.dumps(data), 'interrupted'
                session.get(db.Chat, chat_id).updated_at = db.now()
        finally:
            release()
