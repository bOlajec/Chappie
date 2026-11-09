import { useEffect, useMemo, useRef, useState } from 'react';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import json from 'highlight.js/lib/languages/json';
import bash from 'highlight.js/lib/languages/bash';
import xml from 'highlight.js/lib/languages/xml';
import css from 'highlight.js/lib/languages/css';

for (const [name, language] of Object.entries({python, javascript, typescript, json, bash, xml, css})) {
  hljs.registerLanguage(name, language);
}

type IconName = 'chat' | 'plus' | 'search' | 'send' | 'stop' | 'copy' | 'sun' | 'moon' | 'tools' | 'menu' | 'close' | 'refresh';
const paths: Record<IconName, string> = {
  chat: 'M3 1h10v1h2v10h-2v1H7v1H5v1H3v-3H1V3h2V1zm0 3v6h2v2l2-2h6V4H3zm2 2h2v2H5V6zm4 0h2v2H9V6z',
  plus: 'M7 2h2v5h5v2H9v5H7V9H2V7h5V2z',
  search: 'M3 1h6v1h2v2h1v5h-2v2H8v1H3v-1H1V3h2V1zm1 2v1H3v5h1v1h4V9h2V4H9V3H4zm6 8h2v1h1v1h1v2h-2v-1h-1v-1h-1v-2z',
  send: 'M7 1h2v2h2v2h2v2h2v2h-5v6H6V9H1V7h2V5h2V3h2V1z',
  stop: 'M3 3h10v10H3V3z',
  copy: 'M5 1h9v11h-3v3H1V4h4V1zm2 2v1h4v6h1V3H7zM3 6v7h6V6H3z',
  sun: 'M7 0h2v3H7V0zm0 13h2v3H7v-3zM0 7h3v2H0V7zm13 0h3v2h-3V7zM2 2h2v2H2V2zm10 0h2v2h-2V2zM2 12h2v2H2v-2zm10 0h2v2h-2v-2zM5 4h6v1h1v6h-1v1H5v-1H4V5h1V4z',
  moon: 'M6 1h4v2H7v2H5v5h2v2h4v-1h3v2h-2v2H5v-1H3v-2H1V5h2V3h3V1z',
  tools: 'M2 1h3v3h4V1h3v2h2v4h-2v2H9v3H7v3H4v-3h1V9H3V7H1V3h1V1z',
  menu: 'M1 3h14v2H1V3zm0 4h14v2H1V7zm0 4h14v2H1v-2z',
  close: 'M2 2h2v2h2v2h4V4h2V2h2v2h-2v2h-2v4h2v2h2v2h-2v-2h-2v-2H6v2H4v2H2v-2h2v-2h2V6H4V4H2V2z',
  refresh: 'M4 1h8v2h2V1h2v7H9V6h3V4h-2V3H5v1H3v7h2v2h6v-2h2v2h-1v2H4v-2H2v-2H1V5h1V3h2V1z',
};

export function PixelIcon({name, className = ''}: {name: IconName; className?: string}) {
  return <svg className={`pixel-icon ${className}`} viewBox="0 0 16 16" aria-hidden="true" shapeRendering="crispEdges"><path d={paths[name]} fill="currentColor"/></svg>;
}

function CodeBlock({code, language, streaming}: {code: string; language: string; streaming: boolean}) {
  const [copyState, setCopyState] = useState('Copy');
  const reset = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {if (reset.current) clearTimeout(reset.current);}, []);
  const highlighted = useMemo(() => {
    if (streaming || code.length > 50000 || !hljs.getLanguage(language)) return null;
    return hljs.highlight(code, {language, ignoreIllegals: true}).value;
  }, [code, language, streaming]);
  async function copy() {
    try {await navigator.clipboard.writeText(code); setCopyState('Copied!');}
    catch {setCopyState('Copy failed');}
    if (reset.current) clearTimeout(reset.current);
    reset.current = setTimeout(() => setCopyState('Copy'), 2000);
  }
  return <div className="code-panel">
    <div className="code-toolbar"><span>{language || 'Code'}</span><button type="button" onClick={() => void copy()} aria-label="Copy code"><PixelIcon name="copy"/>{copyState}</button></div>
    <pre tabIndex={0} aria-label={`${language || 'Plain text'} code`}>{highlighted === null ? <code>{code}</code> : <code dangerouslySetInnerHTML={{__html: highlighted}}/>}</pre>
  </div>;
}

function inferLanguage(content: string): string | null {
  if (/^\s*(?:(?:#[^\n]*\n)\s*)*(?:from\s+\S+\s+import\s|import\s+\w|(?:async\s+)?def\s+\w+\s*\(|class\s+\w+[^\n]*:)/.test(content)) return 'python';
  if (/^\s*(?:const\s+\w+\s*=|let\s+\w+\s*=|(?:export\s+)?(?:async\s+)?function\s+\w+\s*\()/.test(content)) return 'javascript';
  return null;
}

export function MessageContent({content, streaming}: {content: string; streaming: boolean}) {
  const language = inferLanguage(content);
  if (!content.includes('```')) return language ? <CodeBlock code={content} language={language} streaming={streaming}/> : <div className="prose">{content}</div>;
  const parts: React.ReactNode[] = [];
  const blocks = /```([^\n`]*)\n([\s\S]*?)(```|$)/g;
  let cursor = 0;
  for (const match of content.matchAll(blocks)) {
    const index = match.index!;
    if (index > cursor) parts.push(<div className="prose" key={`text-${index}`}>{content.slice(cursor, index)}</div>);
    parts.push(<CodeBlock key={`code-${index}`} code={match[2].replace(/\r?\n$/, '')} language={match[1].trim().toLowerCase()} streaming={streaming}/>);
    cursor = index + match[0].length;
  }
  if (cursor < content.length) parts.push(<div className="prose" key="last-text">{content.slice(cursor)}</div>);
  return <>{parts}</>;
}
