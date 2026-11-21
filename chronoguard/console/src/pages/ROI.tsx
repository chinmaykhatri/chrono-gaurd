import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useResource } from '../hooks/data';
import { Badge, ErrorNotice, Kpis, Loading, PageHead, Section, WindowFilter } from '../components/ui';
import { display, number, RecordData } from '../api/client';

export function RoiReport({ revision }: { revision: number }) {
  const [params] = useSearchParams();
  const window = params.get('window') || '24h';
  const roi = useResource<RecordData>(`/roi?window=${window}`, revision);
  const [copied, setCopied] = useState(false);

  if (roi.loading && !roi.data) return <Loading />;
  if (roi.error) return <ErrorNotice message={roi.error} retry={roi.reload} />;

  const data = roi.data || {};
  const costs = (data.costs as RecordData) || {};
  const staleFacts = (Array.isArray(data.top_stale_facts) ? data.top_stale_facts : []) as RecordData[];

  const observed = Number(data.requests_observed || 0);
  const hitRate = Number(data.hit_rate || 0);
  const staleServed = Number(data.stale_would_have_served || 0);
  const atRisk = Number(data.entries_at_risk || 0);
  const verificationCost = typeof costs.verification_cost_usd === 'number' ? `$${costs.verification_cost_usd.toFixed(4)} USD` : 'Unpriced';

  function exportJson() {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chronoguard-roi-report-${window}-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function copyMarkdown() {
    const md = [
      `# ChronoGuard ROI & Freshness Report (${window})`,
      `Generated at: ${new Date().toISOString()}`,
      '',
      '## Executive Summary',
      String(data.recommendation || 'No recommendation available.'),
      '',
      '## Key Metrics',
      `| Metric | Value | Provenance |`,
      `|---|---|---|`,
      `| Requests Observed | ${observed} | LIVE |`,
      `| Cache Hit Rate | ${(hitRate * 100).toFixed(1)}% | LIVE |`,
      `| Known-stale hits in shadow mode | ${staleServed} | LIVE |`,
      `| Cache Entries at Risk | ${atRisk} | LIVE |`,
      `| Verification Cost | ${verificationCost} | ${costs.verification_cost_label || 'unpriced'} |`,
      `| Tavily Credits | ${number(costs.tavily_credits)} | recorded |`,
      `| Verified repairs | ${number(data.repaired_hits)} | recorded |`,
      `| Verification blocks | ${number(data.blocked_hits)} | recorded |`,
      '',
      '## Top Stale Facts Detected',
      `| Fact Key | Cached Value | Current Value | Verdict | Entries Affected | Hits |`,
      `|---|---|---|---|---|---|`,
      ...staleFacts.map(f =>
        `| \`${f.fact_key}\` | ${f.cached_value} | ${f.current_value} | ${f.last_verdict} | ${f.entries_affected} | ${f.hits} |`
      ),
      '',
      '---',
    ].join('\n');

    navigator.clipboard.writeText(md).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  }

  return (
    <div className="page roi-page">
      <PageHead
        title="Return on Investment"
        description="Inspect cached answer risk, verified repairs, and recorded verification spend."
      >
        <div className="head-actions" style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <WindowFilter />
          <button type="button" className="secondary" onClick={exportJson}>
            Export JSON
          </button>
          <button type="button" className="primary" onClick={copyMarkdown}>
            {copied ? '✓ Markdown Copied' : 'Copy Markdown Report'}
          </button>
        </div>
      </PageHead>

      <Section
        title="Cache impact"
        note="Known-stale shadow hits represent traffic observed while serving in shadow mode."
      >
        <Kpis
          items={[
            {
              label: 'Requests observed',
              value: observed,
              context: `Total in last ${window}`,
            },
            {
              label: 'Cache hit rate',
              value: `${(hitRate * 100).toFixed(1)}%`,
              context: 'Direct & semantic hits',
            },
            {
              label: 'Known-stale shadow hits',
              value: staleServed,
              context: 'Hits with outdated facts',
            },
            {
              label: 'Entries at risk',
              value: atRisk,
              context: 'Cache entries with stale claims',
            },
          ]}
        />
      </Section>

      <div className="grid-2-col" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1.5rem' }}>
        <Section title="Verification spend">
          <div className="card" style={{ padding: '1.25rem' }}>
            <table className="stats-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <td style={{ padding: '0.6rem 0' }}>Verification cost</td>
                  <td style={{ textAlign: 'right', fontWeight: 600 }}>{verificationCost}</td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <td style={{ padding: '0.6rem 0' }}>Tavily credits used</td>
                  <td style={{ textAlign: 'right', fontWeight: 600 }}>{number(costs.tavily_credits)} credits</td>
                </tr>
                <tr><td>Verified repairs</td><td>{number(data.repaired_hits)}</td></tr>
                <tr><td>Verification blocks</td><td>{number(data.blocked_hits)}</td></tr>
              </tbody>
            </table>
          </div>
        </Section>

        <Section title="Observed outcomes">
          <div className="card" style={{ padding: '1.25rem', backgroundColor: 'var(--color-surface-2)', borderLeft: '4px solid var(--color-accent)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
              <Badge value={staleServed > 0 ? 'evict_regen' : 'serve'} />
              <span style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>Policy engine assessment</span>
            </div>
            <p style={{ lineHeight: 1.6, margin: 0 }}>{String(data.recommendation || 'Analyzing traffic…')}</p>
          </div>
        </Section>
      </div>

      <Section
        title="Top Stale Facts Detected"
        note="Facts whose values drifted while residing in cache, ranked by blast radius."
      >
        {staleFacts.length === 0 ? (
          <div className="empty-card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--color-muted)' }}>
            No stale facts recorded in this window.
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Fact Key</th>
                  <th>Cached Value</th>
                  <th>Current Live Value</th>
                  <th>Verdict</th>
                  <th>Entries Affected</th>
                  <th>Hits / Revision</th>
                </tr>
              </thead>
              <tbody>
                {staleFacts.map((fact, i) => (
                  <tr key={String(fact.fact_id || i)}>
                    <td>
                      <code>{display(fact.fact_key)}</code>
                    </td>
                    <td style={{ color: 'var(--color-error)' }}>{display(fact.cached_value)}</td>
                    <td style={{ color: 'var(--color-success)', fontWeight: 600 }}>{display(fact.current_value)}</td>
                    <td>
                      <Badge value={fact.last_verdict} />
                    </td>
                    <td style={{ textAlign: 'center' }}>{number(fact.entries_affected)}</td>
                    <td style={{ textAlign: 'center' }}>{number(fact.hits)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
