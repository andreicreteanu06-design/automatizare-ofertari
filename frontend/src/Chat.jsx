import { useEffect, useRef, useState } from 'react';
import { BookOpen, Send, Sparkles } from 'lucide-react';
import { api } from './api';
import { Button, Check, ErrorBox, Field, Table } from './ui';

function Answer({ data, onRemember }) {
  const citations = data.citations || [];
  const parts = data.answer.split(/(\[https?:\/\/[^\]\n]+\]|\[[^\]\n]+:\d+\])/g);
  return <>
    <div className="answer-text">{parts.map((part, i) => {
      const c = citations.find(c => c.cite === part);
      if (c?.url && /^https?:\/\//.test(c.url)) return <a className="citation" href={c.url} target="_blank" rel="noopener noreferrer" key={i}>{new URL(c.url).hostname} ↗</a>;
      return c ? <span className="citation" key={i} title={`${c.supplier || 'Sursă internă'} · paginile ${c.page}–${c.page_end || c.page}`}><BookOpen size={12} />{c.doc_id} · p. {c.page}</span> : <span key={i}>{part}</span>;
    })}</div>
    {data.verification_status && <p className={data.verification_status === 'verified_excerpts' ? 'success mt-3' : 'warning mt-3'}>
      {data.verification_status === 'verified_excerpts' ? 'Pasaje copiate din surse. Verifică relevanța, revizia și corectitudinea extragerii.' : data.verification_status === 'conflict' ? 'Surse contradictorii — este necesară verificarea unui specialist.' : 'Dovezi insuficiente după căutările efectuate.'}
      {' '}{data.attempts?.length || 0} încercări de căutare / verificare.
    </p>}
    {!data.verification_status && data.grounded === false && <p className="warning">Răspuns fără citări valide. Verifică informațiile în documentele sursă.</p>}
    {!!data.web_research?.errors?.length && <p className="warning mt-3">Unele pagini web nu au putut fi accesate. Răspunsul poate fi incomplet.</p>}
    {data.live_web && !data.web_research?.sources?.length && <p className="warning mt-3">Căutarea web nu a furnizat pagini utilizabile.</p>}
    {citations.length > 0 && <div className="sources"><span>SURSE DOCUMENTARE</span>{citations.map((c, i) => <div key={i}><BookOpen size={14} /><strong>{c.doc_id}</strong><span>p. {c.page}{c.page_end > c.page ? `–${c.page_end}` : ''} · {c.doc_type || 'Document'} · {c.supplier || ''}</span></div>)}</div>}
    {!!data.evidence?.length && <details className="mt-4"><summary>Dovezi și trasabilitate</summary>{data.evidence.map(e => <div key={e.id} className="line-card mt-3"><strong>{e.doc_id} · p. {e.page}–{e.page_end}</strong><p className="whitespace-pre-wrap">{e.quote}</p><p className="text-xs break-all">Amprentă document: {e.source_revision || 'Indisponibilă pentru documentele indexate anterior'}</p>{onRemember && <Button secondary onClick={() => onRemember(e)}>Reține / adaugă notă de revizuire</Button>}</div>)}</details>}
    {!!data.removed_codes?.length && <p className="warning">Coduri eliminate ca neverificate: {data.removed_codes.join(', ')}.</p>}
    {!!data.removed_citations?.length && <p className="warning">Citări eliminate ca neverificate: {data.removed_citations.join(', ')}.</p>}
    {!!data.exact?.length && <div className="mt-5"><h3 className="mb-3">Prețuri identificate în facturi</h3><Table headers={['Articol', 'Furnizor', 'Factură / data', 'Cantitate', 'Preț unitar', 'Preț net']} rows={data.exact.map(p => [<span>{p.seller_code}<small className="block">{p.name}</small></span>, p.supplier, `${p.invoice_number} / ${p.issue_date}`, `${p.quantity} ${p.unit_code}`, `${p.unit_price} ${p.currency}`, `${p.net_unit_price ?? '—'} ${p.currency}`])} /></div>}
  </>;
}

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [conversation, setConversation] = useState(null);
  const [project, setProject] = useState('General');
  const [references, setReferences] = useState([]);
  const [selected, setSelected] = useState(null);
  const [note, setNote] = useState('');
  const [query, setQuery] = useState('');
  const [k, setK] = useState('5');
  const [liveWeb, setLiveWeb] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const pending = useRef(null);
  const end = useRef(null);
  const applyConversation = data => {
    setConversation(data); setMessages(data.messages || []); setReferences(data.references || []);
    setProject(data.project); setSelected(null); setNote('');
  };
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await api('/conversations');
        if (cancelled) return;
        setConversations(list);
        if (list.length) {
          const data = await api(`/conversations/${list[0].id}`);
          if (!cancelled) applyConversation(data);
        }
      } catch (e) { if (!cancelled) setError(e.message); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);
  useEffect(() => { if (end.current?.getClientRects().length) end.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [messages, busy]);
  async function open(id) {
    if (!id || busy) return;
    setBusy(true); setError('');
    try { applyConversation(await api(`/conversations/${id}`)); pending.current = null; }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  function reset() {
    setConversation(null); setMessages([]); setReferences([]); setSelected(null); setError(''); setQuery(''); pending.current = null;
  }
  async function submit(e) {
    e.preventDefault(); if (!query.trim() || busy || loading) return;
    const text = query.trim(); setBusy(true); setError('');
    try {
      let active = conversation;
      if (!active) {
        active = await api('/conversations', { project: project.trim(), title: text.slice(0, 200) });
        setConversation(active); setConversations(list => [active, ...list]);
      }
      if (!pending.current || pending.current.query !== text || pending.current.cid !== active.id || pending.current.liveWeb !== liveWeb) pending.current = { id: crypto.randomUUID(), query: text, cid: active.id, liveWeb };
      const response = await api('/chat', { query: text, k: Number(k), conversation_id: active.id, version: active.version, request_id: pending.current.id, live_web: liveWeb });
      setMessages(m => [...m, { role: 'user', text }, { role: 'assistant', data: response }]);
      setConversation(c => ({ ...c, version: response.version })); setQuery(''); pending.current = null;
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function remember(e) {
    e.preventDefault(); setBusy(true); setError('');
    try {
      await api(`/conversations/${conversation.id}/references`, { evidence_id: selected.id, note });
      const data = await api(`/conversations/${conversation.id}`);
      applyConversation(data);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <div className="space-y-5">
    <section className="card"><div className="form-grid">
      <Field label="Proiect" value={project} onChange={setProject} maxLength={200} disabled={!!conversation || busy || loading} />
      <Field label="Conversații salvate" value={conversation?.id || ''} onChange={open} disabled={busy || loading} options={[[ '', loading ? 'Se încarcă…' : 'Conversație nouă'], ...conversations.map(c => [c.id, `${c.project} · ${c.title}`])]} />
    </div><p className="text-xs mt-3">Istoricul este salvat în Postgres pentru acest browser. Nu există încă autentificare pe utilizatori; ștergerea cookie-ului pierde accesul din browser. Referințele salvate sunt repere pentru revizuire, nu dovezi noi.</p>
    <div className="flex gap-3 mt-3"><Button secondary disabled={busy || loading} onClick={reset}>Conversație nouă</Button>{conversation && <Button secondary disabled={busy} onClick={() => open(conversation.id)}>Reîncarcă istoricul</Button>}</div></section>
    <section className="card chat-card"><div className="card-heading"><div className="flex items-center gap-3"><span className="soft-icon"><Sparkles size={20} /></span><div><h2>Asistent tehnic · dovezi din surse</h2><p>Memorie persistentă și verificare extractivă</p></div></div><Field label="Fragmente inițiale" options={Array.from({ length: 10 }, (_, i) => String(i + 1))} value={k} onChange={setK} disabled={busy} /></div>
    <div className="messages" role="log" aria-label="Mesaje chat" aria-live="polite">{!messages.length && <div className="chat-empty"><BookOpen size={30} className="mx-auto mb-4" /><h2>Cu ce te pot ajuta?</h2><p>Include codul articolului și proprietatea căutată, de exemplu: „Care este masa pentru 3EST-000-123?”.</p></div>}{messages.map((m, i) => <article key={i} className={`message ${m.role}`}><div className="message-author">{m.role === 'user' ? 'TU' : 'ASISTENT TEHNIC'}</div>{m.role === 'user' ? <p className="whitespace-pre-wrap">{m.text}</p> : <Answer data={m.data} onRemember={conversation && !busy ? e => { setSelected(e); setNote(''); } : null} />}</article>)}{busy && <p role="status" className="processing">Se consultă și verifică sursele… Maximum trei încercări; pe CPU poate dura câteva minute.</p>}<div ref={end} /></div>
    <form className="composer" onSubmit={submit}><ErrorBox error={error} /><label htmlFor="chat-query" className="sr-only">Întrebare tehnică</label><textarea id="chat-query" required maxLength={1000} disabled={busy || loading} value={query} onChange={e => setQuery(e.target.value)} placeholder="Întreabă despre un articol sau continuă conversația…" rows={3} /><div className="mt-3"><Check label="🌍 Căutare Live Web (Perplexity)" value={liveWeb} onChange={setLiveWeb} /><p className="text-xs mt-2">Trimite doar întrebarea curentă spre căutarea web, după Egress Guard. Include explicit codul public; istoricul și documentele interne nu sunt trimise.</p></div><div className="composer-footer"><span>{query.length} / 1000 · Istoricul identifică articolul; documentele furnizează dovezile.</span><Button type="submit" disabled={busy || loading || !query.trim() || !project.trim()} busy={busy}><Send size={16} />Trimite</Button></div></form></section>
    {selected && <form className="card" onSubmit={remember}><h2>Notă de revizuire</h2><p>{selected.quote}</p><label className="field mt-3"><span>Observație / corecție propusă (nu devine automat fapt verificat)</span><textarea maxLength={1000} value={note} onChange={e => setNote(e.target.value)} rows={3} /></label><Button type="submit" disabled={busy}>Salvează referința</Button></form>}
    {!!references.length && <section className="card"><h2>Referințe păstrate pentru acest proiect / conversație</h2>{references.map(r => <div className="line-card mt-3" key={r.id}><strong>{r.evidence.doc_id} · p. {r.evidence.page}</strong><p>{r.evidence.quote}</p><p className="whitespace-pre-wrap">{r.note}</p><small>Referință istorică; poate necesita reverificare după actualizarea documentului.</small></div>)}</section>}
  </div>;
}
