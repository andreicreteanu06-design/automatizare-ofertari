import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { Button } from './ui';
import { sourceMutation } from './sourceActions';

export default function RemoveSource({ source, onRemoved, onError, disabled = false }) {
  const [busy, setBusy] = useState(false);
  async function remove() {
    const detail = source.kind === 'upload'
      ? 'Copiile încărcate în aplicație și indexul lor vor fi șterse de serviciul de procesare. Originalele de pe calculator rămân păstrate.'
      : 'Conexiunea și indexul vor fi eliminate. Fișierele originale din folder sau Google Drive rămân păstrate.';
    if (!window.confirm(`Elimini „${source.name}” din bibliotecă și din căutările noi?\n\n${detail}`)) return;
    setBusy(true);
    try {
      await sourceMutation('/' + encodeURIComponent(source.id), undefined, false, 'DELETE');
      await onRemoved();
    } catch (e) { onError(e.message); }
    finally { setBusy(false); }
  }
  return <Button secondary disabled={busy || disabled} busy={busy} onClick={remove}
    aria-label={`Elimină folderul ${source.name}`}><Trash2 size={16}/><span>Elimină</span></Button>;
}
