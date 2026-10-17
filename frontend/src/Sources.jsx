import { useEffect, useRef, useState } from 'react';
import { FolderOpen, Upload, RefreshCw, Cloud, FolderPlus } from 'lucide-react';
import { api, errorText } from './api';
import { Button, Card, ErrorBox, Field } from './ui';

const labels = { ready: 'Actualizat', pending: 'În așteptare', indexing: 'Se procesează', indexed: 'Disponibil în chat', error: 'Necesită verificare', attention: 'Unele fișiere au erori', removed: 'Eliminat din căutare' };
const formats = ['pdf', 'docx', 'xlsx', 'txt', 'md', 'csv'];
async function mutate(path, body, binary = false) {
  const response = await fetch('/api/sources' + path, { method: 'POST', headers: { 'X-Source-Action': '1', 'Content-Type': binary ? 'application/octet-stream' : 'application/json' }, body: binary ? body : JSON.stringify(body) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(errorText(data?.detail) || 'Operația a eșuat.');
  return data;
}

export default function Sources() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [folders, setFolders] = useState([]);
  const [browsePath, setBrowsePath] = useState('');
  const [driveName, setDriveName] = useState('');
  const [driveId, setDriveId] = useState('');
  const [progress, setProgress] = useState('');
  const picker = useRef(null);
  async function refresh() {
    try { setData(await api('/sources')); } catch (e) { setError(e.message); }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 10000); return () => clearInterval(timer); }, []);
  async function browse(path = '') {
    setError('');
    try { const result = await api('/sources/folders?path=' + encodeURIComponent(path)); setFolders(result.folders); setBrowsePath(path); }
    catch (e) { setError(e.message); }
  }
  async function add(source) {
    setBusy(true); setError(''); setNotice('');
    try { await mutate('', source); setNotice('Sursă adăugată. Fișierele vor apărea în chat după indexare.'); await refresh(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function upload(event) {
    const all = Array.from(event.target.files || []);
    const files = all.filter(f => formats.includes(f.name.split('.').pop().toLowerCase()));
    if (!files.length) { setError('Folderul nu conține formate acceptate.'); return; }
    if (files.length > 1000 || files.some(f => f.size > 40 * 1024 * 1024)) { setError('Maximum 1.000 de fișiere, fiecare de cel mult 40 MB.'); return; }
    setBusy(true); setError(''); setNotice('');
    let sid;
    let completed = 0;
    try {
      const name = files[0].webkitRelativePath.split('/')[0] || 'Documente încărcate';
      sid = (await mutate('', { kind: 'upload', name })).id;
      for (const file of files) {
        setProgress(`Se încarcă ${completed + 1} din ${files.length}: ${file.name}`);
        await mutate(`/${sid}/upload?path=${encodeURIComponent(file.webkitRelativePath || file.name)}`, file, true);
        completed++;
      }
      setNotice(`${completed} fișiere încărcate. ${all.length - files.length} fișiere cu alte formate au fost omise. Indexarea continuă pe server.`);
    } catch (e) { setError(`${e.message} ${completed} fișiere au fost încărcate; sursa rămâne în listă.`); }
    finally { setBusy(false); setProgress(''); event.target.value = ''; await refresh(); }
  }
  return <div className="source-library space-y-5">
    <Card title="De unde citește asistentul?" subtitle="Documentele sunt comune acestui spațiu de lucru. Conectează doar folderele pe care vrei să le poată consulta.">
      <p>Fișiere PDF, Word, Excel, text, Markdown și CSV · maximum 40 MB per fișier. Documentele devin disponibile după procesare, nu imediat după copiere.</p>
      <div className="source-actions">
        <Button disabled={busy} onClick={() => picker.current.click()}><Upload size={18}/>Încarcă un folder</Button>
        <input ref={picker} className="sr-only" type="file" webkitdirectory="" multiple aria-label="Folder de încărcat" onChange={upload} disabled={busy}/>
        <Button secondary disabled={busy} onClick={refresh}><RefreshCw size={18}/>Actualizează starea</Button>
      </div>
      <p className="note mt-4">Încărcarea salvează o copie. Pentru fișiere noi și modificări automate, conectează un folder monitorizat mai jos.</p>
      <details className="advanced-options" onToggle={e => { if (e.currentTarget.open) browse(''); }}><summary><FolderOpen size={18}/>Conectează un folder monitorizat</summary>
        <p>Administratorul pune directoarele de lucru în folderul autorizat prin configurarea Docker. Originalele sunt accesate doar pentru citire. Verificarea are loc la aproximativ 30 de secunde, între procesări.</p>
        <div className="source-actions"><Button secondary disabled={!browsePath || busy} onClick={() => browse(browsePath.split('/').slice(0, -1).join('/'))}>Înapoi</Button><span>{browsePath || 'Foldere autorizate'}</span></div>
        {!folders.length && <p>Nu există subfoldere aici. Configurează CLIENT_DOCUMENTS_PATH la instalare sau adaugă un subfolder în directorul autorizat.</p>}
        {folders.map(f => <div className="source-folder" key={f.path}><span><FolderOpen size={18}/>{f.name}</span><Button secondary disabled={busy} onClick={() => browse(f.path)}>Deschide</Button><Button disabled={busy} onClick={() => add({ kind: 'local', name: f.name, path: f.path })}><FolderPlus size={16}/>Conectează</Button></div>)}
      </details>
      <details className="advanced-options"><summary><Cloud size={18}/>Conectează un folder Google Drive</summary><p>Necesită configurarea serviciului Workspace CLI de către administrator și acces de citire la folder. Nu încarcă documentele locale în Google.</p><div className="form-grid mt-4"><Field label="Numele sursei Drive" value={driveName} onChange={setDriveName} maxLength={100}/><Field label="ID folder Google Drive" value={driveId} onChange={setDriveId} maxLength={200} placeholder="ID-ul de după /folders/ din adresă"/></div><div className="mt-4"><Button disabled={busy || !driveName.trim() || !/^[A-Za-z0-9_-]{10,200}$/.test(driveId)} onClick={() => add({ kind: 'drive', name: driveName.trim(), path: driveId })}>Conectează Google Drive</Button></div></details>
    </Card>
    {progress && <p role="status">{progress}</p>}{notice && <p role="status" className="success">{notice}</p>}<ErrorBox error={error}/>
    {data && !data.worker_active && <div className="warning">Monitorizarea nu este activă momentan. Administratorul trebuie să pornească serviciul source-watch. Fișierele din aceste surse nu sunt folosite în răspunsuri cât timp serviciul este oprit.</div>}
    {data?.sources.length === 0 && <Card title="Biblioteca ta începe aici"><p>Încarcă un folder sau conectează o sursă pentru actualizare automată.</p></Card>}
    {data?.sources.map(source => <Card key={source.id} title={source.name} subtitle={`${({ local: 'Folder monitorizat', upload: 'Copie încărcată', drive: 'Google Drive · Workspace CLI' })[source.kind]} · ${labels[source.status] || source.status}`}>
      <p>{source.counts.indexed || 0} documente indexate · ultima verificare: {source.checked ? new Date(source.checked * 1000).toLocaleString('ro-RO') : 'în așteptare'}</p><ErrorBox error={source.error}/>
      <details className="advanced-options"><summary>Vezi documentele și starea lor</summary><p>Ultimele 50 de documente. Fișierele modificate se reprocesează; cele șterse sunt retrase din căutările noi.</p>{source.files.map(file => <div className="source-file" key={file.path}><strong>{file.path}</strong><span>{labels[file.status] || file.status}</span><small>{file.doc_id}</small>{file.error && <p>{file.error}</p>}</div>)}</details>
    </Card>)}
  </div>;
}
