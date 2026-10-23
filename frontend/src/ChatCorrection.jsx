import { useState } from 'react';
import { api } from './api';
import { Button, ErrorBox } from './ui';

export default function ChatCorrection({ conversation, response, onSaved, onCancel }) {
  const [note, setNote] = useState('');
  const [ids, setIds] = useState(() => (response.evidence || []).map(e => e.id));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api(`/conversations/${conversation.id}/corrections`, { request_id: response.request_id, evidence_ids: ids, note: note.trim() });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <form className="card chat-correction" onSubmit={save}>
    <h2>Corectează răspunsul</h2>
    <p>Corecția se păstrează pentru proiectul „{conversation.project}”, inclusiv în conversațiile noi din acest spațiu. Pasajele bifate vor fi excluse la întrebări similare; observația va fi folosită pentru reverificare în surse.</p>
    <p>Valoarea propusă trebuie susținută de un document. Dacă nu există alt pasaj potrivit, chatul va spune că nu are dovezi suficiente.</p>
    <label className="field mt-3"><span>Ce trebuie corectat?</span><textarea value={note} onChange={e => setNote(e.target.value)} maxLength={1000} required rows={3}/></label>
    {!!response.evidence?.length && <fieldset disabled={busy}><legend>Pasaje care conțin greșeala</legend>{response.evidence.map(e => <label className="check mt-3" key={e.id}><input type="checkbox" checked={ids.includes(e.id)} onChange={event => setIds(old => event.target.checked ? [...old, e.id] : old.filter(id => id !== e.id))}/><span>{e.doc_id} · p. {e.page}: {e.quote}</span></label>)}</fieldset>}
    <ErrorBox error={error}/><div className="source-actions mt-3"><Button type="submit" busy={busy} disabled={busy || !note.trim()}>Salvează corecția</Button><Button secondary disabled={busy} onClick={onCancel}>Anulează</Button></div>
  </form>;
}
