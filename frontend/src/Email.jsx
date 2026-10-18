import { useState } from 'react';
import { Copy, Languages, Mail } from 'lucide-react';
import { api } from './api';
import { MailAccounts, MailSend, useMailAccounts } from './MailDelivery';
import { Field, Button, Add, Remove, ErrorBox, Card, identified, stripId } from './ui';
import EmailAssistant from './EmailAssistant';
import { emailPreview } from './emailPreview';
import './email.css';
import { languages, units } from './commercialOptions';
const newItem = () => identified({ code: '', description: '', quantity: '', unit: 'pcs' });
export default function Email() {
  const mail = useMailAccounts();
  const [recipient, setRecipient] = useState('');
  const [form, setForm] = useState({ kind: 'rfq', language: 'ro', contact_name: '', reply_by: '', items: [newItem()] });
  const [questions, setQuestions] = useState('');
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const edit = (key, value) => { setForm(f => ({ ...f, [key]: value })); setDraft(null); setCopied(false); };
  const ef = (key, label, props = {}) => <Field label={label} value={form[key]} onChange={v => edit(key, v)} {...props} />;
  const preview = draft || emailPreview(form, questions);
  function addSuggested(item) {
    const blank = form.items.findIndex(i => !i.code && !i.description && !i.quantity);
    if (blank < 0 && form.items.length >= 50) return;
    edit('items', blank >= 0 ? form.items.map((i, n) => n === blank ? { ...i, ...item } : i) : [...form.items, identified(item)]);
  }
  async function submit(e) {
    e.preventDefault();
    const list = questions.split('\n').map(q => q.trim()).filter(Boolean);
    if (form.kind === 'clarification' && (!list.length || list.length > 10)) { setError('Introdu între 1 și 10 întrebări, fiecare pe un rând separat.'); return; }
    setBusy(true); setError(''); setDraft(null); setCopied(false);
    try { setDraft(await api('/emails/draft', { ...form, reply_by: form.reply_by || null, items: form.items.map(item => ({ ...stripId(item), quantity: item.quantity || null })), questions: form.kind === 'clarification' ? list : [] })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function copy() { try { await navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`); setCopied(true); } catch { setError('Copierea automată nu este disponibilă. Selectează și copiază textul din previzualizare.'); } }
  return <><MailAccounts {...mail}/><div className="email-layout"><form onSubmit={submit} onInvalidCapture={e => { const section = e.target.closest("details"); if (section) section.open = true; }}><fieldset disabled={busy} className="space-y-5"><Card title="Configurează mesajul" subtitle="De la cerere la draft, în limba furnizorului."><div className="form-grid"><Field label="Destinatar" type="email" maxLength={254} value={recipient} onChange={setRecipient} placeholder="achizitii@furnizor.ro" />{ef('kind', 'Tip e-mail', { options: [['rfq', 'Cerere de ofertă'], ['clarification', 'Clarificări tehnice']] })}{ef('language', 'Limba mesajului', { options: languages })}</div><details className="advanced-options"><summary>Contact și termen de răspuns · opțional</summary><div className="form-grid">{ef('contact_name', 'Persoană de contact · opțional', { maxLength: 100 })}{ef('reply_by', 'Termen de răspuns · opțional', { type: 'date' })}</div></details></Card><Card title="Articole solicitate" subtitle="Include doar informațiile destinate furnizorului."><EmailAssistant onAdd={addSuggested} disabled={busy || form.items.length >= 50} /><div className="space-y-4">{form.items.map((item, i) => <div className="line-card" key={item._id}><div className="line-heading"><span>ARTICOL {String(i + 1).padStart(2, '0')}</span><Remove disabled={form.items.length === 1} onClick={() => edit('items', form.items.filter(x => x._id !== item._id))} /></div><div className="form-grid">{[['code', 'Cod articol', { required: true, maxLength: 64 }], ['description', 'Descriere · opțional', { maxLength: 300 }], ['quantity', 'Cantitate · opțional', { type: 'number', min: '0.000001', step: 'any' }], ['unit', 'Unitate de măsură', { suggestions: units, maxLength: 20 }]].map(([key, label, props]) => <Field key={key} label={label} value={item[key]} onChange={v => edit('items', form.items.map(x => x._id === item._id ? { ...x, [key]: v } : x))} {...props} />)}</div></div>)}</div><div className="mt-4"><Add disabled={form.items.length >= 50} onClick={() => edit('items', [...form.items, newItem()])}>Adaugă articol</Add></div>{form.kind === 'clarification' && <label className="field mt-5"><span>Întrebări tehnice · una pe rând, maximum 10</span><textarea rows={5} required value={questions} onChange={e => { setQuestions(e.target.value); setDraft(null); }} placeholder="Care este termenul de livrare?" /></label>}</Card><aside className="email-safety-note"><Languages size={22} /><div><strong>Protejează datele clientului</strong><p>Nu include numele clientului final sau al proiectului. Româna și engleza folosesc șabloane fixe; celelalte limbi sunt traduse. Draftul final este verificat de Egress Guard înainte de trimitere.</p></div></aside><Button type="submit" busy={busy} disabled={busy}><Mail size={16} />{busy ? 'Se pregătește draftul…' : 'Generează draftul'}</Button></fieldset><div className="mt-4"><ErrorBox error={error} /></div></form><section className="card draft-preview"><div className="card-heading"><h2>Previzualizare mesaj</h2>{draft && <Button secondary onClick={copy}><Copy size={15} />{copied ? 'Copiat' : 'Copiază'}</Button>}</div><div className={`draft-meta ${draft ? 'verified' : ''}`}>{draft ? `${languages.find(l => l[0] === draft.language)?.[1] || draft.language} · ${draft.translated ? 'Tradus și verificat' : 'Șablon verificat'}` : 'Previzualizare instant · neverificată'}</div>{!draft && <p className="preview-guidance">{busy ? 'Se pregătește și se verifică draftul…' : !['ro', 'en'].includes(form.language) ? 'Previzualizare în engleză. Apasă „Generează draftul” pentru traducerea în limba aleasă și verificare.' : 'Mesajul se actualizează pe măsură ce scrii. Generează draftul pentru verificare și trimitere.'}</p>}<label className="field mt-5"><span>Subiect</span><input readOnly value={preview.subject} /></label><label className="field mt-5" htmlFor="draft-body"><span>Mesaj</span><textarea id="draft-body" className="draft-body" readOnly value={preview.body} rows={18} /></label>{draft && <MailSend draft={draft} accounts={mail.accounts} to={recipient}/>}</section></div></>;
}
