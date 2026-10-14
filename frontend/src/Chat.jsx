import { useEffect, useRef, useState } from 'react';
import { BookOpen, Send, Sparkles, ArrowUpRight } from 'lucide-react';
import { api } from './api';
import { Button, ErrorBox, Field, Table } from './ui';

function Answer({ data }) {
  const citations = data.citations || [];
  const parts = data.answer.split(/(\[[^\]\n]+:\d+\])/g);
  return <><div className="answer-text">{parts.map((part, i) => {
    const citation = citations.find(c => c.cite === part);
    return citation ? <span className="citation" key={i} title={`${citation.doc_type || 'Document'} · ${citation.supplier || 'Sursă internă'} · pagina ${citation.page}`}><BookOpen size={12} />{citation.doc_id} · p. {citation.page}</span> : <span key={i}>{part}</span>;
  })}</div>{data.grounded === false && <p className="warning">Răspuns fără citări valide. Verifică informațiile în documentele sursă.</p>}
    {citations.length > 0 && <div className="sources"><span>SURSE DOCUMENTARE</span>{citations.map((c, i) => <div key={i}><BookOpen size={14} /><strong>{c.doc_id}</strong><span>p. {c.page} · {c.doc_type || 'Document'}{c.supplier ? ` · ${c.supplier}` : ''}</span></div>)}</div>}
    {!!data.removed_codes?.length && <p className="warning">Coduri eliminate ca neverificate: {data.removed_codes.join(', ')}.</p>}
    {!!data.removed_citations?.length && <p className="warning">Citări eliminate ca neverificate: {data.removed_citations.join(', ')}.</p>}
    {!!data.exact?.length && <div className="mt-5"><h3 className="mb-3">Prețuri identificate în facturi</h3><Table headers={['Articol', 'Furnizor', 'Factură / data', 'Cantitate', 'Preț unitar', 'Preț net']} rows={data.exact.map(p => [<span>{p.seller_code}<small className="block">{p.name}</small></span>, p.supplier, `${p.invoice_number} / ${p.issue_date}`, `${p.quantity} ${p.unit_code}`, `${p.unit_price} ${p.currency}`, `${p.net_unit_price ?? '—'} ${p.currency}`])} /></div>}
  </>;
}
export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [query, setQuery] = useState('');
  const [k, setK] = useState('5');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const end = useRef(null);
  useEffect(() => { if (end.current?.getClientRects().length) end.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [messages, busy]);
  async function submit(e) {
    e.preventDefault(); if (!query.trim() || busy) return;
    const text = query.trim(); setBusy(true); setError('');
    setMessages(m => [...m, { role: 'user', text }]);
    try { const response = await api('/chat', { query: text, k: Number(k) }); setMessages(m => [...m, { role: 'assistant', data: response }]); setQuery(''); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <div className="chat-layout"><section className="card chat-card"><div className="card-heading"><div className="flex items-center gap-3"><span className="soft-icon"><Sparkles size={20} /></span><div><h2>Asistent tehnic</h2><p>Întrebări în limbaj natural, răspunsuri documentate</p></div></div><Button secondary disabled={busy || !messages.length} onClick={() => { setMessages([]); setError(''); }}>Conversație nouă</Button></div><div className="messages" role="log" aria-label="Mesaje chat" aria-live="polite">{!messages.length && <div className="chat-empty"><span className="empty-icon"><BookOpen size={30} strokeWidth={1.4} /></span><h2>Cu ce te pot ajuta?</h2><p>Caută un cod de piesă, verifică o caracteristică<br />sau consultă istoricul prețurilor.</p>{['Care sunt specificațiile pentru 3EST-000-123?', 'Cât costă 3EST-000-123?'].map(q => <button type="button" key={q} onClick={() => setQuery(q)}>{q}<ArrowUpRight size={16} /></button>)}</div>}{messages.map((m, i) => <article key={i} className={`message ${m.role}`}><div className="message-author">{m.role === 'user' ? 'TU' : 'ASISTENT TEHNIC'}</div>{m.role === 'user' ? <p className="whitespace-pre-wrap">{m.text}</p> : <Answer data={m.data} />}</article>)}{busy && <p role="status" className="processing">Se consultă documentele interne… Generarea pe CPU poate dura câteva minute.</p>}<div ref={end} /></div><form className="composer" onSubmit={submit}><ErrorBox error={error} /><label htmlFor="chat-query" className="sr-only">Întrebare tehnică</label><textarea id="chat-query" required maxLength={1000} disabled={busy} value={query} onChange={e => setQuery(e.target.value)} placeholder="Scrie o întrebare despre articole sau documente…" rows={3} /><div className="composer-footer"><span>{query.length} / 1000 · Fiecare întrebare este căutată independent.</span><Button type="submit" disabled={busy || !query.trim()} busy={busy}><Send size={16} />Trimite</Button></div></form></section><aside><CardInfo k={k} setK={setK} busy={busy} /></aside></div>;
}
function CardInfo({ k, setK, busy }) { return <div className="card"><BookOpen size={23} className="text-emerald-800 mb-4" /><h2>Din documente, cu context.</h2><p className="mt-3 mb-5">Citările indică documentul și pagina sursă. Prețurile identificate în facturi apar separat de răspuns.</p><Field label="Fragmente consultate" options={Array.from({ length: 10 }, (_, i) => String(i + 1))} value={k} onChange={setK} disabled={busy} /><p className="mt-4 text-xs">Codurile și citările neverificate sunt filtrate de backend.</p></div>; }
