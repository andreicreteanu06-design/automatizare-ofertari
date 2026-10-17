import { useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';

export default function WorkspaceBackground({ active }) {
  const video = useRef(null);
  const [reduced, setReduced] = useState(true);
  const [paused, setPaused] = useState(() => localStorage.getItem('ofertare-background-paused') === 'true');
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(media.matches);
    update(); media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    const update = () => {
      if (!video.current) return;
      if (active && !paused && !reduced && !document.hidden) video.current.play().catch(() => setPaused(true));
      else video.current.pause();
    };
    update(); document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, [active, paused, reduced]);
  return <><div className="workspace-backdrop" aria-hidden="true"><img src="/backgrounds/skylight-fish-swarm.jpg" alt=""/>{!reduced && <video ref={video} muted loop playsInline preload="metadata" poster="/backgrounds/skylight-fish-swarm.jpg" src="/backgrounds/skylight-fish-swarm.mp4"/>}</div><button className="background-control" type="button" disabled={reduced} aria-pressed={paused || reduced} onClick={() => { const value = !paused; setPaused(value); localStorage.setItem('ofertare-background-paused', String(value)); }}>{paused || reduced ? <Play size={15}/> : <Pause size={15}/>}<span>{reduced ? 'Fundal static' : paused ? 'Pornește fundalul' : 'Pauză fundal'}</span></button></>;
}
