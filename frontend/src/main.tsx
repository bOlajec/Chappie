import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ChappieIcon, MessageContent, PixelIcon } from './components';
import { api, jsonRequest } from './api';
import { AssistantManager, ProjectContextEditor, type AssistantProfile, type ReasoningMode } from './assistants';
import { SavedScriptsPanel, ScriptResult, type ScriptCatalog } from './savedScripts';
import './retro.css';
import './gunmetal.css';

type Chat = {id: string; title: string; model: string; updated_at: string; assistant_id: string | null; assistant_name: string | null; reasoning: ReasoningMode; script_tools_enabled: boolean};
type ChatSettings = Chat & {assistant_snapshot: AssistantProfile | null; project_context: string};
type Message = {id: number; role: string; content: string; model: string; status: string; tool_name?: string; tool_calls?: unknown[] | null};
type Conversation = ChatSettings & {messages: Message[]};
type Check = {status: string; detail: string};
type Diagnostics = {endpoint: string; network: Check; ollama: Check; tailscale: Check};
type Timings = {first_chunk_ms: number | null; first_text_ms: number | null; total_ms: number; load_ms?: number; prompt_ms?: number; generation_ms?: number; tokens_per_second?: number};
type ModelInfo = {model: string; supports_thinking: boolean | null; supports_tools?: boolean | null; thinking_variant: boolean};
type Theme = 'light' | 'dark';

function initialTheme(): Theme {
  try {return localStorage.getItem('chappie-theme') === 'dark' ? 'dark' : 'light';}
  catch {return 'light';}
}

function seconds(value: number | null | undefined) {
  return value == null ? 'unavailable' : `${(value / 1000).toFixed(2)} s`;
}

