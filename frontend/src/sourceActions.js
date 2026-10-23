import { errorText } from './api';

export async function sourceMutation(path, body, binary = false, method = 'POST') {
  const response = await fetch('/api/sources' + path, {
    method,
    headers: { 'X-Source-Action': '1', 'Content-Type': binary ? 'application/octet-stream' : 'application/json' },
    ...(body === undefined ? {} : { body: binary ? body : JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(errorText(data?.detail) || 'Operația a eșuat.');
  return data;
}
