"""Reconstruct complete tool exchanges; omit interrupted or dangling tool calls."""
def history_messages(rows):
    result = []
    index = 0
    while index < len(rows):
        message = rows[index]
        if message.status == 'complete' and message.role == 'assistant' and message.tool_calls:
            calls = message.tool_calls
            replies = rows[index + 1:index + 1 + len(calls)]
            if len(replies) == len(calls) and all(reply.role == 'tool' and reply.status == 'complete'
                    and reply.tool_name == call['function']['name'] for reply, call in zip(replies, calls)):
                result.append({'role': 'assistant', 'content': message.content, 'tool_calls': calls})
                result.extend({'role': 'tool', 'tool_name': reply.tool_name, 'content': reply.content} for reply in replies)
                index += len(calls) + 1
                continue
        elif message.status == 'complete' and message.role in ('user', 'assistant'):
            result.append({'role': message.role, 'content': message.content})
        index += 1
    return result


def normalize_calls(calls):
    result = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get('function'), dict):
            raise ValueError('Malformed model tool call')
        function = call['function']
        name, arguments = function.get('name'), function.get('arguments', {})
        if not isinstance(name, str) or len(name) > 100 or not isinstance(arguments, dict):
            raise ValueError('Invalid tool name or arguments; arguments must be a JSON object')
        result.append({'type': 'function', 'function': {'name': name, 'arguments': arguments}})
    return result
