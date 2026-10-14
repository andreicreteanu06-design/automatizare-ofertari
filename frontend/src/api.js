export function errorText(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(d => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('\n');
  if (!detail) return 'Răspuns invalid de la server.';
  return [detail.error, ...(detail.failures || []).map(f => f.message),
    detail.rules?.length && `Reguli: ${detail.rules.join(', ')}`,
    detail.missing_codes?.length && `Coduri lipsă: ${detail.missing_codes.join(', ')}`,
    detail.invented_codes?.length && `Coduri inventate: ${detail.invented_codes.join(', ')}`].filter(Boolean).join('\n') || JSON.stringify(detail);
}

export async function api(path, body, binary = false) {
  let response;
  try {
    response = await fetch(`/api${path}`, { cache: 'no-store', ...(body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }) });
  } catch { throw new Error('Conexiunea cu serverul a eșuat. Verifică rețeaua internă și încearcă din nou.'); }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const error = new Error(`HTTP ${response.status} · ${data ? errorText(data.detail || data) : 'Serviciul nu este disponibil.'}`);
    error.status = response.status;
    error.detail = data?.detail;
    throw error;
  }
  if (binary) return response;
  if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Serverul nu a returnat JSON. Verifică proxy-ul /api.');
  return response.json();
}

export async function download(kind, payload) {
  const response = await api(`/offers/export/${kind}`, payload, true);
  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  let filename = disposition.match(/filename="([^"]+)"/i)?.[1] || `oferta_${payload.offer_number}.${kind === 'saga' ? 'xml' : kind}`;
  if (encoded) { try { filename = decodeURIComponent(encoded); } catch { /* use fallback */ } }
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
