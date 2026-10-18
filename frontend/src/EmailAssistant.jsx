import { useState } from 'react';
import { MessageCircle, Search } from 'lucide-react';
import { api } from './api';
import { Button, ErrorBox } from './ui';

export default function EmailAssistant({ onAdd, disabled }) {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function ask(chat) {
    if (busy || query.trim().length < 2) return;
    const question = query.trim();
    setBusy(true); setError('');
    setMessages(m => [...m, { question }]);
    try {
      const result = chat ? await api('/chat', { query: question, live_web: false }) : await api(`/articles/search?q=${encodeURIComponent(question)}`);
      const candidates = chat ? result.exact || [] : result.items || [];
      setMessages(m => [...m, { answer: result.answer || (candidates.length ? 'Am găsit aceste articole în facturi. Alege varianta potrivită.' : 'Nu am găsit articole. Încearcă o parte din denumire sau întreabă documentele.'), candidates, citations: result.citations || [] }]);
      setQuery('');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <details className="email-assistant"><summary><MessageCircle size={20} /><span>Nu știi codul? Te ajută asistentul.</span></summary><p>Caută după denumire în facturi sau pune o întrebare despre documentele interne. Fiecare întrebare este independentă.</p>
    <div className="email-assistant-history" aria-live="polite">{messages.map((m, i) => <div className={m.question ? 'assistant-question' : 'assistant-answer'} key={i}><p className="whitespace-pre-wrap">{m.question || m.answer}</p>{m.citations?.map((c, n) => <small key={n}>{c.doc_id} · p. {c.page} </small>)}{m.candidates?.filter(c => c.seller_code && c.seller_code.length <= 64).map((c, n) => <div className="article-suggestion" key={n}><strong>{c.seller_code}</strong><p>{c.name}</p><small>{c.supplier} · factura {c.invoice_number} · {c.issue_date}</small><Button secondary disabled={disabled || busy} onClick={() => onAdd({ code: c.seller_code, description: (c.name || '').slice(0, 300), unit: (c.unit_code || 'pcs').slice(0, 20), quantity: '' })}>Adaugă în e-mail</Button></div>)}</div>)}</div>
    <label className="field"><span>Denumire articol sau întrebare</span><textarea value={query} onChange={e => setQuery(e.target.value)} rows={2} maxLength={1000} placeholder="De exemplu: rulment sau Ce rulment apare în fișa motorului?" /></label>
    <div className="assistant-actions"><Button secondary disabled={busy || query.trim().length < 2 || query.trim().length > 200} onClick={() => ask(false)}><Search size={16} />Caută în facturi</Button><Button disabled={busy || query.trim().length < 2} onClick={() => ask(true)}><MessageCircle size={16} />Întreabă documentele</Button></div>
    {busy && <p role="status">Caut în sursele interne…</p>}<ErrorBox error={error} /><small>Adaugă doar articolele confirmate. Cantitățile și prețurile istorice nu sunt preluate automat.</small>
  </details>;
}
