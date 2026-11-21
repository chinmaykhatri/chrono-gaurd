import { FormEvent, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { asRecord, asRows, display, download, idPath, Page, post, put, RecordData, timestamp } from '../api/client';
import { useResource } from '../hooks/data';
import { Badge, DataTable, ErrorNotice, Json, MetricList, PageHead, State } from '../components/ui';

export function Policies() {
  const resource=useResource<Page>('/policies');const classes=useResource<Page>('/classes');const[selected,setSelected]=useState<RecordData|null>(null);const[error,setError]=useState('');const[saved,setSaved]=useState('');const[busy,setBusy]=useState(false);const[prompt,setPrompt]=useState('');const[result,setResult]=useState<RecordData|null>(null);
  function change(key:string,value:unknown){setSelected(previous=>({...previous,[key]:value}));setSaved('');}
  async function save(event:FormEvent){event.preventDefault();if(!selected)return;setBusy(true);setError('');setSaved('');try{const {id,tenant_id,created_at,updated_at,...fields}=selected;await put(`/policies/${idPath(id)}`,fields);resource.reload();setSaved('Verifier policy saved.');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <><PageHead title="Policies" description="Control verification budgets and failure behavior."/>{error&&<ErrorNotice message={error}/>}<State resource={resource}><DataTable name="policies" rows={resource.data?.items??[]} columns={[{key:'name',label:'Policy'},{key:'strictness',label:'Strictness'},{key:'mode',label:'Mode'},{key:'on_unverifiable',label:'When unverifiable'},{key:'max_claims_per_response',label:'Claim cap'},{key:'max_credits_per_response',label:'Credit cap'}]} actions={row=><button onClick={()=>{setSelected({...row});setError('');setSaved('');}}>Edit policy</button>}/></State>{selected&&<section><h2>Edit {display(selected.name)}</h2><form onSubmit={save} className="form-grid"><label>Strictness<select value={String(selected.strictness??'standard')} onChange={e=>change('strictness',e.target.value)}>{['strict','standard','lenient'].map(p=><option key={p}>{p}</option>)}</select></label><label>Verification mode<select value={String(selected.mode??'async')} onChange={e=>change('mode',e.target.value)}><option value="async">Asynchronous</option><option value="verify_before_return">Verify before return</option></select></label><label>When unverifiable<select value={String(selected.on_unverifiable??'serve_annotated')} onChange={e=>change('on_unverifiable',e.target.value)}><option value="serve_annotated">Serve with annotation</option><option value="fail_closed">Withhold response</option></select></label>{[['blocking_budget_ms',4500],['revalidate_budget_ms',3000],['regen_budget_ms',12000],['serve_min_freshness',80],['evict_below',50],['max_claims_per_response',6],['max_credits_per_response',6]].map(([key,fallback])=><label key={key}>{String(key).replaceAll('_',' ')}<input type="number" min={0} max={String(key).includes('freshness')||key==='evict_below'?100:60000} required step={1} value={Number(selected[String(key)]??fallback)} onChange={e=>change(String(key),e.target.valueAsNumber)}/></label>)}<label className="check"><input type="checkbox" checked={Boolean(selected.regen_on_stale)} onChange={e=>change('regen_on_stale',e.target.checked)}/>Regenerate stale answers</label><div className="toolbar"><button className="primary" disabled={busy}>{busy?'Saving…':'Save policy'}</button><button type="button" onClick={()=>setSelected(null)}>Cancel</button></div></form>{saved&&<p role="status" className="success">{saved}</p>}</section>}<section><h2>Policy dry run</h2><form onSubmit={async e=>{e.preventDefault();setError('');setBusy(true);try{setResult(await post('/policies/dry-run',{prompt}));}catch(err){setError((err as Error).message);}finally{setBusy(false);}}}><label>Prompt<textarea value={prompt} onChange={e=>setPrompt(e.target.value)} required maxLength={2000}/></label><button disabled={busy||!prompt.trim()}>Resolve policy</button></form>{result&&<MetricList values={result}/>}</section><section><h2>Volatility classes</h2><State resource={classes}><DataTable name="classes" rows={classes.data?.items??[]} columns={[{key:'class_key',label:'Class'},{key:'soft_ttl_seconds',label:'Soft TTL (s)'},{key:'half_life_seconds',label:'Half-life (s)'},{key:'default_strictness',label:'Strictness'},{key:'cacheable',label:'Cacheable'}]}/></State></section></>;
}
export function Settings({revision}:{revision:number}) {
  const health=useResource<RecordData>('/settings/health',revision);const bifrost=useResource<RecordData>('/settings/bifrost');const clock=useResource<RecordData>('/clock',revision);const[error,setError]=useState('');const[busy,setBusy]=useState(false);const[seconds,setSeconds]=useState(86400);const[freeze,setFreeze]=useState('');
  async function changeClock(body:RecordData){setBusy(true);setError('');try{await post('/clock',body);clock.reload();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  const connections=health.data?Object.entries(asRecord(health.data.checks??health.data)).map(([name,value])=>({name,...(typeof value==='object'?asRecord(value):{status:typeof value==='boolean'?(value?'ready':'unavailable'):value})})):[];
  return <><PageHead title="Settings" description="Check connections and manage the evaluation clock."><button onClick={()=>{health.reload();bifrost.reload();clock.reload();}}>Check connections</button></PageHead>{error&&<ErrorNotice message={error}/>}<section><h2>Service connections</h2><State resource={health}><DataTable name="connections" rows={connections} columns={[{key:'name',label:'Service'},{key:'status',label:'Status',render:r=><Badge value={r.status??r.ok}/>},{key:'detail',label:'Details'}]}/></State></section><section><h2>Bifrost integration</h2><State resource={bifrost}><MetricList values={{version:bifrost.data?.version,url:bifrost.data?.url,plugin_order:bifrost.data?.plugin_order}}/><Json value={bifrost.data} label="Gateway configuration status"/></State></section><section><h2>Evaluation clock</h2><State resource={clock}><MetricList values={{mode:clock.data?.mode,offset_seconds:clock.data?.offset_seconds,frozen_at:timestamp(clock.data?.frozen_at)}}/></State><p className="muted">Clock changes age stored verification windows. They do not change facts on the live web.</p><div className="form-grid"><form onSubmit={e=>{e.preventDefault();changeClock({action:'advance',seconds});}}><label>Advance by seconds<input type="number" min={1} max={31536000} required value={seconds} onChange={e=>setSeconds(e.target.valueAsNumber)}/></label><button disabled={busy}>Advance clock</button></form><form onSubmit={e=>{e.preventDefault();changeClock({action:'freeze',timestamp:new Date(freeze).toISOString()});}}><label>Freeze at local time<input type="datetime-local" required value={freeze} onChange={e=>setFreeze(e.target.value)}/></label><button disabled={busy}>Freeze clock</button></form></div><button disabled={busy} onClick={()=>changeClock({action:'reset'})}>Reset to real time</button></section><section><h2>Semantic-Hit Guard</h2><p>Checks whether a cache candidate matches the incoming query before returning the answer.</p><MetricList values={{status:bifrost.data?.guard_enabled?'active':'standby'}}/></section><section><h2>Privacy and retention</h2><p>Content storage, retention, and model profiles are managed in the server configuration. Connection checks report credential availability without exposing API keys.</p><Json value={health.data?.privacy} label="Privacy configuration"/></section></>;
}
export function Evaluation({ revision }: { revision: number }) {
  const datasets = useResource<Page>('/eval/datasets', revision);
  const runs = useResource<Page>('/eval/runs', revision);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function run(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await post('/eval/runs', { dataset_id: 'release-replay' });
      runs.reload();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <>
    <PageHead title="Evaluation lab" description="Compare cache policies on the same frozen release evidence and request trace." />
    {error && <ErrorNotice message={error} />}
    <section>
      <h2>Datasets</h2>
      <State resource={datasets}>
        <DataTable name="datasets" rows={datasets.data?.items ?? []} columns={[
          { key: 'name', label: 'Dataset' },
          { key: 'item_count', label: 'Items' },
          { key: 'label_date', label: 'Label date' },
          { key: 'runnable', label: 'Runnable replay', render: row => row.runnable ? 'Available' : 'Requires a capture' },
        ]} />
      </State>
    </section>
    <form onSubmit={run}>
      <button className="primary" disabled={busy || !datasets.data?.items.some(row => row.runnable)}>
        {busy ? 'Running replay…' : 'Run release replay'}
      </button>
    </form>
    <section>
      <h2>Runs</h2>
      <State resource={runs}>
        <DataTable name="evaluation-runs" rows={runs.data?.items ?? []} columns={[
          { key: 'id', label: 'Run', render: row => <Link to={`/eval/runs/${idPath(row.id)}`}>{display(row.name)}</Link> },
          { key: 'created_at', label: 'Started', render: row => timestamp(row.created_at) },
          { key: 'done', label: 'Requests per variant' },
        ]} />
      </State>
    </section>
  </>;
}

function CostFreshnessPlot({ variants }: { variants: RecordData[] }) {
  const points = variants.flatMap(row => {
    const x = row.credits_per_1000_requests;
    const y = row.stale_per_1000_hits;
    return typeof x === 'number' && typeof y === 'number' ? [{ x, y, label: display(row.variant) }] : [];
  });
  if (!points.length) return null;
  const maxX = Math.max(...points.map(point => point.x), 1);
  const maxY = Math.max(...points.map(point => point.y), 1);
  return <svg viewBox="0 0 680 310" className="curve" role="img" aria-label="Stale cache hits versus evidence credits in the controlled replay">
    <line x1="75" y1="35" x2="75" y2="248" />
    <line x1="75" y1="248" x2="620" y2="248" />
    <text x="78" y="22">Stale responses per 1,000 eligible hits</text>
    <text x="325" y="291">Evidence credits per 1,000 requests</text>
    <text x="48" y="44">{Math.ceil(maxY)}</text>
    <text x="58" y="253">0</text>
    <text x="588" y="271">{Math.ceil(maxX)}</text>
    {points.map(point => <circle key={point.label} cx={75 + 545 * point.x / maxX} cy={248 - 213 * point.y / maxY} r="6" fill="currentColor">
      <title>{point.label} · {point.x} credits · {point.y} stale hits</title>
    </circle>)}
  </svg>;
}

export function EvaluationReport({ revision }: { revision: number }) {
  const { id } = useParams();
  const resource = useResource<RecordData>(`/eval/runs/${idPath(id)}/report`, revision);
  const data = resource.data ?? {};
  const variants = asRows(data.variants);
  const failures = asRows(data.rows).filter(row => row.stale_served || row.false_correction);
  return <>
    <Link to="/eval">Evaluation lab</Link>
    <PageHead title="Release replay report">
      <button disabled={!resource.data} onClick={() => download(`evaluation-${id}.json`, JSON.stringify(data, null, 2))}>Export raw traces</button>
    </PageHead>
    <State resource={resource}>
      <p>{display(data.description)}</p>
      <MetricList values={asRecord(data.metrics)} />
      <CostFreshnessPlot variants={variants} />
      <DataTable name="evaluation-variants" rows={variants} columns={[
        { key: 'variant', label: 'Policy' },
        { key: 'eligible_hits', label: 'Eligible hits' },
        { key: 'stale_hits', label: 'Stale hits' },
        { key: 'stale_per_1000_hits', label: 'Stale / 1,000 hits' },
        { key: 'credits_per_1000_requests', label: 'Credits / 1,000 requests' },
        { key: 'repairs', label: 'Repairs' },
        { key: 'false_corrections', label: 'False corrections' },
        { key: 'provider_calls', label: 'Generation calls' },
      ]} />
      <h2>Replay failures</h2>
      <DataTable name="evaluation-failures" rows={failures.slice(0, 50)} columns={[
        { key: 'variant', label: 'Policy' },
        { key: 'request_id', label: 'Request' },
        { key: 'route', label: 'Route' },
        { key: 'returned', label: 'Returned values' },
        { key: 'gold', label: 'Expected values' },
      ]} actions={row => <Json value={row} label="Inspect trace" />} />
    </State>
  </>;
}
