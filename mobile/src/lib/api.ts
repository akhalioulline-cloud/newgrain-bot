import * as SecureStore from 'expo-secure-store';

// The native app talks to the same backend as the web app. No API changes needed;
// auth is the same `x-session` header, the token kept in the device keychain (SecureStore).
export const BASE = 'https://ai.flagleaf.ru';
const TOKEN_KEY = 'flagleaf_session';

export async function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(TOKEN_KEY);
}
export async function setToken(t: string | null): Promise<void> {
  if (t) await SecureStore.setItemAsync(TOKEN_KEY, t);
  else await SecureStore.deleteItemAsync(TOKEN_KEY);
}

async function req(path: string, opts: any = {}): Promise<any> {
  const token = await getToken();
  const headers = { ...(opts.headers || {}), ...(token ? { 'x-session': token } : {}) };
  const r = await fetch(BASE + path, { ...opts, headers });
  let body: any = null;
  try { body = await r.json(); } catch {}
  if (!r.ok) {
    const e: any = new Error((body && body.detail) || `Ошибка ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return body;
}

export const api = {
  get: (p: string) => req(p),
  postJson: (p: string, data: any) =>
    req(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  postForm: (p: string, form: FormData) => req(p, { method: 'POST', body: form }),
};
