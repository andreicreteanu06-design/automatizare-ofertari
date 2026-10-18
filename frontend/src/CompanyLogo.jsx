import { useState } from 'react';
import { Button, ErrorBox } from './ui';

export default function CompanyLogo({ value, onChange, disabled }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function load(e) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setError(''); setBusy(true);
    try {
      if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > 512 * 1024) throw new Error('Alege un logo PNG sau JPEG de cel mult 512 KB.');
      const raw = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
      const img = new Image();
      img.src = raw;
      await img.decode();
      if (img.width > 1024 || img.height > 1024) throw new Error('Logo-ul poate avea cel mult 1024 × 1024 pixeli.');
      // Re-encode locally: metadata does not travel with the message.
      const canvas = document.createElement('canvas');
      canvas.width = img.width; canvas.height = img.height;
      canvas.getContext('2d').drawImage(img, 0, 0);
      const base64 = canvas.toDataURL('image/png').split(',')[1];
      if (base64.length > 699052) throw new Error('Imaginea PNG rezultată depășește 512 KB. Alege un logo mai mic.');
      onChange(base64);
    } catch (e) { setError(e.message || 'Imaginea nu a putut fi citită.'); }
    finally { setBusy(false); }
  }
  return <details className="advanced-options company-logo"><summary>Logo-ul firmei · opțional</summary><p>PNG/JPEG, maximum 512 KB și 1024 × 1024 pixeli. Se adaugă la finalul e-mailului. Verifică imaginea: Egress Guard verifică textul mesajului, nu textul din logo.</p><label className="field"><span>Alege logo-ul firmei</span><input type="file" accept="image/png,image/jpeg" disabled={disabled || busy} onChange={load}/></label>{busy && <p role="status">Se pregătește logo-ul…</p>}{value && <div className="company-logo-sample"><img src={`data:image/png;base64,${value}`} alt="Logo-ul firmei selectat"/><Button secondary disabled={disabled || busy} onClick={() => onChange(null)}>Elimină logo-ul</Button></div>}<ErrorBox error={error}/></details>;
}
