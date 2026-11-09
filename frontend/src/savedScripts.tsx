import { useState } from 'react';
import { Dialog } from './assistants';
import { PixelIcon } from './components';
import './scripts.css';

export type ScriptCatalog = {enabled: boolean; available: boolean; detail: string; scripts: Array<{name: string; file: string; description: string; parameters: Record<string, unknown>}>};

export function SavedScriptsPanel({catalog, refresh, onClose}: {catalog: ScriptCatalog | null; refresh: () => Promise<void>; onClose: () => void}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function reload() {setBusy(true); setError(''); try {await refresh();} catch (e) {setError((e as Error).message);} finally {setBusy(false);}}
  return <Dialog title="Saved Python scripts" onClose={onClose} className="scripts-dialog"><div className="scripts-panel-body">
    <p>Register trusted Python scripts in <code>scripts/tools.json</code> in this project. Only registered files from the <code>scripts</code> folder can be selected by the model.</p>
    <p className="script-isolation">Scripts run in a separate container on the computer hosting this app, with no network or chat-database mount. The script folder is read-only; each run gets a temporary working folder. Standard-library Python is available.</p>
    <div className="scripts-panel-toolbar"><span className={catalog?.available ? 'good' : 'caution'}>{catalog?.available ? `${catalog.scripts.length} registered scripts` : 'Runner unavailable'}</span><button onClick={() => void reload()} disabled={busy}><PixelIcon name="refresh"/>{busy ? 'Checking…' : 'Refresh scripts'}</button></div>
    {error && <p role="alert" className="notice error">{error}</p>}
    {!catalog?.available && <p className="notice warning">{catalog?.detail ?? 'Checking script runner…'}</p>}
    {catalog?.available && !catalog.scripts.length && <p>No scripts are registered yet. Add an entry to scripts/tools.json.</p>}
    {catalog?.scripts.map(script => <div className="script-entry" key={script.name}><h3><PixelIcon name="tools"/>{script.name}</h3><p>{script.description}</p><small>{script.file}</small><details><summary>Input format</summary><pre>{JSON.stringify(script.parameters, null, 2)}</pre></details></div>)}
    <p className="profile-footnote">Enable “Allow saved scripts” in a chat, or set it as an assistant preference. The model can then run registered scripts automatically when relevant. A folder restriction does not make untrusted Python safe; only register scripts you trust. No model-generated code is executed and no Arduino validation or upload tool is included.</p>
  </div></Dialog>;
}

export function ScriptResult({content, status}: {content: string; status: string}) {
  let result: Record<string, unknown>;
  try {result = JSON.parse(content); if (!result || typeof result !== 'object') throw new Error();}
  catch {return <div className="prose">{content}</div>;}
  const runStatus = status === 'interrupted' ? 'interrupted' : String(result.status ?? status);
  const success = runStatus === 'complete';
  const stdout = typeof result.stdout === 'string' ? result.stdout : '';
  const stderr = typeof result.stderr === 'string' ? result.stderr : '';
  return <div className="script-result">
    <div className="script-result-heading"><strong>Saved script · {String(result.script ?? 'unknown')}</strong><span className={success ? 'good' : runStatus === 'running' ? 'caution' : 'bad'}>{runStatus.replaceAll('_', ' ')}</span></div>
    <p className="script-output-preview">{stdout || stderr ? (stdout || stderr).slice(0, 240) : runStatus === 'running' ? 'Running saved Python script…' : 'No captured output.'}</p>
    <div className="message-meta">{typeof result.duration_ms === 'number' && <span>{(result.duration_ms / 1000).toFixed(2)} s</span>}{typeof result.exit_code === 'number' && <span>Exit {result.exit_code}</span>}{result.truncated === true && <span className="caution">Output truncated; script stopped</span>}</div>
    <details><summary>Arguments & output</summary><div className="script-output"><strong>Arguments</strong><pre>{JSON.stringify(result.arguments ?? {}, null, 2)}</pre><strong>Standard output</strong><pre>{stdout || '(empty)'}</pre><strong>Errors</strong><pre>{stderr || '(empty)'}</pre></div></details>
  </div>;
}
