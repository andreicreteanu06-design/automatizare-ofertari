import { Hero1 } from './components/ui/hero-1';
import { useEffect, useRef, useState } from 'react';
import { BookOpen, ArrowUpRight, MessageSquareText, Plus } from 'lucide-react';
import { api } from './api';
import './chat.css';
import { BranchingReasoningChatInput } from './components/ui/branching-reasoning-chat-input';
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
    {data.rerank_status === 'fallback' && <p className="warning">Reordonarea locală nu este disponibilă; sunt folosite rezultatele căutării hibride.</p>}
    {data.technical_claims?.some(c => c.normalized_quantity) && <details className="mt-3"><summary>Conversii de unități verificate</summary>{data.technical_claims.filter(c => c.normalized_quantity).map((c, i) => <p key={i}>{c.property}: {c.value} = {c.normalized_quantity.value} {c.normalized_quantity.unit}</p>)}</details>}
    {data.evidence?.some(e => e.provenance?.length) && <details className="mt-3"><summary>Localizare în documentul original</summary>{data.evidence.filter(e => e.provenance?.length).map(e => <div key={e.id}><strong>{e.doc_id}</strong>{e.provenance.map((p, i) => <p key={i}>{p.ref} · {p.locations.map(l => `p. ${l.page_no}: (${l.bbox.l}, ${l.bbox.t})–(${l.bbox.r}, ${l.bbox.b}), ${l.bbox.coord_origin}`).join('; ')} · {p.cells.length} celule asociate. Coordonatele elementului nu certifică exactitatea OCR.</p>)}</div>)}</details>}
    {data.evidence_status && <p className="warning mt-3">Date tehnice: {({ confirmed: 'criteriile documentare sunt îndeplinite', unconfirmed: 'neconfirmate — verifică produsul, unitățile și revizia', contradictory: 'contradictorii' })[data.evidence_status] || data.evidence_status}. Revizuire umană necesară înainte de ofertare.</p>}
    {!!data.web_research?.pages?.length && <details className="mt-3"><summary>Acces web și actualitate</summary>{data.web_research.pages.map((p, i) => <p className="break-all" key={i}>{p.url} · {p.access_status} · {p.stale ? 'COPIE ISTORICĂ — nu este verificare live' : 'Preluare live'} · {p.retrieved_at}</p>)}</details>}
    {!!data.technical_claims?.length && <details className="mt-3"><summary>Valori structurate și criterii de verificare</summary>{data.technical_claims.map((c, i) => <div key={i} className="line-card"><p>{c.property}: {c.value} · {c.evidence_status}</p><p>Producător: {c.identity.manufacturer || 'neprecizat'} · Variantă: {c.identity.variant || 'neprecizată'} · Revizie: {c.document_revision || 'neprecizată'} · Condiții: {c.conditions || 'neprecizate'}</p><small>{c.reasons.join(', ')}</small></div>)}</details>}
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
  const stage = useRef(null);
  function suggest(text) { setQuery(text); stage.current?.querySelector('textarea')?.focus(); }
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
    e?.preventDefault?.(); if (!query.trim() || busy || loading) return;
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
  return <div className="technical-chat chat-focus" data-has-messages={messages.length > 0}>
    <section className="card conversation-history" aria-label="Conversații precedente">
      <div className="card-heading"><h2><MessageSquareText size={17} aria-hidden="true"/>Conversațiile tale</h2><Button secondary disabled={busy || loading} onClick={reset}><Plus size={17} aria-hidden="true"/>Conversație nouă</Button></div>
      <nav className="conversation-bar" aria-label="Conversații salvate">{conversations.map(c => <button type="button" key={c.id} aria-current={conversation?.id === c.id ? 'true' : undefined} disabled={busy || loading} onClick={() => open(c.id)}><strong>{c.title}</strong><small>{c.project}</small></button>)}</nav>
      {!conversations.length && <p>{loading ? 'Se încarcă istoricul…' : 'Conversațiile vor apărea aici după prima întrebare.'}</p>}
    <details className="chat-settings"><summary>Setări de căutare · opțional</summary><div className="form-grid mt-4">
      <Field label="Proiect" value={project} onChange={setProject} maxLength={200} disabled={!!conversation || busy || loading} />
      <Field label="Fragmente inițiale" options={Array.from({ length: 10 }, (_, i) => String(i + 1))} value={k} onChange={setK} disabled={busy} />
    </div><p className="text-xs mt-3">Istoricul este asociat acestui browser. Ștergerea cookie-ului pierde accesul. Referințele salvate necesită reverificare în surse.</p></details>
    </section>
    <section className="chat-stage" ref={stage} aria-label="Asistent tehnic">
      <Hero1 />
      <ErrorBox error={error} />
      <BranchingReasoningChatInput
        status={busy ? 'answering' : messages.length ? 'done' : 'idle'}
        value={query} onValueChange={setQuery} onSubmit={() => submit()}
        disabled={loading || !project.trim()} placeholder="Care este masa pentru PART123?"
        branches={(busy ? [] : messages.filter(m => m.role === 'assistant').at(-1)?.data?.attempts || []).map(a => ({
          id: String(a.attempt), title: `Căutare ${a.attempt}`,
          note: ({ verified_excerpts: 'Pasaje selectate din surse.', no_matching_evidence: 'Nu au fost găsite dovezi potrivite.', invalid_selection: 'Selecția a necesitat reverificare.', conflicting_sources: 'Au fost găsite valori contradictorii.', insufficient_evidence: 'Dovezile nu au fost suficiente.', generation_timeout: 'Timpul de verificare a expirat.' })[a.outcome] || 'Verificare încheiată.',
          chosen: a.outcome === 'verified_excerpts',
        }))}
        transcript={messages.length ? <div className="messages" role="log" aria-label="Mesaje chat" aria-live="polite">{messages.map((m, i) => <article key={i} className={`message ${m.role}`}><div className="message-author">{m.role === 'user' ? 'TU' : 'ASISTENT TEHNIC'}</div>{m.role === 'user' ? <p className="whitespace-pre-wrap">{m.text}</p> : <Answer data={m.data} onRemember={conversation && !busy ? e => { setSelected(e); setNote(''); } : null} />}</article>)}<div ref={end} /></div> : undefined}
        footer={<div className="live-web-option"><Check label="Cautare Live" value={liveWeb} onChange={setLiveWeb} /><p>Doar întrebarea curentă este trimisă spre web, după Egress Guard. {query.length}/1000</p></div>}
      />
      {!messages.length && <div className="chat-starters" aria-label="Idei de întrebări"><span>Începe cu</span><button type="button" disabled={busy || loading} onClick={() => suggest('Care sunt specificațiile tehnice pentru ')}>Date tehnice <ArrowUpRight size={16} aria-hidden="true"/></button><button type="button" disabled={busy || loading} onClick={() => suggest('Ce prețuri apar în facturi pentru ')}>Prețuri din facturi <ArrowUpRight size={16} aria-hidden="true"/></button></div>}
    </section>
    {selected && <form className="card" onSubmit={remember}><h2>Notă de revizuire</h2><p>{selected.quote}</p><label className="field mt-3"><span>Observație / corecție propusă (nu devine automat fapt verificat)</span><textarea maxLength={1000} value={note} onChange={e => setNote(e.target.value)} rows={3} /></label><Button type="submit" disabled={busy}>Salvează referința</Button></form>}
    {!!references.length && <section className="card"><h2>Referințe păstrate pentru acest proiect / conversație</h2>{references.map(r => <div className="line-card mt-3" key={r.id}><strong>{r.evidence.doc_id} · p. {r.evidence.page}</strong><p>{r.evidence.quote}</p><p className="whitespace-pre-wrap">{r.note}</p><small>Referință istorică; poate necesita reverificare după actualizarea documentului.</small></div>)}</section>}
  </div>;
}
