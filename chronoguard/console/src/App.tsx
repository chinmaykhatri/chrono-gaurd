import { FormEvent, ReactNode, Component, useEffect, useState } from 'react';
import { Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import { api, post, Session, setCsrfToken, display, RecordData } from './api/client';
import { useEvents, useResource } from './hooks/data';
import { ErrorNotice, Loading } from './components/ui';
import { Overview, Feed, Cache, CacheDetail, ClaimDetail, Facts, FactDetail, Costs } from './pages/records';
import { Playground } from './pages/Playground';
import { Policies, Settings, Evaluation, EvaluationReport } from './pages/management';
import { RoiReport } from './pages/ROI';

class Boundary extends Component<{children: ReactNode}, {error: boolean}> {
  state = {error: false};
  static getDerivedStateFromError() { return {error: true}; }
  render() { return this.state.error ? <main><ErrorNotice message="This view could not be displayed. Reload to reconnect to the console." retry={() => location.reload()}/></main> : this.props.children; }
}
export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [sessionError, setSessionError] = useState('');
  const navigate = useNavigate();
  const events = useEvents(Boolean(session?.authenticated));
  const clock = useResource<RecordData>(session ? '/clock' : null, events.revision);
  useEffect(() => {
    const controller = new AbortController();
    api<Session>('/auth/session', {signal: controller.signal}).then(s => { setCsrfToken(s.csrf_token); setSession(s.authenticated ? s : null); }).catch(e => { if (!controller.signal.aborted && e.status !== 401) setSessionError(e.message); }).finally(() => { if (!controller.signal.aborted) setChecking(false); });
    const expired = () => { setSession(null); setCsrfToken(''); setSessionError('Your session expired. Sign in again.'); };
    window.addEventListener('cg:unauthorized', expired);
    return () => { controller.abort(); window.removeEventListener('cg:unauthorized', expired); };
  }, []);
  async function logout() { try { await post('/auth/logout'); setSession(null); setCsrfToken(''); navigate('/login'); } catch (e) { setSessionError((e as Error).message); } }
  if (checking) return <div className="login"><Loading/></div>;
  if (!session) return <Login error={sessionError} onLogin={s => { setCsrfToken(s.csrf_token); setSession(s); setSessionError(''); navigate('/'); }}/>;
  const links = [['/', 'Overview'], ['/playground', 'Playground'], ['/feed', 'Live feed'], ['/cache', 'Cache explorer'], ['/facts', 'Fact ledger'], ['/policies', 'Policies'], ['/costs', 'Costs & latency'], ['/roi', 'ROI report'], ['/eval', 'Evaluation lab'], ['/settings', 'Settings']];
  return <Boundary><a href="#content" className="skip-link">Skip to content</a><div className="app-shell"><aside className="sidebar"><Link className="wordmark" to="/">ChronoGuard<span>Freshness console</span></Link><nav aria-label="Main navigation">{links.map(([path, label]) => <NavLink key={path} to={path} end={path === '/'}>{label}</NavLink>)}</nav><p className="sidebar-note">Evidence behind every decision.</p></aside><div className="workspace"><header className="topbar"><span>Bifrost gateway</span><div className="toolbar"><Link to="/settings" className="clock-chip">{clock.data?.mode && clock.data.mode !== 'real' ? `Simulated clock (${display(clock.data.offset_seconds)}s)` : clock.error ? 'Clock unavailable' : 'Real time'}</Link><span role="status" className="connection">Events: {events.state}</span><button onClick={logout}>Sign out</button></div></header>{clock.data?.mode && clock.data.mode !== 'real' ? <div className="notice warning">Simulated time is active. Evidence retrieval still uses real-world sources.</div> : null}{sessionError && <ErrorNotice message={sessionError}/>}<main id="content" tabIndex={-1}><Routes><Route path="/" element={<Overview live={events}/>}/><Route path="/playground" element={<Playground live={events}/>}/><Route path="/feed" element={<Feed live={events}/>}/><Route path="/cache" element={<Cache revision={events.revision} clock={clock.data}/>}/><Route path="/cache/:id" element={<CacheDetail revision={events.revision}/>}/><Route path="/claims/:id" element={<ClaimDetail revision={events.revision}/>}/><Route path="/facts" element={<Facts revision={events.revision}/>}/><Route path="/facts/:id" element={<FactDetail revision={events.revision}/>}/><Route path="/policies" element={<Policies/>}/><Route path="/costs" element={<Costs revision={events.revision}/>}/><Route path="/roi" element={<RoiReport revision={events.revision}/>}/><Route path="/eval" element={<Evaluation revision={events.revision}/>}/><Route path="/eval/runs/:id" element={<EvaluationReport revision={events.revision}/>}/><Route path="/settings" element={<Settings revision={events.revision}/>}/><Route path="/login" element={<Overview live={events}/>}/><Route path="*" element={<><h1>Page not found</h1><Link to="/">Return to overview</Link></>}/></Routes></main><footer>ChronoGuard uses Bifrost by Maxim AI and Tavily for evidence retrieval.</footer></div></div></Boundary>;
}
function Login({ onLogin, error: initialError }: { onLogin: (session: Session) => void; error: string }) {
  const [password, setPassword] = useState(''); const [pending, setPending] = useState(false); const [error, setError] = useState('');
  async function submit(event: FormEvent) { event.preventDefault(); setPending(true); setError(''); try { const session = await post<Session>('/auth/login', {password}); if (!session.authenticated) throw new Error('Sign-in was not accepted.'); setPassword(''); onLogin(session); } catch (e) { setError((e as Error).message); } finally { setPending(false); } }
  return <main className="login"><div className="login-panel"><Link to="/" className="wordmark">ChronoGuard</Link><h1>Inspect the evidence.</h1><p>Sign in to monitor answer freshness and manage cache verification.</p><form onSubmit={submit}><label htmlFor="password">Admin password</label><input id="password" type="password" required autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)}/>{(error || initialError) && <ErrorNotice message={error || initialError}/>}<button className="primary" disabled={pending || !password} aria-busy={pending}>{pending ? 'Signing in…' : 'Sign in'}</button></form><small>Credentials stay on this connection. Use HTTPS for remote access.</small></div></main>;
}
