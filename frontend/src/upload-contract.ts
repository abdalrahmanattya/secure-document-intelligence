export type UploadDescriptor = {
  method: 'PUT' | 'POST';
  url: string;
  headers?: Record<string, string>;
  fields?: Record<string, string>;
  size: number;
  sha256: string;
};

export async function sha256Hex(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()));
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

export async function uploadWithDescriptor(
  descriptor: UploadDescriptor,
  file: Blob,
  apiBase: string,
  token = '',
  request: typeof fetch = fetch,
): Promise<Response> {
  if (file.size !== descriptor.size) throw new Error('upload size does not match descriptor');
  const actual = await sha256Hex(file);
  if (actual !== descriptor.sha256) throw new Error('upload digest does not match descriptor');
  const target = new URL(descriptor.url, apiBase).toString();
  if (descriptor.method === 'POST' && descriptor.fields) {
    const form = new FormData();
    Object.entries(descriptor.fields).forEach(([key, value]) => form.append(key, value));
    form.append('file', file, 'document');
    return request(target, {method: 'POST', body: form});
  }
  return request(target, {method: 'PUT', headers: {...(token ? {Authorization: `Bearer ${token}`} : {}), ...(descriptor.headers ?? {})}, body: file});
}
