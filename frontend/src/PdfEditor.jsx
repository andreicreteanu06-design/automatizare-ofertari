import { useEffect, useRef, useState } from 'react';
import { Expand, FilePenLine } from 'lucide-react';
import { Button, Card } from './ui';
import './pdf-editor.css';

export default function PdfEditor() {
  const [opened, setOpened] = useState(false);
  const [error, setError] = useState('');
  const frame = useRef(null);
  useEffect(() => {
    if (!opened) return;
    const warn = e => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [opened]);
  async function fullscreen() {
    try { await frame.current.requestFullscreen(); }
    catch { setError('Ecranul complet nu este disponibil în acest browser. Poți folosi editorul mai jos.'); }
  }
  return <section className="pdf-workspace">
    <Card title="Documentul rămâne la tine" subtitle="Deschide un PDF de pe calculator, lucrează pe el și descarcă rezultatul.">
      <p>Editorul rulează local în browser. Fișierele deschise aici nu sunt trimise automat către server sau către chat.</p>
      <details className="advanced-options"><summary>Ce poți face în editor</summary>
        <ul className="pdf-help"><li><strong>Pagini:</strong> rotire, reordonare, ștergere, extragere și combinarea documentelor.</li>
          <li><strong>Note și formulare:</strong> adnotări, text adăugat și completarea câmpurilor PDF.</li>
          <li><strong>Text existent:</strong> editare cu limitări. Nu toate PDF-urile, fonturile și limbile pot fi editate fidel; textul scanat este o imagine.</li></ul>
        <p>Folosește Open pentru deschidere, All tools pentru instrumente și Save / Export pentru descărcare. Verifică documentul rezultat înainte de utilizare. Pentru a-l folosi în chat, salvează copia în folderul monitorizat.</p>
      </details>
      <div className="source-actions">{!opened ? <Button onClick={() => setOpened(true)}><FilePenLine size={18}/>Deschide editorul PDF</Button> : <Button secondary onClick={fullscreen}><Expand size={18}/>Ecran complet</Button>}
        <span className="pdf-save-note">Salvează modificările înainte de reîncărcarea sau închiderea aplicației.</span></div>
      {error && <p role="alert">{error}</p>}
    </Card>
    {opened && <div className="pdf-frame-wrap"><iframe ref={frame} title="Editor PDF" src="/pdfcraft/index.html?cpu" sandbox="allow-scripts allow-downloads" allow="fullscreen" allowFullScreen referrerPolicy="no-referrer" />
      <p>Editor local · Interfața editorului este independentă de formularele aplicației.</p></div>}
  </section>;
}
