import { ReactNode, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  asRecord,
  asRows,
  display,
  downloadCsv,
  number,
  post,
  RecordData,
  safeSourceUrl,
  timestamp,
} from '../api/client';

/* ------------------------------------------------------------------
   Status language. One vocabulary for badges, charts and dots so a
   colour always means the same thing across the console.
   ------------------------------------------------------------------ */

export type Tone = 'good' | 'warn' | 'bad' | 'info' | 'neutral';

const TONE_VARS: Record<Tone, string> = {
  good: 'var(--color-success)',
  warn: 'oklch(78% 0.14 78)',
  bad: 'var(--color-error)',
  info: 'var(--color-accent-2)',
  neutral: 'var(--color-muted-2)',
};

const GOOD = ['fresh', 'serve', 'confirmed', 'complete', 'ready', 'hit', 'hit_direct', 'hit_semantic', 'present', 'configured', 'authenticated'];
const WARN = ['due', 'serve_swr', 'partial', 'pending', 'standard', 'queued', 'unconfigured', 'missing'];
const BAD = ['stale', 'evict_regen', 'evicted', 'contradicted', 'outdated', 'fail_closed', 'error', 'failed', 'strict'];
const INFO = ['passthrough', 'revalidate_blocking', 'evict_lazy', 'running', 'lenient'];

export function tone(value: unknown): Tone {
  const name = String(value ?? '').toLowerCase();
  if (GOOD.includes(name)) return 'good';
  if (WARN.includes(name)) return 'warn';
  if (BAD.includes(name)) return 'bad';
  if (INFO.includes(name)) return 'info';
  return 'neutral';
}

export function toneColor(value: unknown) {
  return TONE_VARS[tone(value)];
}

export function Badge({ value, dot = true }: { value: unknown; dot?: boolean }) {
  const name = display(value).replaceAll('_', ' ');
  return (
    <span className={`badge tone-${tone(value)}${dot ? '' : ' plain'}`}>
      {dot && <i aria-hidden="true" />}
      {name}
    </span>
  );
}

export function ClassChip({ value }: { value: unknown }) {
  if (!value) return null;
  return <span className="class-chip">{String(value).replaceAll('_', ' ')}</span>;
}

/* ------------------------------------------------------------------
   Page furniture
   ------------------------------------------------------------------ */

export function PageHead({
  title,
  kicker,
  description,
  children,
}: {
  title: string;
  kicker?: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        {kicker && <p className="kicker">{kicker}</p>}
        <h1>{title}</h1>
        {description && <p className="page-note">{description}</p>}
      </div>
      {children && <div className="toolbar">{children}</div>}
    </header>
  );
}

export function Section({
  title,
  note,
  action,
  children,
}: {
  title: string;
  note?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="section-head">
        <h2>{title}</h2>
        {note && <p>{note}</p>}
        {action && <div className="section-action">{action}</div>}
      </div>
      {children}
    </section>
  );
}

export function ErrorNotice({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div role="alert" className="notice error">
      <p>{message}</p>
      {retry && <button onClick={retry}>Try again</button>}
    </div>
  );
}

export function Empty({ title = 'No records yet', children }: { title?: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children || <p>Records appear here after the gateway processes requests.</p>}
    </div>
  );
}

export function Loading() {
  return (
    <div className="loading" role="status">
      Loading records…
      <div />
      <div />
      <div />
    </div>
  );
}

