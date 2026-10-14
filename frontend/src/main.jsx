import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Boxes, MessageSquareText, FileText, Mail, ShieldCheck, ArrowUpRight } from 'lucide-react';
import Chat from './Chat';
import Offers from './Offers';
import Email from './Email';
import './styles.css';

const tabs = [
  { id: 'offers', label: 'Generator oferte', icon: FileText, eyebrow: 'OFERTARE & SAGA', title: 'De la articol la ofertă.', description: 'Construiește oferta, verifică cerințele și pregătește documentele.' },
  { id: 'chat', label: 'Chat tehnic', icon: MessageSquareText, eyebrow: 'ASISTENT TEHNIC · RAG', title: 'Răspunsuri cu surse.', description: 'Caută informații tehnice și prețuri în documentele interne.' },
  { id: 'email', label: 'Draft e-mail', icon: Mail, eyebrow: 'COMUNICARE CU FURNIZORII', title: 'Un mesaj. Zece limbi.', description: 'Pregătește cereri de ofertă și clarificări tehnice pentru furnizori.' },
];
function App() {
  const [active, setActive] = useState('offers');
  const current = tabs.find(t => t.id === active);
  return <div className="shell"><aside className="sidebar"><a className="brand" href="#" onClick={e => { e.preventDefault(); setActive('offers'); }}><span className="brand-mark"><Boxes size={23} /></span>ofertare<span className="brand-dot">.</span></a><div className="workspace-label">SPAȚIU DE LUCRU</div><nav aria-label="Navigare principală">{tabs.map(t => <button key={t.id} aria-current={active === t.id ? 'page' : undefined} className={`nav-item ${active === t.id ? 'active' : ''}`} onClick={() => setActive(t.id)}><t.icon size={19} />{t.label}{active === t.id && <ArrowUpRight size={16} className="ml-auto" />}</button>)}</nav><div className="sidebar-note"><ShieldCheck size={22} /><strong>Documente interne.<br />Decizii informate.</strong><p>Un singur loc pentru informații tehnice, oferte și furnizori.</p><span className="local-badge">Resurse servite local</span></div><div className="sidebar-footer">OFERTARE B2B <span>v1.0</span></div></aside><main><header className="topbar"><span>Spațiu de lucru <span className="mx-3 text-stone-300">/</span> <strong>{current.label}</strong></span><span className="internal"><ShieldCheck size={14} />Uz intern</span></header><div className="content"><div className="page-heading"><div><div className="eyebrow">{current.eyebrow}</div><h1>{current.title}</h1><p>{current.description}</p></div><span className="edition">WORKSPACE / 01</span></div><div hidden={active !== 'offers'}><Offers /></div><div hidden={active !== 'chat'}><Chat /></div><div hidden={active !== 'email'}><Email /></div><footer className="page-footer">Ofertare B2B <span>Informațiile și calculele provin din API-ul intern.</span></footer></div></main></div>;
}
createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);
