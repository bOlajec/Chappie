import { useEffect, useRef, useState } from 'react';
import { api, jsonRequest } from './api';
import { PixelIcon } from './components';
import './profiles.css';

export type ReasoningMode = 'off' | 'on' | 'model_default';
export type ProfileFields = {name: string; description: string; instructions: string; project_context: string; reference_notes: string; preferred_model: string; reasoning: ReasoningMode; script_tools_enabled: boolean};
export type AssistantProfile = ProfileFields & {id: string; updated_at: string};
const emptyProfile: ProfileFields = {name: '', description: '', instructions: '', project_context: '', reference_notes: '', preferred_model: '', reasoning: 'off', script_tools_enabled: false};

export function Dialog({title, onClose, children, className = ''}: {title: string; onClose: () => void; children: React.ReactNode; className?: string}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {const element = dialog.current!; element.showModal(); return () => element.close();}, []);
  return <dialog className={`retro-dialog ${className}`} ref={dialog} aria-label={title} onCancel={e => {e.preventDefault(); onClose();}}>
    <div className="dialog-heading"><h2>{title}</h2><button type="button" className="icon-button" aria-label="Close dialog" onClick={onClose}><PixelIcon name="close"/></button></div>
    {children}
  </dialog>;
}

export function AssistantManager({profiles, models, activeId, onChanged, onClose}: {profiles: AssistantProfile[]; models: string[]; activeId: string; onChanged: () => Promise<void>; onClose: () => void}) {
  const initial = profiles.find(profile => profile.id === activeId) ?? profiles[0];
  const [selected, setSelected] = useState(initial?.id ?? 'new');
  const [form, setForm] = useState<ProfileFields>(initial ?? emptyProfile);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  function pick(id: string) {setSelected(id); setForm(profiles.find(p => p.id === id) ?? {...emptyProfile}); setError(''); setNotice(''); setConfirmDelete(false);}
  function field<K extends keyof ProfileFields>(key: K, value: ProfileFields[K]) {setForm(previous => ({...previous, [key]: value})); setNotice('');}
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    // Send only editable fields, never the id/timestamp from a saved profile.
    const payload = Object.fromEntries(Object.keys(emptyProfile).map(key => [key, form[key as keyof ProfileFields]]));
    try {
      const saved = await api<AssistantProfile>(selected === 'new' ? '/assistants' : `/assistants/${selected}`, jsonRequest(selected === 'new' ? 'POST' : 'PUT', payload));
      await onChanged(); setSelected(saved.id); setForm(saved); setConfirmDelete(false); setNotice('Assistant saved. Existing chats keep their saved copy until you update them.');
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function remove() {
    setBusy(true); setError('');
    try {await api<void>(`/assistants/${selected}`, {method: 'DELETE'}); await onChanged(); pick('new'); setNotice('Assistant deleted. Existing chats keep their saved instructions and notes.');}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function importNotes(file: File | undefined) {
    if (!file) return;
    if (!/\.(md|txt)$/i.test(file.name) || file.size > 96000) {setError('Choose a .md or .txt file with at most 24,000 characters.'); return;}
    try {
      const text = await file.text();
      const combined = form.reference_notes ? `${form.reference_notes}\n\n${text}` : text;
      if (combined.length > 24000) {setError('Reference notes are limited to 24,000 characters.'); return;}
      field('reference_notes', combined); setError('');
    } catch {setError('Could not read this text file.');}
  }
  return <Dialog title="Assistant profiles" onClose={() => {if (!busy) onClose();}} className="profile-manager">
    <div className="manager-layout">
      <nav className="profile-list" aria-label="Saved assistants"><button type="button" className="primary" disabled={busy} onClick={() => pick('new')}><PixelIcon name="plus"/>New assistant</button>
        {profiles.map(profile => <button type="button" key={profile.id} aria-current={selected === profile.id ? 'true' : undefined} disabled={busy} onClick={() => pick(profile.id)}>{profile.name}</button>)}
      </nav>
      <form className="profile-form" onSubmit={save}>
        <fieldset disabled={busy}>
          <div className="field-row"><label>Assistant name<input required maxLength={80} value={form.name} onChange={e => field('name', e.target.value)} placeholder="e.g. Arduino Developer"/></label><label>Short description<input maxLength={300} value={form.description} onChange={e => field('description', e.target.value)} placeholder="What this assistant helps with"/></label></div>
          <label>Instructions<textarea aria-label="Instructions" rows={6} maxLength={12000} value={form.instructions} onChange={e => field('instructions', e.target.value)} placeholder="Describe its expertise, how it should answer, and when it should ask questions."/></label>
          <label>Default project context<textarea aria-label="Default project context" rows={4} maxLength={12000} value={form.project_context} onChange={e => field('project_context', e.target.value)} placeholder={'Board: …\nComponents and pins: …\nLibraries and versions: …\nProject goals and constraints: …'}/></label>
          <small>Copied into new chats. Each chat can have its own board, wiring, and project notes.</small>
          <label>Reference notes<textarea aria-label="Reference notes" rows={5} maxLength={24000} value={form.reference_notes} onChange={e => field('reference_notes', e.target.value)} placeholder="Paste relevant documentation, library examples, or your own reference notes."/></label>
          <div className="import-row"><label className="import-label">Import .md / .txt<input type="file" accept=".md,.txt,text/plain,text/markdown" aria-label="Import reference notes" onChange={e => {void importNotes(e.target.files?.[0]); e.target.value = '';}}/></label><small>{form.reference_notes.length.toLocaleString()} / 24,000 characters</small></div>
          <small>Notes are included as text in each request. Importing a SKILL.md file adds reference text only; it does not enable tools or file access.</small>
          <div className="field-row"><label>Preferred model<select aria-label="Preferred model" value={form.preferred_model} onChange={e => field('preferred_model', e.target.value)}><option value="">Use the selected model</option>{form.preferred_model && !models.includes(form.preferred_model) && <option value={form.preferred_model}>{form.preferred_model} (not available)</option>}{models.map(model => <option key={model}>{model}</option>)}</select></label>
            <label>Reasoning preference<select aria-label="Reasoning preference" value={form.reasoning} onChange={e => field('reasoning', e.target.value as ReasoningMode)}><option value="off">Off — direct answers</option><option value="on">On — deeper reasoning</option><option value="model_default">Model default</option></select></label></div>
          <small>Reasoning preferences apply where the selected model offers on/off controls. Profiles do not change model weights.</small>
          <label className="profile-tool-permission"><input type="checkbox" checked={form.script_tools_enabled} onChange={e => field('script_tools_enabled', e.target.checked)}/>Allow saved Python scripts by default</label>
          <small>When enabled, this assistant can run registered scripts automatically. Only scripts from the configured project folder are offered, in a separate runner with time and output limits.</small>
        </fieldset>
        {error && <p className="notice error" role="alert">{error}</p>}{notice && <p className="save-notice" role="status">{notice}</p>}
        <div className="dialog-actions"><button type="submit" className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save assistant'}</button>
          {selected !== 'new' && !confirmDelete && <button type="button" className="delete-button" disabled={busy} onClick={() => setConfirmDelete(true)}>Delete assistant</button>}
          {confirmDelete && <div className="delete-confirm"><span>Delete this profile? Chats keep their saved copy.</span><button type="button" className="delete-button" disabled={busy} onClick={() => void remove()}>Confirm delete</button><button type="button" disabled={busy} onClick={() => setConfirmDelete(false)}>Keep profile</button></div>}
        </div>
        <p className="profile-footnote">Saved-script access is optional. There is no general shell, model-generated-code execution, Arduino compilation, or board upload tool.</p>
      </form>
    </div>
  </Dialog>;
}

export function ProjectContextEditor({value, onSave, onClose}: {value: string; onSave: (value: string) => Promise<void>; onClose: () => void}) {
  const [text, setText] = useState(value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {await onSave(text); onClose();} catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <Dialog title="Project context" onClose={() => {if (!busy) onClose();}} className="context-editor"><form className="profile-form" onSubmit={save}>
    <p>These notes belong to this chat and accompany every message.</p>
    <label>Board, components & project notes<textarea aria-label="Board, components & project notes" autoFocus rows={12} maxLength={12000} disabled={busy} value={text} onChange={e => setText(e.target.value)} placeholder={'Board: …\nComponents and pins: …\nLibraries and versions: …\nProject goals and constraints: …'}/></label>
    <small>{text.length.toLocaleString()} / 12,000 characters</small>
    {error && <p className="notice error" role="alert">{error}</p>}
    <div className="dialog-actions"><button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save project context'}</button><button type="button" disabled={busy} onClick={onClose}>Cancel</button></div>
  </form></Dialog>;
}
