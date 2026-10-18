import { useEffect, useState } from 'react';
import { api } from './api';

export default function AuthGate({ children }) {
  const [session, setSession] = useState(null);
  const [error, setError] = useState('');
  async function load() {
    setError('');
    try { setSession(await api('/auth/session')); }
    catch { setError('Serverul nu este disponibil. Pornește serviciile Docker, apoi încearcă din nou.'); }
  }
  useEffect(() => { load(); }, []);
  if (session && (!session.enabled || session.user)) return <>
    {session.user && <div className="account-bar"><span>Conectat: {session.user.email || session.user.name}</span>
      <button className="btn secondary" onClick={async () => {
        try { await api('/auth/logout', {}); location.reload(); }
        catch { setError('Deconectarea a eșuat. Reîncearcă.'); }
      }}>Deconectare</button>{error && <span role="alert">{error}</span>}</div>}{children}</>;
  return <main className="login-page"><section className="card"><h1>Bine ai venit în ofertare.</h1>
    <p>Conectează-te cu contul organizației pentru a accesa documentele și conversațiile.</p>
    {error ? <><p role="alert">{error}</p><button className="btn" onClick={load}>Încearcă din nou</button>
      <p>Poți consulta interfața fără conexiune. Datele și serviciile backend rămân indisponibile.</p>
      <button className="btn secondary" onClick={() => setSession({enabled:false})}>Vezi interfața</button></>
      : !session ? <p>Verific conexiunea…</p> : <>
        {location.search.includes('login=failed') && <p role="alert">Conectarea nu a reușit sau contul nu aparține unei organizații autorizate.</p>}
        <div className="source-actions"><a className="btn" href="/api/auth/microsoft/login">Conectare cu Microsoft 365</a>
          <a className="btn secondary" href="/api/auth/google/login">Conectare cu Google Workspace</a></div></>}
  </section></main>;
}
