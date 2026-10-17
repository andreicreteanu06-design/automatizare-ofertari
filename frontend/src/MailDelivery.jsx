import { useEffect, useState } from 'react';
import { Send, RefreshCw, Unplug } from 'lucide-react';
import { api } from './api';
import { Button, Field, ErrorBox } from './ui';

export function ProviderLogo({ provider }) {
  return provider === 'google' ? <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24"><path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-2 3.02v2.51h3.24c1.9-1.75 2.98-4.33 2.98-7.36Z"/><path fill="#34A853" d="M12 22c2.7 0 4.96-.9 6.62-2.41l-3.24-2.51c-.9.6-2.04.96-3.38.96-2.6 0-4.8-1.76-5.59-4.12H3.07v2.59A10 10 0 0 0 12 22Z"/><path fill="#FBBC05" d="M6.41 13.92a6 6 0 0 1 0-3.84V7.49H3.07a10 10 0 0 0 0 9.02l3.34-2.59Z"/><path fill="#EA4335" d="M12 5.96c1.47 0 2.79.51 3.83 1.51l2.87-2.87A9.62 9.62 0 0 0 12 2a10 10 0 0 0-8.93 5.49l3.34 2.59A6 6 0 0 1 12 5.96Z"/></svg> : <svg aria-hidden="true" width="22" height="22" viewBox="0 0 22 22"><path fill="#f25022" d="M1 1h9v9H1z"/><path fill="#7fba00" d="M12 1h9v9h-9z"/><path fill="#00a4ef" d="M1 12h9v9H1z"/><path fill="#ffb900" d="M12 12h9v9h-9z"/></svg>;
}

export function MailAccounts({ accounts, refresh, error, loading }) {
  const [busy, setBusy] = useState('');
  const [failure, setFailure] = useState('');
  async function connect(provider) {
    const tab = window.open('about:blank', '_blank');
    if (tab) tab.opener = null;
    setBusy(provider); setFailure('');
    try {
      const result = await api(`/emails/accounts/${provider}/connect`, {});
      if (tab) tab.location.href = result.url;
      else throw new Error('Permite deschiderea unui tab nou pentru conectare.');
    } catch (e) { tab?.close(); setFailure(e.message); }
    finally { setBusy(''); }
  }
  async function disconnect(provider) {
    setBusy(provider); setFailure('');
    try { await api(`/emails/accounts/${provider}/disconnect`, {}); await refresh(); }
    catch (e) { setFailure(e.message); } finally { setBusy(''); }
  }
  return <section className="card mail-accounts"><div className="card-heading"><div><h2>Conectează e-mailul</h2><p>Alege contul din care vrei să trimiți ofertele și cererile.</p></div><Button secondary disabled={loading || !!busy} onClick={refresh} aria-label="Actualizează conturile"><RefreshCw size={16}/></Button></div>
    <div className="mail-provider-grid">{['google', 'microsoft'].map(provider => {
      const account = accounts.find(a => a.provider === provider);
      const name = provider === 'google' ? 'Google / Gmail' : 'Microsoft / Outlook';
      return <div className="mail-provider" key={provider}><div className="mail-provider-name"><ProviderLogo provider={provider}/><strong>{name}</strong></div><p>{account?.connected ? account.email : account?.configured ? 'Conectare securizată în pagina furnizorului.' : loading ? 'Se verifică disponibilitatea…' : 'Necesită configurarea OAuth de către administrator.'}</p>{account?.connected ? <Button secondary disabled={!!busy} onClick={() => disconnect(provider)}><Unplug size={15}/>Deconectează {provider === 'google' ? 'Google' : 'Microsoft'}</Button> : <Button secondary disabled={loading || !!busy || !account?.configured} onClick={() => connect(provider)}>Conectează cu {provider === 'google' ? 'Google' : 'Microsoft'}</Button>}</div>;
    })}</div><p className="note mt-4">Acces pentru trimitere. Citirea și triajul atașamentelor se configurează separat prin IMAP. După autorizare, revino în acest tab.</p><ErrorBox error={failure || error}/>{location.hash.includes('oauth=connected') && <p role="status">Cont conectat. Poți reveni în tabul în care pregăteai mesajul.</p>}{location.hash.includes('oauth=error') && <ErrorBox error="Conectarea nu a fost finalizată. Reia autorizarea contului."/>}</section>;
}

export function MailSend({ draft, accounts, to }) {
  const [provider, setProvider] = useState('');
  useEffect(() => { setConfirmed(false); }, [to]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState('');
  const [attemptedRecipient, setAttemptedRecipient] = useState('');
  const [requestId] = useState(() => crypto.randomUUID());
  const connected = accounts.filter(a => a.connected);
  const selected = connected.find(a => a.provider === provider);
  async function send(e) {
    e.preventDefault(); setBusy(true); setError(''); setAttemptedRecipient(to);
    try { const response = await api('/emails/send', { provider, to, subject: draft.subject, body: draft.body, confirmed, request_id: requestId }); setResult(response.status); }
    catch (e) { setError(e.message); setResult(e.status && e.status < 500 ? '' : 'unknown'); }
    finally { setBusy(false); }
  }
  return <form className="mail-send" onSubmit={send}><h3>Trimite mesajul</h3><fieldset disabled={busy || !!result} className="space-y-4"><Field label="Trimite din contul" value={provider} onChange={v => { setProvider(v); setConfirmed(false); }} options={ [['', 'Alege contul conectat'], ...connected.map(a => [a.provider, a.email])] } required/><p className="send-recipient">Destinatar: {to || 'Completează adresa în formularul de mai sus.'}</p><label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/><span>Am verificat destinatarul și mesajul de mai sus și confirm trimiterea.</span></label><Button type="submit" busy={busy} disabled={!selected || !confirmed || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to) || busy || !!result}><Send size={16}/>{busy ? 'Se trimite…' : 'Trimite e-mailul'}</Button></fieldset>{!connected.length && <p className="note mt-4">Conectează Google sau Microsoft pentru a trimite din aplicație.</p>}<ErrorBox error={error}/>{result && <p role="status" className="note mt-4">Destinatarul încercării: {attemptedRecipient}. {result === 'accepted' ? 'Mesaj acceptat de furnizor pentru trimitere. Livrarea în inbox nu este încă confirmată.' : result === 'rejected' ? 'Furnizorul a refuzat trimiterea. Verifică permisiunile contului înainte de a pregăti un nou mesaj.' : 'Rezultat neconfirmat. Verifică folderul Trimise înainte de a pregăti un nou mesaj. Nu retrimitem automat.'}</p>}</form>;
}

export function useMailAccounts() {
  const [accounts, setAccounts] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  async function refresh() {
    setLoading(true);
    try { setAccounts(await api('/emails/accounts')); setError(''); }
    catch (e) { setAccounts([]); setError(e.message); } finally { setLoading(false); }
  }
  useEffect(() => { refresh(); window.addEventListener('focus', refresh); return () => window.removeEventListener('focus', refresh); }, []);
  return { accounts, refresh, error, loading };
}
