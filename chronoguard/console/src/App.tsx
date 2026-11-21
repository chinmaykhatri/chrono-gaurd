import { Component, FormEvent, ReactNode, useEffect, useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity, ArrowRight, BookOpen, Boxes, ChartColumn, ChevronRight, Clock3, Eye, EyeOff,
  FlaskConical, Gauge, LayoutDashboard, LogOut, Menu, MessagesSquare, Radio, Settings2, SlidersHorizontal, X,
} from 'lucide-react';
import { api, display, post, RecordData, Session, setCsrfToken } from './api/client';
import { useEvents, useResource } from './hooks/data';
import { ErrorNotice, Loading } from './components/ui';
import { Chronometer } from './components/Chronometer';
import { Overview, Feed, Cache, CacheDetail, ClaimDetail, Facts, FactDetail, Costs } from './pages/records';
import { Playground } from './pages/Playground';
import { Policies, Settings, Evaluation, EvaluationReport } from './pages/management';
import { RoiReport } from './pages/ROI';

const navigation = [
  { label: 'Overview', path: '/', icon: LayoutDashboard },
  { label: 'Playground', path: '/playground', icon: MessagesSquare },
  { label: 'Live feed', path: '/feed', icon: Radio },
  { label: 'Cache explorer', path: '/cache', icon: Boxes },
  { label: 'Fact ledger', path: '/facts', icon: BookOpen },
  { label: 'Policies', path: '/policies', icon: SlidersHorizontal },
  { label: 'Costs & latency', path: '/costs', icon: Activity },
  { label: 'ROI report', path: '/roi', icon: ChartColumn },
  { label: 'Evaluation lab', path: '/eval', icon: FlaskConical },
  { label: 'Settings', path: '/settings', icon: Settings2 },
];

function Wordmark() {
  return <Link to="/" className="wordmark" aria-label="ChronoGuard home">
    <span className="brand-mark" aria-hidden="true"><i/><i/></span>ChronoGuard
  </Link>;
}

class Boundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() { return { error: true }; }
  render() {
    return this.state.error
      ? <main><ErrorNotice message="This view could not be displayed. Reload to reconnect to the console." retry={() => location.reload()}/></main>
      : this.props.children;
  }
}

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [sessionError, setSessionError] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const events = useEvents(Boolean(session?.authenticated));
  const clock = useResource<RecordData>(session ? '/clock' : null, events.revision);
  useEffect(() => {
    const controller = new AbortController();
    api<Session>('/auth/session', {signal: controller.signal}).then(s => {
      setCsrfToken(s.csrf_token); setSession(s.authenticated ? s : null);
    }).catch(e => { if (!controller.signal.aborted && e.status !== 401) setSessionError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setChecking(false); });
    const expired = () => { setSession(null); setCsrfToken(''); setSessionError('Your session expired. Sign in again.'); };
    window.addEventListener('cg:unauthorized', expired);
    return () => { controller.abort(); window.removeEventListener('cg:unauthorized', expired); };
  }, []);
  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [pathname]);
  async function logout() {
    try { await post('/auth/logout'); setSession(null); setCsrfToken(''); navigate('/login'); }
    catch (e) { setSessionError((e as Error).message); }
  }
  if (checking) return <main className="boot"><Loading/></main>;
  if (!session) return <Login error={sessionError} onLogin={s => {
    setCsrfToken(s.csrf_token); setSession(s); setSessionError(''); navigate('/');
  }}/>;
  const current = navigation.find(link => link.path === '/' ? pathname === '/' : pathname.startsWith(link.path));
  const simulated = Boolean(clock.data?.mode && clock.data.mode !== 'real');
  return <Boundary>
    <a href="#content" className="skip-link">Skip to content</a>
    <div className="app-shell">
      <aside className={'sidebar' + (menuOpen ? ' menu-open' : '')}>
        <div className="brand-row"><Wordmark/>
          <button className="menu-toggle icon-button" aria-label={menuOpen ? 'Close navigation' : 'Open navigation'}
            aria-controls="main-navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X/> : <Menu/>}</button>
        </div>
        <nav id="main-navigation" aria-label="Main navigation" onKeyDown={event => {
          if (event.key === 'Escape') { setMenuOpen(false); document.querySelector<HTMLButtonElement>('.menu-toggle')?.focus(); }
        }}>
          {[{group: 'Workspace', links: navigation.slice(0, 5)}, {group: 'Operations', links: navigation.slice(5)}].map(({group, links}) => (
            <div className="nav-group" key={group}>
              <p>{group}</p>
              {links.map(({path, label, icon: Icon}) =>
                <NavLink key={path} end={path === '/'} to={path} onClick={() => setMenuOpen(false)}>
                  <Icon size={17} strokeWidth={1.65} aria-hidden="true"/><span>{label}</span>
                </NavLink>)}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot"><Gauge size={16} aria-hidden="true"/>Bifrost gateway</div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="crumb"><span>Workspace</span><ChevronRight size={14}/><strong>{current?.label ?? 'Record detail'}</strong></div>
          <div className="toolbar">
            <Link to="/settings" className="clock-chip"><Clock3 size={15}/>
              {simulated ? 'Simulated time' : clock.error ? 'Clock unavailable' : 'Real time'}
            </Link>
            <span role="status" className="connection"><Radio size={15}/>Events: {events.state}</span>
            <button className="session-control" onClick={logout}><LogOut size={15}/>Sign out</button>
          </div>
        </header>
        {simulated && <div className="notice warning">The evaluation clock is active. Offset {display(clock.data?.offset_seconds)} seconds.</div>}
        {sessionError && <ErrorNotice message={sessionError}/>}
        <main id="content" tabIndex={-1} key={pathname}><Routes>
          <Route path="/" element={<Overview live={events} clock={clock.data}/>}/>
          <Route path="/playground" element={<Playground live={events}/>}/>
          <Route path="/feed" element={<Feed live={events}/>}/>
          <Route path="/cache" element={<Cache revision={events.revision} clock={clock.data}/>}/>
          <Route path="/cache/:id" element={<CacheDetail revision={events.revision}/>}/>
          <Route path="/claims/:id" element={<ClaimDetail revision={events.revision}/>}/>
          <Route path="/facts" element={<Facts revision={events.revision}/>}/>
          <Route path="/facts/:id" element={<FactDetail revision={events.revision}/>}/>
          <Route path="/policies" element={<Policies/>}/>
          <Route path="/costs" element={<Costs revision={events.revision}/>}/>
          <Route path="/roi" element={<RoiReport revision={events.revision}/>}/>
          <Route path="/eval" element={<Evaluation revision={events.revision}/>}/>
          <Route path="/eval/runs/:id" element={<EvaluationReport revision={events.revision}/>}/>
          <Route path="/settings" element={<Settings revision={events.revision}/>}/>
          <Route path="/login" element={<Overview live={events} clock={clock.data}/>}/>
          <Route path="*" element={<><h1>Page not found</h1><Link to="/">Return to overview</Link></>}/>
        </Routes></main>
        <footer className="app-footer">ChronoGuard <span>Bifrost gateway / Tavily evidence</span></footer>
      </div>
    </div>
  </Boundary>;
}

function Login({ onLogin, error: initialError }: { onLogin: (session: Session) => void; error: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); setPending(true); setError('');
    try {
      const session = await post<Session>('/auth/login', {password: ''});
      if (!session.authenticated) throw new Error('Sign-in was not accepted.');
      onLogin(session);
    } catch (e) { setError((e as Error).message); } finally { setPending(false); }
  }
  return <div className="login-shell">
    <header className="login-header"><Wordmark/><span><Gauge size={16}/>Operator console</span></header>
    <main className="login-layout">
      <div className="login-copy">
        <h1>Inspect the<br/> evidence.</h1>
        <p>Open access enabled. Enter freely to trace cached answers back to their sources and monitor answer freshness.</p>
        <form onSubmit={submit}>
          {(error || initialError) && <ErrorNotice message={error || initialError}/>}
          <button className="primary login-submit" disabled={pending} aria-busy={pending} style={{width: '100%', justifyContent: 'center', marginTop: '1rem'}}>
            {pending ? 'Opening console…' : 'Enter ChronoGuard Console'}<ArrowRight size={17}/>
          </button>
        </form>
      </div>
      <div className="login-instrument">
        <div className="instrument-heading"><span className="instrument-rule"/>Verification clock</div>
        <Chronometer/>
      </div>
    </main>
    <footer className="login-footer">ChronoGuard <span>Bifrost gateway / Tavily evidence</span></footer>
  </div>;
}
