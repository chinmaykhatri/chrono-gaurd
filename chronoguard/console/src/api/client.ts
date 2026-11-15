export type RecordData = Record<string, unknown>;
export type Page<T = RecordData> = { items: T[]; next_cursor: string | null };
export type Session = { authenticated: boolean; csrf_token: string };
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) { super(message); }
}
let csrfToken = '';
export function setCsrfToken(token: string) { csrfToken = token; }
export async function api<T = RecordData>(path: string, options: RequestInit = {}): Promise<T> {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) throw new Error('API path must be relative.');
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body) headers.set('Content-Type', 'application/json');
  if (options.method && !['GET', 'HEAD'].includes(options.method.toUpperCase())) headers.set('X-CSRF-Token', csrfToken);
  const response = await fetch(`/api/v1${path}`, { ...options, credentials: 'same-origin', cache: 'no-store', headers });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('cg:unauthorized'));
    throw new ApiError(response.status, body?.error?.code ?? 'request_failed', body?.error?.message ?? `Request failed (${response.status}).`, body?.error?.details);
  }
  return body as T;
}
export const post = <T = RecordData>(path: string, data?: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(data ?? {}) });
export const put = <T = RecordData>(path: string, data: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(data) });
export const idPath = (id: unknown) => encodeURIComponent(String(id));
export function safeSourceUrl(value: unknown): string | undefined {
  try { const url = new URL(String(value)); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; } catch { return undefined; }
}
export function csvCell(value: unknown): string {
  const text = typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '');
  const safe = /^[\s]*[=+@\-\t\r]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}
export function downloadCsv(name: string, rows: RecordData[]) {
  const keys = Array.from(new Set(rows.flatMap(Object.keys)));
  const csv = [keys.map(csvCell).join(','), ...rows.map(row => keys.map(key => csvCell(row[key])).join(','))].join('\r\n');
  download(name, csv, 'text/csv;charset=utf-8');
}
export function download(name: string, content: string, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const asRecord = (value: unknown): RecordData => typeof value === 'object' && value !== null && !Array.isArray(value) ? value as RecordData : {};
export const asRows = (value: unknown): RecordData[] => Array.isArray(value) ? value.map(asRecord) : [];
export const display = (value: unknown) => value == null ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value) : String(value);
export const number = (value: unknown, digits = 0) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : 'Unavailable';
export const timestamp = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString(undefined, { timeZoneName: 'short' }) : 'Not recorded';
