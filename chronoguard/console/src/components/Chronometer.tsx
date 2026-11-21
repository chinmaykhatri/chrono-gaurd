import { useEffect, useRef, useState } from 'react';
import { Clock3, MoveHorizontal, Pause, Play, RotateCcw } from 'lucide-react';
import type { RecordData } from '../api/client';
import type { ClockPose, mountClock } from './clockScene';

const utc = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', hour12: false });

export function Chronometer({ compact = false, clock }: { compact?: boolean; clock?: RecordData | null }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  const controller = useRef<ReturnType<typeof mountClock> | null>(null);
  const offset = typeof clock?.offset_seconds === 'number' ? clock.offset_seconds * 1000 : 0;
  const timestamp = clock?.mode === 'frozen' && typeof clock.frozen_at === 'string' ? Date.parse(clock.frozen_at) : NaN;
  const frozen = Number.isFinite(timestamp) ? timestamp : null;
  const reference = useRef({ offset, frozen });
  const pose = useRef<ClockPose>({ yaw: 0, pitch: 0, scroll: 0, moving: true,
    now: () => reference.current.frozen ?? Date.now() + reference.current.offset });
  const drag = useRef<{ x: number; y: number; id: number } | null>(null);
  const [engine, setEngine] = useState('dial');
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [paused, setPaused] = useState(false);
  const [wallTime, setWallTime] = useState(Date.now);
  const time = new Date(frozen ?? wallTime + offset);
  const moving = !reduced && !paused;

  function updatePose() {
    const p = pose.current;
    surface.current?.style.setProperty('--dial-yaw', (p.yaw + p.scroll * 0.78) + 'rad');
    surface.current?.style.setProperty('--dial-pitch', p.pitch + 'rad');
    controller.current?.wake();
  }
  function reset() { pose.current.yaw = 0; pose.current.pitch = 0; updatePose(); }
  useEffect(() => { reference.current = { offset, frozen }; controller.current?.wake(); }, [offset, frozen]);
  useEffect(() => {
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setReduced(motion.matches);
    motion.addEventListener('change', change);
    const tick = window.setInterval(() => setWallTime(Date.now()), 1000);
    return () => { motion.removeEventListener('change', change); clearInterval(tick); };
  }, []);
  useEffect(() => {
    pose.current.moving = moving;
    function scroll() {
      pose.current.scroll = moving ? Math.min(1.2, Math.max(0, window.scrollY / window.innerHeight)) : 0;
      updatePose();
    }
    scroll(); window.addEventListener('scroll', scroll, { passive: true });
    return () => window.removeEventListener('scroll', scroll);
  }, [moving]);
  useEffect(() => {
    let cancelled = false;
    const element = canvas.current;
    if (!element) return;
    import('./clockScene').then(({ mountClock }) => {
      if (cancelled || !element.getContext('webgl2', { alpha: true, antialias: true, powerPreference: 'low-power' })) return;
      controller.current = mountClock(element, pose.current);
      setEngine('webgl');
    }).catch(() => { if (!cancelled) setEngine('dial'); });
    const lost = (event: Event) => { event.preventDefault(); setEngine('dial'); controller.current?.dispose(); controller.current = null; };
    element.addEventListener('webglcontextlost', lost);
    return () => { cancelled = true; element.removeEventListener('webglcontextlost', lost); controller.current?.dispose(); controller.current = null; };
  }, []);
  return <figure className={'chronometer' + (compact ? ' compact' : '')} data-engine={engine} data-motion={moving ? 'rolling' : 'still'}>
    <div className="instrument-field" ref={surface} tabIndex={0} role="group"
      aria-label="3-D verification clock. Drag to rotate, or use the left and right arrow keys. Home resets the view."
      onPointerDown={e => { if (e.button !== 0) return; drag.current = { x: e.clientX, y: e.clientY, id: e.pointerId }; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={e => {
        const old = drag.current;
        if (!old || old.id !== e.pointerId) return;
        pose.current.yaw += (e.clientX - old.x) * 0.012;
        pose.current.pitch = Math.max(-0.95, Math.min(0.95, pose.current.pitch + (e.clientY - old.y) * 0.006));
        drag.current = { x: e.clientX, y: e.clientY, id: e.pointerId }; updatePose();
      }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
      onLostPointerCapture={() => { drag.current = null; }}
      onKeyDown={e => {
        if (e.key === 'Home') { e.preventDefault(); reset(); }
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
          e.preventDefault(); pose.current.yaw += e.key === 'ArrowRight' ? 0.33 : -0.33; updatePose();
        }
      }}>
      <div className="dial-shadow" aria-hidden="true" />
      <div className="fallback-dial" aria-hidden="true"><div className="fallback-face">
        <span>12</span><span>3</span><span>6</span><span>9</span><b>ChronoGuard</b>
        <i style={{ transform: 'rotate(' + (time.getUTCHours() * 30 + time.getUTCMinutes() / 2) + 'deg)' }}/>
        <i style={{ transform: 'rotate(' + time.getUTCMinutes() * 6 + 'deg)' }}/>
      </div></div>
      <canvas ref={canvas} aria-hidden="true" />
    </div>
    <figcaption>
      <span className="instrument-time"><Clock3 aria-hidden="true" size={15}/><time dateTime={time.toISOString()}>{utc.format(time)} UTC</time></span>
      <span className="rotate-hint"><MoveHorizontal aria-hidden="true" size={15}/>Drag to rotate</span>
      <div className="instrument-actions">
        <button type="button" className="icon-button" onClick={reset} aria-label="Reset clock view" title="Reset clock view"><RotateCcw size={15}/></button>
        {!reduced && <button type="button" className="icon-button" onClick={() => setPaused(value => !value)}
          aria-label={paused ? 'Resume rotation' : 'Pause rotation'} title={paused ? 'Resume rotation' : 'Pause rotation'}>
          {paused ? <Play size={14}/> : <Pause size={14}/>}
        </button>}
      </div>
    </figcaption>
  </figure>;
}
