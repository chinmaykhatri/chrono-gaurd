import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE, api, asRecord, RecordData } from '../api/client';

export function useResource<T>(path: string | null, revision = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(Boolean(path));
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce(n => n + 1), []);
  useEffect(() => {
    if (!path) { setLoading(false); return; }
    const controller = new AbortController(); setLoading(true); setError('');
    api<T>(path, { signal: controller.signal }).then(setData).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to load records.'); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, revision, nonce]);
  return { data, error, loading, reload };
}
const eventNames = ['request.completed', 'decision.made', 'claims.extracted', 'verification.started', 'verification.finished', 'fact.updated', 'entry.status_changed', 'entry.evicted', 'regen.finished', 'budget.updated', 'budget.exhausted', 'clock.changed', 'eval.progress'];
export type LiveEvent = { id: string; type: string; ts?: string; payload: RecordData };
export function useEvents(enabled: boolean) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [state, setState] = useState('Connecting');
  const [revision, setRevision] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    if (!enabled) return;
    const stream = new EventSource(API_BASE + '/api/v1/events/stream', { withCredentials: true });
    stream.onopen = () => setState('Connected');
    stream.onerror = () => setState('Reconnecting');
    function receive(event: MessageEvent) {
      try {
        const parsed = asRecord(JSON.parse(event.data));
        const item = { id: event.lastEventId || crypto.randomUUID(), type: String(parsed.type ?? event.type), ts: typeof parsed.ts === 'string' ? parsed.ts : undefined, payload: asRecord(parsed.payload) };
        setEvents(previous => previous.some(x => x.id === item.id) ? previous : [item, ...previous].slice(0, 1000));
        if (!timer.current) timer.current = setTimeout(() => { setRevision(n => n + 1); timer.current = undefined; }, 500);
      } catch { setState('Invalid event received'); }
    }
    eventNames.forEach(name => stream.addEventListener(name, receive as EventListener));
    stream.onmessage = receive;
    return () => { stream.close(); clearTimeout(timer.current); timer.current = undefined; };
  }, [enabled]);
  return { events, state, revision };
}
