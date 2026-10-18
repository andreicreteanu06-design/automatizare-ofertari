import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { Boxes, MessageSquareText, FileText, Mail, ShieldCheck, ArrowUpRight, FolderOpen } from 'lucide-react';
import Chat from './Chat';
import Offers from './Offers';
import Email from './Email';
import Sources from './Sources';
import PdfEditor from './PdfEditor';
import WorkspaceBackground from './WorkspaceBackground';
import './styles.css';
import './workspace.css';
import SculptureHero from './components/ui/liquid-sculpture-hero';
import '@fontsource/geist/400.css';
import '@fontsource/geist/500.css';
import '@fontsource/geist/600.css';
import '@fontsource/instrument-serif/400-italic.css';

const tabs = [
  { id: 'sources', label: 'Documentele mele', icon: FolderOpen, title: 'Documentele asistentului.', description: 'Încarcă foldere sau conectează surse care se actualizează automat.' },
  { id: 'offers', label: 'Generator oferte', icon: FileText, eyebrow: 'OFERTARE & SAGA', title: 'Pregătește o ofertă.', description: 'Construiește oferta, verifică cerințele și pregătește documentele.' },
  { id: 'chat', label: 'Chat tehnic', icon: MessageSquareText, eyebrow: 'ASISTENT TEHNIC · RAG', title: 'Răspunsuri cu surse.', description: 'Caută informații tehnice și prețuri în documentele interne.' },
  { id: 'email', label: 'Draft e-mail', icon: Mail, eyebrow: 'COMUNICARE CU FURNIZORII', title: 'Scrie furnizorului.', description: 'Pregătește cereri de ofertă și clarificări tehnice pentru furnizori.' },
  { id: 'pdf', label: 'Editor PDF', icon: FileText, title: 'Lucrează pe document.', description: 'Pagini, adnotări și formulare, într-un editor local.' },
];
function App() {
  const initial = () => ['offers', 'chat', 'email', 'sources', 'pdf'].includes(location.hash.slice(1).split('?')[0]) ? location.hash.slice(1).split('?')[0] : 'home';
  const [active, setActive] = useState(initial);
  const [entered, setEntered] = useState(() => initial() !== 'home');
  const navigate = id => { location.hash = id; setActive(id); if (id !== 'home') setEntered(true); };
  useEffect(() => { const change = () => { const id = initial(); setActive(id); if (id !== 'home') setEntered(true); }; window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
  const current = tabs.find(t => t.id === active) || tabs[0];
  return <>{active === 'home' && <SculptureHero brand="ofertare." eyebrow="INTELIGENȚĂ LOCALĂ · OFERTARE B2B"
    headline={'Informația prinde\nformă.'} headlineAccent="formă." backdropText="ofertare"
    body="Transformă documentația tehnică în decizii clare. Consultă sursele, construiește oferte și pregătește următoarea conversație cu furnizorul."
    navLinks={[{ label: 'Chat tehnic', href: '#chat' }, { label: 'Generator oferte', href: '#offers' }, { label: 'Draft e-mail', href: '#email' }]}
    navCta={{ label: 'Deschide aplicația', href: '#offers' }}
    primaryCta={{ label: 'Începe o conversație', href: '#chat' }} secondaryCta={{ label: 'Creează o ofertă', href: '#offers' }}
    hint="Explorează forma" hintTouch="Atinge forma" imageAlt="Sculptură abstractă din filamente metalice"
    loadFonts={false} showCredit={false} particleDensity={0.5} height="max(760px, 100svh)" />}
    {entered && <div hidden={active === 'home'}><div className="shell"><WorkspaceBackground active={active !== 'home'}/><aside className="sidebar"><a className="brand" href="#" onClick={e => { e.preventDefault(); navigate('home'); }}><span className="brand-mark"><Boxes size={23} /></span>ofertare<span className="brand-dot">.</span></a><div className="workspace-label">SPAȚIU DE LUCRU</div><nav aria-label="Navigare principală">{tabs.map(t => <button key={t.id} aria-current={active === t.id ? 'page' : undefined} className={`nav-item ${active === t.id ? 'active' : ''}`} onClick={() => navigate(t.id)}><t.icon size={19} />{t.label}{active === t.id && <ArrowUpRight size={16} className="ml-auto" />}</button>)}</nav><div className="sidebar-note"><ShieldCheck size={22} /><strong>Documente interne.<br />Decizii informate.</strong><p>Un singur loc pentru informații tehnice, oferte și furnizori.</p><span className="local-badge">Resurse servite local</span></div><div className="sidebar-footer">OFERTARE B2B <span>v1.0</span></div></aside><main><header className="topbar"><span>Spațiu de lucru <span className="mx-3 text-stone-300">/</span> <strong>{current.label}</strong></span><span className="internal"><ShieldCheck size={14} />Uz intern</span></header><div className="content"><div className="page-heading" hidden={active === 'chat'}><div><div className="eyebrow">{current.eyebrow}</div><h1>{current.title}</h1><p>{current.description}</p></div><span className="edition">WORKSPACE / 01</span></div>{active === 'sources' && <Sources />}<div hidden={active !== 'pdf'}><PdfEditor /></div><div hidden={active !== 'offers'}><Offers /></div><div hidden={active !== 'chat'}><Chat /></div><div hidden={active !== 'email'}><Email /></div><footer className="page-footer">Ofertare B2B <span>Informațiile și calculele provin din API-ul intern.</span></footer></div></main></div></div>}</>;
}
createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);