function App() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [chat, setChat] = useState<Conversation | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [reasoning, setReasoning] = useState<ReasoningMode>('off');
  const [profiles, setProfiles] = useState<AssistantProfile[]>([]);
  const [assistantId, setAssistantId] = useState('');
  const [projectContext, setProjectContext] = useState('');
  const [profileManagerOpen, setProfileManagerOpen] = useState(false);
  const [contextEditorOpen, setContextEditorOpen] = useState(false);
  const [scriptCatalog, setScriptCatalog] = useState<ScriptCatalog | null>(null);
  const [scriptsPanelOpen, setScriptsPanelOpen] = useState(false);
  const [useScripts, setUseScripts] = useState(false);
  const [stage, setStage] = useState('');
  const [timings, setTimings] = useState<Timings | null>(null);
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  const [modelInfoError, setModelInfoError] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [search, setSearch] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const diagnosticPanel = useRef<HTMLDetailsElement>(null);
  const followOutput = useRef(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  const isQwen3 = /(^|\/)qwen3(?:\.5)?(?::|$)/i.test(model);
  const selectedInfo = modelInfo?.model === model ? modelInfo : null;
  const checkingModel = Boolean(model && !selectedInfo && !modelInfoError);
  const canToggleReasoning = isQwen3 && !checkingModel && !selectedInfo?.thinking_variant && selectedInfo?.supports_thinking !== false;
  const controller = useRef<AbortController | null>(null);
  const opening = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);
  const filteredChats = chats.filter(c => c.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const today = new Date().toDateString();
  const groups = [
    {label: 'Today', chats: filteredChats.filter(c => new Date(c.updated_at).toDateString() === today)},
    {label: 'Earlier', chats: filteredChats.filter(c => new Date(c.updated_at).toDateString() !== today)},
  ];
  const modelOnline = diagnostics?.ollama.status === 'ready';
  const activeProfile = chat ? chat.assistant_snapshot : profiles.find(profile => profile.id === assistantId);
  const profileHasUpdates = Boolean(chat?.assistant_id && profiles.find(p => p.id === chat.assistant_id)?.updated_at !== chat.assistant_snapshot?.updated_at);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {localStorage.setItem('chappie-theme', theme);} catch { /* Theme still works when storage is unavailable. */ }
  }, [theme]);
  useEffect(() => {
    if (!sidebarOpen) return;
    function closeOnEscape(event: KeyboardEvent) {if (event.key === 'Escape') setSidebarOpen(false);}
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [sidebarOpen]);

  async function refresh() {
    setRefreshing(true);
    const results = await Promise.allSettled([
      api<Diagnostics>('/diagnostics').then(setDiagnostics),
      refreshScripts(),
      api<{models: string[]}>('/models').then(data => {
        setModels(data.models);
        setModel(previous => data.models.includes(previous) ? previous : data.models[0] ?? '');
      }).catch(e => {setModels([]); setModel(''); throw e;}),
    ]);
    const failures = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected');
    setError(failures.map(r => String(r.reason.message ?? r.reason)).join('; '));
    setRefreshing(false);
  }

  async function refreshScripts() {
    try {setScriptCatalog(await api<ScriptCatalog>('/scripts'));}
    catch (e) {setScriptCatalog({enabled: false, available: false, scripts: [], detail: (e as Error).message});}
  }

  useEffect(() => {
    void refresh();
    api<Chat[]>('/chats').then(setChats).catch(e => setError(e.message));
    api<AssistantProfile[]>('/assistants').then(setProfiles).catch(e => setError(e.message));
    return () => controller.current?.abort();
  }, []);
  useEffect(() => {if (followOutput.current) bottom.current?.scrollIntoView({block: 'end'});}, [chat?.messages]);
  useEffect(() => {
    const abort = new AbortController();
    setModelInfo(null); setModelInfoError(false);
    if (model) {
      api<ModelInfo>(`/model-info?model=${encodeURIComponent(model)}`, {signal: abort.signal})
        .then(info => {if (!abort.signal.aborted) setModelInfo(info);})
        .catch(() => {if (!abort.signal.aborted) setModelInfoError(true);});
    }
    return () => abort.abort();
  }, [model]);

  async function openChat(id: string) {
    const request = ++opening.current;
    setBusy(true); setError(''); setStage('Loading chat…');
    try {
      const value = await api<Conversation>(`/chats/${id}`);
      if (request !== opening.current) return;
      followOutput.current = true;
      setChat(value); setDraft(''); setTimings(null);
      setAssistantId(value.assistant_id ?? (value.assistant_snapshot ? '_saved' : ''));
      setProjectContext(value.project_context); setReasoning(value.reasoning);
      setUseScripts(value.script_tools_enabled);
      setSidebarOpen(false);
      if (value.model) {
        if (models.includes(value.model)) setModel(value.model);
        else {setModel(''); setError(`The saved model ${value.model} is not available. Choose an installed model to continue.`);}
      }
    } catch (e) {setError((e as Error).message);}
    finally {if (request === opening.current) setBusy(false);}
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (busy || checkingModel || !draft.trim() || !model || (useScripts && !scriptCatalog?.available)) return;
    setBusy(true); setError(''); setTimings(null); setStage('Connecting to model…');
    followOutput.current = true;
    const text = draft;
    let current = chat;
    const abort = new AbortController();
    controller.current = abort;
    try {
      if (!current) {
        const created = await api<ChatSettings>('/chats', jsonRequest('POST', {assistant_id: assistantId || null, project_context: projectContext}));
        current = {...created, messages: []};
        setChat(current);
      }
      const id = current.id;
      const response = await fetch(`/api/chats/${id}/messages`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model, content: text, think: canToggleReasoning && reasoning !== 'model_default' ? reasoning === 'on' : null, use_scripts: useScripts}), signal: abort.signal,
      });
      if (!response.ok) {
        const value = await response.json().catch(() => ({}));
        throw new Error(typeof value.detail === 'string' ? value.detail : `Send failed (${response.status})`);
      }
      setDraft('');
      setStage('Waiting for model…');
      setChat({...current, messages: [...current.messages,
        {id: -1, role: 'user', content: text, model, status: 'complete'},
        {id: -2, role: 'assistant', content: '', model, status: 'streaming'}]});
      if (!response.body) throw new Error('Streaming is unavailable in this browser.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '', completed = false;
      function consume(line: string) {
        if (!line.trim()) return;
        const value = JSON.parse(line);
        if (value.type === 'start') {
          setChat(previous => previous && ({...previous, messages: previous.messages.map((m, i) => i === previous.messages.length - 1 ? {...m, id: value.message_id} : m)}));
        } else if (value.type === 'tool_calls') {
          setChat(previous => previous && ({...previous, messages: previous.messages.map(m => m.id === value.message_id ? {...m, tool_calls: value.calls, status: 'complete'} : m)}));
        } else if (value.type === 'tool_start') {
          setStage(`Running ${value.message.tool_name?.replace(/^saved_/, '') ?? 'saved script'}…`);
          setChat(previous => previous && ({...previous, messages: [...previous.messages, value.message]}));
        } else if (value.type === 'tool_result') {
          setStage('Model is reviewing script results…');
          setChat(previous => previous && ({...previous, messages: previous.messages.map(m => m.id === value.message.id ? value.message : m)}));
        } else if (value.type === 'assistant_start') {
          setStage('Waiting for model…');
          setChat(previous => previous && ({...previous, messages: [...previous.messages, {id: value.message_id, role: 'assistant', model, content: '', status: 'streaming'}]}));
        } else if (value.type === 'delta') {
          setStage('Receiving response…');
          setChat(previous => previous && ({...previous, messages: previous.messages.map((m, i) =>
            i === previous.messages.length - 1 ? {...m, content: m.content + value.content} : m)}));
        } else if (value.type === 'status') setStage(value.detail);
        else if (value.type === 'error') throw new Error(value.detail);
        else if (value.type === 'done') {completed = true; setTimings(value.timings ?? null);}
      }
      try {
        while (true) {
          const {value, done} = await reader.read();
          buffer += decoder.decode(value, {stream: !done});
          const lines = buffer.split('\n'); buffer = lines.pop() ?? '';
          lines.forEach(consume);
          if (done) {consume(buffer); break;}
        }
        if (!completed) throw new Error('The connection ended before the response completed.');
      } finally {await reader.cancel().catch(() => {}); reader.releaseLock();}
    } catch (e) {
      setError((e as Error).name === 'AbortError' ? 'Generation stopped. Partial output is retained.' : (e as Error).message);
    } finally {
      controller.current = null;
      // The server finalizes interrupted output when it sees the disconnect.
      try {
        if (current) {
          let saved = await api<Conversation>(`/chats/${current.id}`);
          for (let attempt = 0; saved.messages.some(m => m.status === 'streaming') && attempt < 20; attempt++) {
            await new Promise(resolve => setTimeout(resolve, 100));
            saved = await api<Conversation>(`/chats/${current.id}`);
          }
          setChat(saved);
        }
        setChats(await api<Chat[]>('/chats'));
      } catch (e) {setError((e as Error).message);}
      setBusy(false);
      requestAnimationFrame(() => composer.current?.focus());
    }
  }

  function newChat() {
    ++opening.current; followOutput.current = true;
    setChat(null); setDraft(''); setError(''); setTimings(null); setSidebarOpen(false);
    const selected = profiles.find(profile => profile.id === assistantId);
    setAssistantId(selected?.id ?? ''); setProjectContext(selected?.project_context ?? '');
    setUseScripts(selected?.script_tools_enabled ?? false);
    applyPreferences(selected?.preferred_model ?? '', selected?.reasoning ?? 'off');
    requestAnimationFrame(() => composer.current?.focus());
  }

  function applyPreferences(preferredModel: string, preferredReasoning: ReasoningMode) {
    setReasoning(preferredReasoning);
    if (preferredModel) {
      setModel(models.includes(preferredModel) ? preferredModel : '');
      if (!models.includes(preferredModel)) setError(`The preferred model ${preferredModel} is not available. Choose an installed model.`);
    }
  }

  async function changeAssistant(id: string, preserveContext = false) {
    if (id === '_saved') return;
    setError('');
    if (!chat) {
      const profile = profiles.find(p => p.id === id);
      setAssistantId(id); setProjectContext(profile?.project_context ?? '');
      setUseScripts(profile?.script_tools_enabled ?? false);
      applyPreferences(profile?.preferred_model ?? '', profile?.reasoning ?? 'off');
      return;
    }
    setBusy(true); setStage('Saving assistant…');
    try {
      const updated = await api<ChatSettings>(`/chats/${chat.id}/assistant`, jsonRequest('PATCH', {assistant_id: id || null, ...(preserveContext ? {project_context: projectContext} : {})}));
      setChat({...updated, messages: chat.messages}); setAssistantId(updated.assistant_id ?? ''); setProjectContext(updated.project_context);
      setUseScripts(updated.script_tools_enabled);
      applyPreferences(updated.assistant_snapshot?.preferred_model ?? '', updated.reasoning); setChats(await api<Chat[]>('/chats'));
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }

  async function profilesChanged() {
    const updated = await api<AssistantProfile[]>('/assistants'); setProfiles(updated);
    setChats(await api<Chat[]>('/chats'));
    if (chat?.assistant_id && !updated.some(p => p.id === chat.assistant_id)) {
      setChat({...chat, assistant_id: null}); setAssistantId('_saved');
    } else if (!chat && assistantId && !updated.some(p => p.id === assistantId)) {
      setAssistantId(''); setProjectContext(''); setReasoning('off');
      setUseScripts(false);
    } else if (!chat) {
      const previous = profiles.find(p => p.id === assistantId);
      const selected = updated.find(p => p.id === assistantId);
      if (selected && selected.updated_at !== previous?.updated_at) {
        if (projectContext === previous?.project_context) setProjectContext(selected.project_context);
        applyPreferences(selected.preferred_model, selected.reasoning);
        setUseScripts(selected.script_tools_enabled);
      }
    }
  }

  async function saveProjectContext(value: string) {
    if (chat) {
      const updated = await api<ChatSettings>(`/chats/${chat.id}/context`, jsonRequest('PATCH', {project_context: value}));
      setChat({...updated, messages: chat.messages});
    }
    setProjectContext(value);
  }

  return <div className="layout">
    {profileManagerOpen && <AssistantManager profiles={profiles} models={models} activeId={assistantId} onChanged={profilesChanged} onClose={() => setProfileManagerOpen(false)}/>}
    {contextEditorOpen && <ProjectContextEditor value={projectContext} onSave={saveProjectContext} onClose={() => setContextEditorOpen(false)}/>}
    {scriptsPanelOpen && <SavedScriptsPanel catalog={scriptCatalog} refresh={refreshScripts} onClose={() => setScriptsPanelOpen(false)}/>}
    {sidebarOpen && <button className="sidebar-backdrop" aria-label="Close chat sidebar" onClick={() => setSidebarOpen(false)}/>}
    <aside className={`sidebar ${sidebarOpen ? 'is-open' : ''}`} aria-label="Chat sidebar">
      <div className="brand"><ChappieIcon/><h1>Chappie</h1><button className="icon-button mobile-only" aria-label="Close sidebar" onClick={() => setSidebarOpen(false)}><PixelIcon name="close"/></button></div>
      <button className="new-chat primary" disabled={busy} onClick={newChat}><PixelIcon name="plus"/>New chat</button>
      <label className="search"><PixelIcon name="search"/><span className="sr-only">Search chats</span><input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search chats"/></label>
      <nav className="chat-list" aria-label="Previous chats">
        {groups.filter(group => group.chats.length).map(group => <div className="chat-group" key={group.label}>
          <div className="section-label"><span>{group.label}</span><span className="rule"/></div>
          {group.chats.map(c => <button key={c.id} disabled={busy} aria-current={c.id === chat?.id ? 'page' : undefined} onClick={() => void openChat(c.id)} title={c.assistant_name ? `${c.title} · ${c.assistant_name}` : c.title}><PixelIcon name="chat"/><span>{c.title}</span></button>)}
        </div>)}
        {!chats.length && <p className="sidebar-empty">Your conversations will appear here.</p>}
        {!!chats.length && !filteredChats.length && <p className="sidebar-empty">No matching chats.</p>}
      </nav>
      <div className="sidebar-bottom">
        <button className="manage-assistants" disabled={busy} onClick={() => {setProfileManagerOpen(true); setSidebarOpen(false);}}><PixelIcon name="chat"/>Assistant profiles</button>
        <button className="future-tools" onClick={() => {setScriptsPanelOpen(true); setSidebarOpen(false);}}><PixelIcon name="tools"/><span>Saved scripts <small>· {scriptCatalog?.available ? scriptCatalog.scripts.length : 'Offline'}</small></span></button>
        <div className="theme-row"><span className="theme-caption"><PixelIcon name={theme === 'light' ? 'sun' : 'moon'}/>Theme</span><div className="theme-switch" role="group" aria-label="Color theme">
          <button aria-pressed={theme === 'light'} onClick={() => setTheme('light')}>Light</button><button aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')}>Dark</button>
        </div></div>
      </div>
    </aside>
    <main>
      <header className="topbar">
        <button className="icon-button mobile-only" aria-label="Open chat sidebar" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}><PixelIcon name="menu"/></button>
        <h2 title={chat?.title ?? 'New chat'}>{chat?.title ?? 'New chat'}</h2>
        <div className="session-controls">
          <label className="model-select"><span className="sr-only">Model</span><select value={model} disabled={busy || !models.length} onChange={e => {setModel(e.target.value); setError('');}}>
            {!model && <option value="">{models.length ? 'Choose a model' : 'No models available'}</option>}{models.map(name => <option key={name}>{name}</option>)}
          </select></label>
          {canToggleReasoning && <label className="reasoning-select"><span className="sr-only">Reasoning</span><select aria-label="Reasoning" value={reasoning} disabled={busy} onChange={e => setReasoning(e.target.value as ReasoningMode)}><option value="off">Reasoning: OFF</option><option value="on">Reasoning: ON</option><option value="model_default">Reasoning: DEFAULT</option></select></label>}
          <button className="model-status" onClick={() => {if (diagnosticPanel.current) diagnosticPanel.current.open = !diagnosticPanel.current.open;}} aria-label="Toggle connection diagnostics"><span className={`status-dot ${modelOnline ? 'good' : diagnostics ? 'bad' : 'unknown'}`}/>{modelOnline ? 'Model online' : diagnostics ? 'Model offline' : 'Checking model'}</button>
        </div>
      </header>
      <div className="assistant-bar">
        <label><span>Assistant</span><select aria-label="Assistant" value={assistantId} disabled={busy} onChange={e => void changeAssistant(e.target.value)}><option value="">General assistant</option>{assistantId === '_saved' && <option value="_saved">Saved: {chat?.assistant_name}</option>}{profiles.map(profile => <option value={profile.id} key={profile.id}>{profile.name}</option>)}</select></label>
        <button disabled={busy} onClick={() => setContextEditorOpen(true)}>Project context{projectContext ? ' · Set' : ''}</button>
        <label className="script-access-control" title="Allow the model to automatically run registered Python scripts"><input type="checkbox" aria-label="Allow saved scripts" checked={useScripts} disabled={busy || (!useScripts && (!scriptCatalog?.available || !scriptCatalog.scripts.length || selectedInfo?.supports_tools === false))} onChange={e => setUseScripts(e.target.checked)}/>Allow saved scripts</label>
        {profileHasUpdates && <button disabled={busy} onClick={() => void changeAssistant(assistantId, true)}>Update chat from profile</button>}
        <span className="assistant-description" title={activeProfile?.description}>{activeProfile?.description ?? 'Your everyday local assistant'}</span>
      </div>
      <details className="connection-panel" ref={diagnosticPanel}>
        <summary><span className="sr-only">Connection diagnostics</span>
          <span className={`connection-item ${diagnostics?.network.status === 'reachable' ? 'good' : diagnostics ? 'bad' : ''}`}><i className="status-dot"/>Network: {diagnostics?.network.status ?? 'checking'}</span>
          <span className={`connection-item ${modelOnline ? 'good' : diagnostics ? 'bad' : ''}`}><i className="status-dot"/>Ollama: {modelOnline ? 'online' : diagnostics?.ollama.status ?? 'checking'}</span>
          <span className="connection-item caution"><i className="status-dot"/>Tailscale: host check needed</span><span className="connection-chevron" aria-hidden="true">▾</span>
        </summary>
        <div className="diagnostic-body">
          <div className="diagnostic-heading"><strong>Connection diagnostics</strong><button className="refresh-button" onClick={() => void refresh()} disabled={refreshing || busy}><PixelIcon name="refresh"/>{refreshing ? 'Checking…' : 'Refresh connection & models'}</button></div>
          {!diagnostics ? <p>Diagnostics have not loaded.</p> : <><p className="endpoint">Endpoint: {diagnostics.endpoint}</p>{(['network', 'ollama', 'tailscale'] as const).map(key => <p key={key}><strong>{key}: {diagnostics[key].status}</strong><br/>{diagnostics[key].detail}</p>)}</>}
        </div>
      </details>
      <div className="notices">
        {checkingModel && <p role="status" className="notice">Checking model capabilities…</p>}
        {selectedInfo?.thinking_variant && <p role="status" className="notice warning">This model identifies itself as a Thinking variant. Turning reasoning off may be ineffective. Choose an Instruct variant or another installed model for direct answers.</p>}
        {modelInfoError && <p className="notice warning">Model capabilities could not be checked. Reasoning controls may not apply to this model.</p>}
        {useScripts && !scriptCatalog?.available && <p className="notice warning">Saved scripts are unavailable. Turn off script access to chat without them, or check the runner in Saved scripts.</p>}
        {error && <p role="alert" className="notice error">{error}</p>}
      </div>
      <section className="messages" aria-label="Chat messages" aria-live="polite" aria-relevant="additions text" onScroll={e => {const el = e.currentTarget; followOutput.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;}}>
        <div className="conversation">
          {!chat?.messages.length && <div className="empty-state"><div className="empty-icon"><ChappieIcon/></div><p className="empty-title">A little space to think.</p><p>Choose a model, type a message, and make yourself at home.</p><span className="empty-badge">Your models. Your conversations.</span></div>}
          {chat?.messages.map((message, index) => <article className={`message message-${message.role}`} key={message.id}>
            <div className="message-avatar" aria-hidden="true">{message.role === 'assistant' ? <ChappieIcon/> : message.role === 'tool' ? <PixelIcon name="tools"/> : <span>YOU</span>}</div>
            <div className="message-body">
              <span className="sr-only">{message.role}</span>
              <div className="content">{message.role === 'tool' ? <ScriptResult content={message.content} status={message.status}/> : message.content ? message.role === 'assistant' ? <MessageContent content={message.content} streaming={message.status === 'streaming'}/> : <div className="prose">{message.content}</div> : <span className="waiting-text">{message.tool_calls?.length ? 'Called saved scripts' : message.status === 'streaming' ? 'Waiting for response…' : '(No response content)'}</span>}</div>
              {message.role === 'assistant' && <div className="message-meta"><span>{message.model}</span><span className={`message-status status-${message.status}`}>{message.status === 'complete' ? 'Complete' : message.status}</span>{index === chat.messages.length - 1 && timings && <span>{seconds(timings.total_ms)}{timings.tokens_per_second !== undefined && ` · ${timings.tokens_per_second} tokens/s`}</span>}</div>}
            </div>
          </article>)}
          {timings && <details className="timing-panel"><summary>Last response timing</summary><div>
            <p>First model activity: {seconds(timings.first_chunk_ms)} · First answer text: {seconds(timings.first_text_ms)} · Total: {seconds(timings.total_ms)}</p>
            <p>Model loading: {seconds(timings.load_ms)} · Prompt processing: {seconds(timings.prompt_ms)} · Generation: {seconds(timings.generation_ms)}{timings.tokens_per_second !== undefined && ` · ${timings.tokens_per_second} tokens/s`}</p>
            <p>First activity/text and total include backend setup, network, model loading and generation; they do not isolate network latency. Model timings come from Ollama. Reasoning can contribute to generation time.</p>
          </div></details>}
          <div ref={bottom}/>
        </div>
      </section>
      <div className="composer-area">
        <div className="composer-status" role="status">{busy ? <><span className="busy-pixel"/>{stage || 'Loading chat…'}</> : <span>{model ? `${activeProfile?.name ?? 'General assistant'} · ${model}` : 'Connect a model to begin'}</span>}</div>
        <form onSubmit={send}>
          <label className="sr-only" htmlFor="message">Message</label>
          <textarea ref={composer} id="message" value={draft} disabled={busy} rows={2} maxLength={100000} onChange={e => setDraft(e.target.value)} onKeyDown={e => {if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {e.preventDefault(); e.currentTarget.form?.requestSubmit();}}} placeholder="Message your model…"/>
          {busy && controller.current ? <button className="send-button stop-button" type="button" aria-label="Stop" title="Stop generating" onClick={() => controller.current?.abort()}><PixelIcon name="stop"/></button> : <button className="send-button primary" aria-label="Send" title="Send message" disabled={busy || checkingModel || !draft.trim() || !model || (useScripts && !scriptCatalog?.available)}><PixelIcon name="send"/></button>}
        </form>
        <div className="composer-hint"><span>Enter to send <span className="hint-divider">·</span> Shift+Enter for a new line</span><span className="local-label"><ChappieIcon/> Chappie</span></div>
      </div>
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
