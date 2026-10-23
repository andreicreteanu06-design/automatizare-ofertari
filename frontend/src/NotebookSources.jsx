import { useEffect, useState } from 'react';
import { FolderOpen, FileText, RefreshCw, Plus } from 'lucide-react';
import { api } from './api';
import { Button, ErrorBox } from './ui';
import RemoveSource from './RemoveSource';

export default function NotebookSources() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true);
    try { setData(await api('/sources')); setError(''); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 30000); return () => clearInterval(timer); }, []);
  return <aside className="notebook-sources" aria-label="Surse din bibliotecă"><header><h2><FolderOpen size={19}/>Surse</h2><Button secondary disabled={busy} onClick={refresh} aria-label="Actualizează sursele"><RefreshCw size={16}/></Button></header>
    <a className="notebook-add" href="#sources"><Plus size={17}/>Adaugă documente</a>
    <p>Chatul caută în biblioteca internă și în facturile indexate. Nu trebuie să copiezi documentele în conversație.</p>
    {data && <p className="notebook-count">{data.sources.reduce((sum, source) => sum + (source.counts.indexed || 0), 0)} documente indexate în foldere</p>}
    {data && !data.worker_active && <p className="warning">Procesarea documentelor este oprită. Fișierele încărcate sunt păstrate; vor putea fi folosite după repornirea procesării. <a href="#sources">Vezi starea folderelor</a>.</p>}
    <ErrorBox error={error}/>{!data && !error && <p>Se încarcă sursele…</p>}
    {data?.sources.length === 0 && <p>Nu ai conectat încă foldere. Adaugă documente, apoi așteaptă indexarea.</p>}
    {data?.sources.map(source => <details className="notebook-folder" key={source.id} open><summary><FolderOpen size={16}/><span>{source.name}</span><small>{source.counts.indexed || 0}</small></summary><p>{source.status === 'ready' ? 'Actualizat' : source.status === 'error' ? 'Sursă indisponibilă' : 'Verifică starea indexării'}</p>{source.files.map(file => <div className="notebook-file" key={file.path}><FileText size={15}/><span>{file.path}<small>{file.status === 'indexed' ? 'Indexat' : file.status === 'removed' ? 'Retras din căutare' : file.status === 'error' ? 'Eroare de procesare' : 'În așteptarea procesării'}</small></span></div>)}{source.files.length >= 50 && <small>Sunt afișate cele mai recente 50 de fișiere; căutarea include toate documentele indexate.</small>}<RemoveSource source={source} onRemoved={refresh} onError={setError}/></details>)}
  </aside>;
}
