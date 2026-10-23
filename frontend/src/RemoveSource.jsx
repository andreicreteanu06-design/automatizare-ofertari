import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { Button } from './ui';
import { sourceMutation } from './sourceActions';

export default function RemoveSource({ source, file, onRemoved, onError, disabled = false }) {
  const [busy, setBusy] = useState(false);
  async function remove() {
    const detail = file
      ? (source.kind === 'upload'
        ? 'Doar copia acestui document din aplicație și indexul ei vor fi șterse. Originalul de pe calculator și celelalte documente rămân păstrate.'
        : 'Documentul va fi exclus din această sursă, inclusiv la verificările viitoare. Originalul și celelalte documente rămân păstrate.')
      : source.kind === 'upload'
        ? 'Copiile încărcate în aplicație și indexul lor vor fi șterse de serviciul de procesare. Originalele de pe calculator rămân păstrate.'
        : 'Conexiunea și indexul vor fi eliminate. Fișierele originale din folder sau Google Drive rămân păstrate.';
    if (!window.confirm(`Elimini „${file ? file.path : source.name}” din bibliotecă și din căutările noi?\n\n${detail}`)) return;
    setBusy(true);
    try {
      const path = '/' + encodeURIComponent(source.id) + (file ? '/files/' + encodeURIComponent(file.doc_id) : '');
      await sourceMutation(path, undefined, false, 'DELETE');
      await onRemoved();
    } catch (e) { onError(e.message); }
    finally { setBusy(false); }
  }
  if (file) return <button type="button" className="icon-button" disabled={busy || disabled || !file.doc_id}
    onClick={remove} title="Elimină acest document" aria-label={`Elimină documentul ${file.path}`} aria-busy={busy}><Trash2 size={16}/></button>;
  return <Button secondary disabled={busy || disabled} busy={busy} onClick={remove}
    aria-label={`Elimină folderul ${source.name}`}><Trash2 size={16}/><span>Elimină</span></Button>;
}
