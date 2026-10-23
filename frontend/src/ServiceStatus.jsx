import { useEffect, useState } from 'react';
import { api } from './api';

export default function ServiceStatus() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true);
    try { setResult(await api('/diagnostics')); setError(''); }
    catch { setResult(null); setError('Backend-ul nu poate fi contactat. Verifică pornirea serviciilor Docker.'); }
    finally { setBusy(false); }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 15000); return () => clearInterval(timer); }, []);
  return <details className="card service-status"><summary>
    {busy ? 'Verific serviciile…' : error ? 'Server indisponibil' : result?.ok ? 'Servicii disponibile' : 'Unele servicii necesită atenție'}
  </summary><p>{error || result?.note}</p>
    {result?.services?.map(s => <p key={s.id}><strong>{s.label}</strong> · {s.status === 'ok' ? 'Disponibil' : 'Indisponibil'}{!s.required && ' · serviciu auxiliar'}</p>)}
    <button className="btn secondary" disabled={busy} onClick={refresh}>Verifică din nou</button>
  </details>;
}
