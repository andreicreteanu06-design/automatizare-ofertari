import { BookOpen } from 'lucide-react';

/** Reference-inspired local header; the host owns the real chat and its sources. */
export function Hero1() {
  return <div className="chat-stage-heading chat-hero">
    <div className="chat-light-beams" aria-hidden="true"><i /><i /><i /></div>
    <div className="chat-hero-content">
      <div className="chat-signature"><BookOpen size={18} strokeWidth={1.5} /><span>Asistentul tău tehnic</span></div>
      <h2>Documentele tale.<br /><em>Răspunsuri cu surse.</em></h2>
      <p>Întreabă despre o piesă, o specificație sau un preț.</p>
    </div>
  </div>;
}