export function Json({ value, label = 'Raw record' }: { value: unknown; label?: string }) {
  return (
    <details className="raw">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function State({
  resource,
  children,
}: {
  resource: { loading: boolean; error: string; data: unknown; reload: () => void };
  children: ReactNode;
}) {
  if (resource.error) return <ErrorNotice message={resource.error} retry={resource.reload} />;
  if (resource.loading && !resource.data) return <Loading />;
  return <>{children}</>;
}

export function WindowFilter() {
  const [params, set] = useSearchParams();
  return (
    <label>
      Window
      <select
        value={params.get('window') ?? '24h'}
        onChange={(event) => {
          const next = new URLSearchParams(params);
          next.set('window', event.target.value);
          set(next);
        }}
      >
        <option value="1h">Last hour</option>
        <option value="24h">Last 24 hours</option>
        <option value="7d">Last 7 days</option>
      </select>
    </label>
  );
}

/* ------------------------------------------------------------------
   Measurements
   ------------------------------------------------------------------ */

export function Kpis({
  items,
}: {
  items: { label: string; value: ReactNode; context?: string; to?: string }[];
}) {
  return (
    <div className="kpis">
      {items.map((item) => {
        const body = (
          <>
            <span className="kpi-label">{item.label}</span>
            <strong className="kpi-value">{item.value}</strong>
            <span className="kpi-context">{item.context ?? ''}</span>
          </>
        );
        return item.to ? (
          <Link key={item.label} to={item.to} className="kpi">
            {body}
          </Link>
        ) : (
          <div key={item.label} className="kpi">
            {body}
          </div>
        );
      })}
    </div>
  );
}

export function MetricList({ values }: { values: RecordData }) {
  const entries = Object.entries(values).filter(([, value]) => value !== undefined && value !== null);
  if (!entries.length) return <p className="muted">No measurements recorded.</p>;
  return (
    <dl className="metric-list">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key.replaceAll('_', ' ')}</dt>
          <dd>{display(value).replaceAll('_', ' ')}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ----- stacked decision chart ------------------------------------- */

export function StackedBars({ series }: { series: unknown }) {
  const rows = asRows(series);
  const decisions = Array.from(
    new Set(rows.flatMap((row) => Object.keys(asRecord(row.decisions)))),
  ).sort();
  const max = Math.max(1, ...rows.map((row) => Number(row.total) || 0));
  if (!rows.length) {
    return (
      <div className="chart chart-empty">
        <svg viewBox="0 0 640 190" role="img" aria-label="No decisions recorded in this window">
          {[0, 1, 2, 3].map((line) => (
            <line key={line} x1="44" y1={24 + line * 42} x2="628" y2={24 + line * 42} className="chart-grid" />
          ))}
          <line x1="44" y1="150" x2="628" y2="150" className="chart-axis" />
          <text x="44" y="176">No decisions in this window</text>
        </svg>
      </div>
    );
  }
  const width = 640;
  const height = 190;
  const plotTop = 20;
  const plotBottom = 150;
  const slot = (width - 44) / rows.length;
  const barWidth = Math.max(3, Math.min(26, slot * 0.62));
  return (
    <div className="chart">
      <div className="legend">
        {decisions.map((decision) => (
          <span key={decision}>
            <i style={{ background: toneColor(decision) }} aria-hidden="true" />
            {decision.replaceAll('_', ' ')}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Decisions over time, stacked by decision">
        {[0, 0.25, 0.5, 0.75, 1].map((share) => (
          <g key={share}>
            <line x1="44" y1={plotBottom - share * (plotBottom - plotTop)} x2={width - 12} y2={plotBottom - share * (plotBottom - plotTop)} className="chart-grid" />
            <text x="0" y={plotBottom - share * (plotBottom - plotTop) + 3}>{Math.round(share * max)}</text>
          </g>
        ))}
        {rows.map((row, index) => {
          const counts = asRecord(row.decisions);
          let stacked = 0;
          const x = 44 + index * slot + (slot - barWidth) / 2;
          const total = Number(row.total) || 0;
          return (
            <g key={String(row.at ?? index)}>
              <title>{`${timestamp(String(row.at ?? ''))}: ${total} decisions`}</title>
              {decisions.map((decision) => {
                const value = Number(counts[decision]) || 0;
                if (!value) return null;
                const barHeight = (value / max) * (plotBottom - plotTop);
                const y = plotBottom - stacked - barHeight;
                stacked += barHeight;
                return <rect key={decision} x={x} y={y} width={barWidth} height={Math.max(1, barHeight)} fill={toneColor(decision)} />;
              })}
              {(index === 0 || index === rows.length - 1 || index === Math.floor(rows.length / 2)) && (
                <text x={x + barWidth / 2} y="172" textAnchor="middle">
                  {String(row.at ?? '').replace('T', ' ').slice(5)}
                </text>
              )}
            </g>
          );
        })}
        <line x1="44" y1={plotBottom} x2={width - 12} y2={plotBottom} className="chart-axis" />
      </svg>
    </div>
  );
}

export function Donut({ values, total }: { values: unknown; total?: number }) {
  const entries = Object.entries(asRecord(values)).filter(([, value]) => Number(value) > 0) as [string, number][];
  const sum = entries.reduce((carry, [, value]) => carry + value, 0);
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 160 160" className="donut" role="img" aria-label={`Entry health, ${sum} entries`}>
        <circle cx="80" cy="80" r={radius} className="donut-track" />
        {entries.map(([name, value]) => {
          const length = (value / sum) * circumference;
          const circle = (
            <circle
              key={name}
              cx="80"
              cy="80"
              r={radius}
              fill="none"
              stroke={toneColor(name)}
              strokeWidth="14"
              strokeDasharray={`${length} ${circumference - length}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 80 80)"
            />
          );
          offset += length;
          return circle;
        })}
        <text x="80" y="78" textAnchor="middle" className="donut-value">
          {total ?? sum}
        </text>
        <text x="80" y="96" textAnchor="middle" className="donut-label">
          entries
        </text>
      </svg>
      {entries.length ? (
        <ul className="donut-legend">
          {entries.map(([name, value]) => (
            <li key={name}>
              <i style={{ background: toneColor(name) }} aria-hidden="true" />
              <span>{name.replaceAll('_', ' ')}</span>
              <b>{value}</b>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">No cache entries yet. The first verified answer creates one.</p>
      )}
    </div>
  );
}

export function Bars({ values, label }: { values: unknown; label: string }) {
  const entries = Object.entries(asRecord(values)).filter(([, value]) => typeof value === 'number' && Number.isFinite(value)) as [string, number][];
  const max = Math.max(1, ...entries.map(([, value]) => Math.abs(value)));
  return (
    <div className="bars" aria-label={label}>
      {entries.length ? (
        entries.map(([key, value]) => (
          <div className="bar-row" key={key}>
            <span>{key.replaceAll('_', ' ')}</span>
            <span className="bar-track">
              <i style={{ width: `${(Math.abs(value) / max) * 100}%`, background: toneColor(key) }} />
            </span>
            <span className="measure">{value.toLocaleString()}</span>
          </div>
        ))
      ) : (
        <p className="muted small">No measurements available.</p>
      )}
    </div>
  );
}

export function Countdown({ at, clock }: { at: unknown; clock?: RecordData | null }) {
  if (typeof at !== 'string' || !Number.isFinite(Date.parse(at))) return <span className="muted">No expiry</span>;
  const frozen = clock?.mode === 'frozen' && typeof clock.frozen_at === 'string';
  const reference = frozen ? Date.parse(clock!.frozen_at as string) : Date.now() + Number(clock?.offset_seconds ?? 0) * 1000;
  const seconds = Math.round((Date.parse(at) - reference) / 1000);
  if (seconds <= 0) return <span className="countdown due">Due now</span>;
  const label = seconds < 3600 ? `${Math.ceil(seconds / 60)} min` : seconds < 172800 ? `${Math.ceil(seconds / 3600)} h` : `${Math.ceil(seconds / 86400)} d`;
  return (
    <span className={`countdown${seconds < 3600 ? ' soon' : ''}`} title={timestamp(at)}>
      {label} left
    </span>
  );
}

/* ------------------------------------------------------------------
   Tables
   ------------------------------------------------------------------ */

export type Column = {
  key: string;
  label: string;
  align?: 'right';
  render?: (row: RecordData) => ReactNode;
};

export function DataTable({
  rows,
  columns,
  name = 'records',
  actions,
  empty,
  expanded,
}: {
  rows: RecordData[];
  columns: Column[];
  name?: string;
  actions?: (row: RecordData) => ReactNode;
  empty?: ReactNode;
  expanded?: (row: RecordData) => ReactNode;
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const filtered = rows.filter((row) => JSON.stringify(row).toLowerCase().includes(query.toLowerCase()));
  return (
    <>
      <div className="table-tools">
        <label className="search">
          <span className="visually-hidden">Filter loaded rows</span>
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter rows" />
        </label>
        <button disabled={!filtered.length} onClick={() => downloadCsv(`${name}.csv`, filtered)}>
          Export CSV
        </button>
        <span className="muted small">
          {filtered.length} of {rows.length}
        </span>
      </div>
      {!filtered.length ? (
        empty ?? <Empty title={query ? 'No matching records' : 'No records yet'} />
      ) : (
        <div className="table-scroll" tabIndex={0} role="region" aria-label={`${name} table`}>
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key} scope="col" className={column.align === 'right' ? 'right' : undefined}>
                    {column.label}
                  </th>
                ))}
                {(actions || expanded) && <th scope="col" className="right">{actions ? 'Actions' : 'Trace'}</th>}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, index) => {
                const id = String(row.id ?? row.claim_id ?? row.fact_key ?? index);
                return (
                  <>
                    <tr key={id} className={open === id ? 'open' : undefined}>
                      {columns.map((column) => (
                        <td key={column.key} className={column.align === 'right' ? 'right num' : undefined}>
                          {column.render ? column.render(row) : display(row[column.key]).replaceAll('_', ' ')}
                        </td>
                      ))}
                      {(actions || expanded) && (
                        <td className="right nowrap">
                          {actions ? (
                            actions(row)
                          ) : (
                            <button className="linkish" aria-expanded={open === id} onClick={() => setOpen(open === id ? null : id)}>
                              {open === id ? 'Hide' : 'Inspect'}
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                    {expanded && open === id && (
                      <tr key={`${id}-detail`} className="detail-row">
                        <td colSpan={columns.length + 1}>{expanded(row)}</td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------
   Domain views
   ------------------------------------------------------------------ */

export function Evidence({ items }: { items: unknown }) {
  const rows = asRows(items);
  if (!rows.length) return <p className="muted small">No evidence recorded for this snapshot.</p>;
  return (
    <ol className="evidence-list">
      {rows.map((item, index) => {
        const url = safeSourceUrl(item.url);
        const label = item.label ?? item.verdict ?? 'candidate';
        return (
          <li key={String(item.id ?? index)}>
            <div className="split-line">
              <strong>
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
                    {display(item.title || item.domain || item.url)}
                  </a>
                ) : (
                  display(item.title ?? 'Source unavailable')
                )}
              </strong>
              <Badge value={label} />
            </div>
            <p>{display(item.snippet ?? item.summary ?? '')}</p>
            <div className="source-meta">
              <span>{display(item.domain ?? 'unknown domain')}</span>
              <span>Tier {display(item.tier ?? item.authority_tier)}</span>
              <span>{display(item.source ?? 'Tavily')}</span>
              <time>{item.published_at ? timestamp(item.published_at) : 'No publication date'}</time>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function Claims({ claims }: { claims: unknown }) {
  const rows = asRows(claims);
  return (
    <DataTable
      name="claims"
      rows={rows}
      empty={<Empty title="No claims extracted"><p>This answer had no eligible, externally checkable factual claims.</p></Empty>}
      columns={[
        {
          key: 'text',
          label: 'Claim',
          render: (claim) => (
            <Link to={`/claims/${encodeURIComponent(String(claim.claim_id ?? claim.id))}`} className="claim-link">
              {display(claim.text ?? claim.claim_text)}
            </Link>
          ),
        },
        { key: 'status', label: 'Status', render: (claim) => <Badge value={claim.status} /> },
        { key: 'freshness', label: 'Freshness', align: 'right' },
        { key: 'verdict', label: 'Verdict', render: (claim) => display(claim.verdict).replaceAll('_', ' ') },
        { key: 'next_check_at', label: 'Next check', render: (claim) => timestamp(claim.next_check_at) },
      ]}
    />
  );
}

export function Ticker({ events }: { events: { id: string; type: string; ts?: string; payload: RecordData }[] }) {
  if (!events.length) {
    return (
      <Empty title="Waiting for gateway activity">
        <p>
          Events stream from the verifier as requests complete, claims are checked and cache entries change state. Send a
          request through Bifrost to start the feed.
        </p>
      </Empty>
    );
  }
  return (
    <ul className="ticker">
      {events.slice(0, 20).map((event) => (
        <li key={event.id}>
          <time>{event.ts ? timestamp(event.ts) : '—'}</time>
          <span className="ticker-type">{event.type.replaceAll('.', ' ')}</span>
          <span className="ticker-detail">
            {String(event.payload.verdict ?? event.payload.decision ?? event.payload.cache_status ?? event.payload.status ?? '')}
            {event.payload.claim_count ? ` · ${event.payload.claim_count} claims` : ''}
            {event.payload.min_freshness !== undefined && event.payload.min_freshness !== null ? ` · freshness ${event.payload.min_freshness}` : ''}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------------
   Visual Lifecycle Inspector
   ------------------------------------------------------------------ */

export function LifecycleInspector({ data }: { data: RecordData }) {
  const req = asRecord(data);
  const cacheHit = ['hit', 'hit_direct', 'hit_semantic'].includes(String(req.cache_status));
  const claims = asRows(req.claims ?? asRecord(req.annotation).claims);
  const decision = String(req.decision ?? 'passthrough');

  const steps = [
    {
      num: 1,
      title: 'Request Ingestion',
      subtitle: `${display(req.model_id ?? req.model ?? 'Gateway')} · Policy: ${display(req.policy ?? 'standard')}`,
      status: 'good',
      badge: req.prompt_class ? <ClassChip value={req.prompt_class} /> : null,
      details: [
        { label: 'Request ID', value: display(req.id ?? req.request_id) },
        { label: 'Prompt', value: display(req.prompt_preview ?? req.prompt ?? '—') },
        { label: 'Time', value: timestamp(req.created_at) },
      ],
    },
    {
      num: 2,
      title: 'Bifrost Cache Interception',
      subtitle: cacheHit ? 'Cache entry matched in Bifrost' : 'Cache miss — routed to upstream provider',
      status: cacheHit ? 'good' : 'neutral',
      badge: <Badge value={req.cache_status ?? 'miss'} />,
      details: [
        { label: 'Cache Status', value: display(req.cache_status ?? 'miss') },
        { label: 'Cache ID', value: display(req.cache_id ?? req.bifrost_cache_id ?? 'None') },
      ],
    },
    {
      num: 3,
      title: 'Manifest & Reverse Index',
      subtitle: `${claims.length} atomic factual claim${claims.length === 1 ? '' : 's'} indexed in Redis`,
      status: claims.length > 0 ? 'good' : 'neutral',
      badge: <Badge value={claims.length > 0 ? `${claims.length} claims` : 'No claims'} />,
      details: [
        { label: 'Indexed Claims', value: String(claims.length) },
        { label: 'Redis Manifest', value: req.cache_id ? 'cg:manifest:' + String(display(req.cache_id)).slice(0, 10) + '…' : 'Ephemeral' },
      ],
    },
    {
      num: 4,
      title: 'Freshness Evaluation',
      subtitle: typeof req.min_freshness === 'number' ? `Minimum claim freshness score: ${req.min_freshness}%` : 'Claim freshness evaluated against policy thresholds',
      status: typeof req.min_freshness === 'number' && req.min_freshness >= 60 ? 'good' : 'warn',
      badge: typeof req.min_freshness === 'number' ? <Badge value={`${req.min_freshness}%`} /> : null,
      details: [
        { label: 'Min Freshness', value: typeof req.min_freshness === 'number' ? `${req.min_freshness}%` : '—' },
        { label: 'Best Before', value: req.best_before ? timestamp(req.best_before) : '—' },
      ],
    },
    {
      num: 5,
      title: 'Evidence Adjudication',
      subtitle: req.tavily_credits ? `Tavily Search: ${req.tavily_credits} credits used` : 'Fact ledger cache reused — 0 external Tavily queries',
      status: 'info',
      badge: <Badge value={req.tavily_credits ? 'Tavily verified' : 'Ledger hit'} />,
      details: [
        { label: 'Verification Latency', value: req.verification_latency_ms ? `${req.verification_latency_ms} ms` : '0 ms (cached)' },
        { label: 'Tavily Credits', value: String(req.tavily_credits ?? 0) },
      ],
    },
    {
      num: 6,
      title: 'Gateway Decision Stamped',
      subtitle: `Enforced by Bifrost plugin pair: ${decision.replaceAll('_', ' ')}`,
      status: tone(decision),
      badge: <Badge value={decision} />,
      details: [
        { label: 'Final Action', value: decision },
        { label: 'Cost', value: req.cost_usd ? `$${number(req.cost_usd, 4)}` : '$0.0000' },
        ...(req.guard_tripped ? [{ label: 'Semantic Hit Guard', value: `Tripped: ${display(req.guard_reason)} (bypassed cache)` }] : []),
      ],
    },
  ];

  return (
    <div className="lifecycle-inspector">
      <div className="lifecycle-track">
        {steps.map((s, idx) => (
          <div key={s.num} className={`lifecycle-stage stage-${s.status}`}>
            <div className="stage-marker">
              <span className="stage-num">{s.num}</span>
              {idx < steps.length - 1 && <span className="stage-connector" />}
            </div>
            <div className="stage-body">
              <div className="split-line">
                <div>
                  <h4 className="stage-title">{s.title}</h4>
                  <p className="stage-subtitle">{s.subtitle}</p>
                </div>
                {s.badge}
              </div>
              <div className="stage-grid">
                {s.details.map((d, i) => (
                  <div key={i} className="stage-field">
                    <span className="field-label">{d.label}</span>
                    <strong className="field-value">{d.value}</strong>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------
   Before vs After Comparison Card
   ------------------------------------------------------------------ */

export function DiffCard({
  originalText,
  correctedText,
  staleClaims,
  freshClaims,
  originalDate,
  correctedDate,
}: {
  originalText?: string;
  correctedText?: string;
  staleClaims?: unknown;
  freshClaims?: unknown;
  originalDate?: string;
  correctedDate?: string;
}) {
  const stale = asRows(staleClaims);
  const fresh = asRows(freshClaims);

  return (
    <div className="diff-card">
      <div className="diff-header">
        <div>
          <h3>Answer Evolution & Grounded Correction</h3>
          <p className="page-note">Side-by-side comparison showing outdated claims superseded by verified facts.</p>
        </div>
        <Badge value="corrected" />
      </div>
      <div className="diff-grid">
        <div className="diff-pane stale-pane">
          <div className="diff-pane-head">
            <span className="pane-tag tag-stale">Original Answer (Outdated)</span>
            {originalDate && <time>{timestamp(originalDate)}</time>}
          </div>
          <div className="pane-content">
            <p className="answer-text stale-text">{originalText || 'Previous answer contained outdated factual assertions.'}</p>
            {stale.length > 0 && (
              <div className="diff-claims-box">
                <span className="diff-box-label">Outdated Stated Claims</span>
                <ul className="diff-claims-list">
                  {stale.map((c, i) => (
                    <li key={i} className="stale-claim-item">
                      <span className="strikethrough">{display(c.text ?? c.stated_value)}</span>
                      <Badge value="outdated" />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>

        <div className="diff-pane fresh-pane">
          <div className="diff-pane-head">
            <span className="pane-tag tag-fresh">Grounded Answer (Current)</span>
            {correctedDate && <time>{timestamp(correctedDate)}</time>}
          </div>
          <div className="pane-content">
            <p className="answer-text fresh-text">{correctedText || 'Regenerated with verified Tavily evidence sources.'}</p>
            {fresh.length > 0 && (
              <div className="diff-claims-box">
                <span className="diff-box-label">Verified Corrected Values</span>
                <ul className="diff-claims-list">
                  {fresh.map((c, i) => (
                    <li key={i} className="fresh-claim-item">
                      <strong className="fresh-highlight">{display(c.corrected_value ?? c.stated_value ?? c.text)}</strong>
                      <Badge value="confirmed" />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------
   System Health & Invalidation Probe Widget
   ------------------------------------------------------------------ */

export function ProbeWidget() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RecordData | null>(null);
  const [error, setError] = useState('');

  async function runProbe() {
    setRunning(true);
    setError('');
    try {
      const res = await post('/system/probe');
      setResult(asRecord(res));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  const steps = asRows(result?.steps);

  return (
    <div className="probe-widget">
      <div className="split-line">
        <div>
          <h3>System Invalidation Probe</h3>
          <p className="page-note">
            Automated hardware test verifying Redis reverse indexing (<code>SADD</code>) and sub-20ms cascade invalidation without mocking.
          </p>
        </div>
        <div className="probe-actions">
          {result && (
            <span className={`probe-status-tag status-${result.status === 'verified' ? 'good' : 'bad'}`}>
              {result.status === 'verified' ? '✓ VERIFIED HEALTHY' : '✕ PROBE FAILED'} ({String(result.probe_latency_ms)} ms)
            </span>
          )}
          <button className="button primary" disabled={running} onClick={runProbe}>
            {running ? 'Running Probe…' : '⚡ Run Invalidation Probe'}
          </button>
        </div>
      </div>

      {error && <ErrorNotice message={error} />}

      {steps.length > 0 && (
        <div className="probe-steps-container">
          <ol className="probe-steps-list">
            {steps.map((s, idx) => (
              <li key={idx} className={`probe-step-item ${s.ok ? 'step-ok' : 'step-err'}`}>
                <div className="step-icon">{s.ok ? '✓' : '✕'}</div>
                <div className="step-content">
                  <div className="split-line">
                    <strong className="step-name">{display(s.step).replaceAll('_', ' ')}</strong>
                    <span className="step-latency">{String(s.latency_ms)} ms</span>
                  </div>
                  <p className="step-detail">{display(s.detail)}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
