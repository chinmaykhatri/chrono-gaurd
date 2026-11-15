import { FormEvent, ReactNode, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, asRecord, asRows, display, idPath, Page, post, RecordData } from '../api/client';
import { LiveEvent, useResource } from '../hooks/data';
import { Badge, Claims, Empty, ErrorNotice, Evidence, Json, PageHead } from '../components/ui';

type Message = { role: 'user' | 'assistant'; content: string };
export function highlightClaims(text: string, claims: RecordData[]): ReactNode[] {
  const valid = claims.map(c => {
    const span = c.span;
    let start = Array.isArray(span) ? Number(span[0]) : -1;
    let end = Array.isArray(span) ? Number(span[1]) : -1;
    const phrase = String(c.text ?? c.claim_text ?? '');
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > text.length || text.slice(start,end) !== phrase) { start = phrase ? text.indexOf(phrase) : -1; end = start + phrase.length; }
    return { start, end, claim: c };
  }).filter(c => c.start >= 0 && c.end > c.start).sort((a,b) => a.start-b.start);
  const output: ReactNode[] = []; let cursor=0;
  for (const {start,end,claim} of valid) {
    if(start<cursor)continue;
    output.push(text.slice(cursor,start));
    output.push(<Link key={`${start}-${end}`} className={`claim-mark status-${String(claim.status).replaceAll(/[^a-z_]/g,'')}`} to={`/claims/${idPath(claim.claim_id??claim.id)}`} title={`Freshness: ${display(claim.freshness)}`}>{text.slice(start,end)}</Link>);
    cursor=end;
  }
  output.push(text.slice(cursor));return output;
}
export function Playground({live}:{live:{events:LiveEvent[];revision:number}}) {
  const models=useResource<Page>('/models');const [params,setParams]=useSearchParams();
  const [model,setModel]=useState('');const[policy,setPolicy]=useState('strict');const[cache,setCache]=useState(true);const[prompt,setPrompt]=useState('');const[messages,setMessages]=useState<Message[]>([]);const[result,setResult]=useState<RecordData|null>(null);const[annotation,setAnnotation]=useState<RecordData>({});const[error,setError]=useState('');const[busy,setBusy]=useState(false);const[curl,setCurl]=useState('');
  const tab=params.get('tab')??'claims';
  useEffect(()=>{if(!model&&models.data?.items[0])setModel(String(models.data.items[0].id));},[models.data,model]);
  useEffect(()=>{
    if(!result?.response_id||annotation.status==='complete')return;
    const controller=new AbortController();let timeout:ReturnType<typeof setTimeout>;
    async function poll(){try{const data=await api<RecordData>(`/responses/${idPath(result!.response_id)}/annotations`,{signal:controller.signal});setAnnotation(data);if(data.status!=='complete')timeout=setTimeout(poll,2000);}catch(e){if(!controller.signal.aborted){setError((e as Error).message);}}}
    timeout=setTimeout(poll,1000);return()=>{controller.abort();clearTimeout(timeout);};
  },[result,annotation.status]);
  async function send(event:FormEvent){event.preventDefault();if(busy||!prompt.trim()||!model)return;setBusy(true);setError('');setAnnotation({});setResult(null);const sent=[...messages,{role:'user' as const,content:prompt.trim()}];try{const data=await post<RecordData>('/playground/chat',{model,messages:sent,policy,cache,stream:false});setResult(data);setAnnotation(asRecord(data.annotation));setMessages([...sent,{role:'assistant',content:String(data.text??'')}]);setPrompt('');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function showCurl(){const body=JSON.stringify({model,messages:[...messages,...(prompt?[{role:'user',content:prompt}]:[])],stream:false});const escaped=body.replaceAll("'", "'\\''");setCurl(`curl "$BIFROST_URL/v1/chat/completions" \\\n  -H 'Content-Type: application/json' \\\n  -H 'x-cg-policy: ${policy}' \\\n${cache?"  -H 'x-bf-cache-key: your-cache-key' \\\n":''}  -d '${escaped}'`);}
  const claims=asRows(annotation.claims);const evidence=claims.flatMap(c=>asRows(c.evidence));const progress=live.events.filter(e=>e.payload.response_id===result?.response_id&&result?.response_id).slice(0,10);
  return <><PageHead title="Playground" description="Ask through Bifrost and inspect each factual claim."><button onClick={()=>{setMessages([]);setResult(null);setAnnotation({});setError('');}} disabled={busy||!messages.length}>New conversation</button><button onClick={showCurl} disabled={!model}>Show curl</button></PageHead><div className="playground"><section className="chat-pane"><form onSubmit={send}><div className="filters"><label>Model<select value={model} onChange={e=>setModel(e.target.value)} required disabled={busy||!models.data?.items.length}><option value="">{models.loading?'Loading models…':'Select model'}</option>{models.data?.items.map(m=><option key={String(m.id)} value={String(m.id)}>{String(m.id)}</option>)}</select></label><label>Policy<select value={policy} onChange={e=>setPolicy(e.target.value)} disabled={busy}>{['strict','standard','lenient'].map(p=><option key={p}>{p}</option>)}</select></label><label className="check"><input type="checkbox" checked={cache} onChange={e=>setCache(e.target.checked)} disabled={busy}/>Use semantic cache</label></div>{models.error&&<ErrorNotice message={models.error} retry={models.reload}/>}<div className="messages" aria-live="polite">{messages.length?messages.map((message,index)=><article key={index} className={`message ${message.role}`}><h2>{message.role==='user'?'You':'Bifrost response'}</h2><div className="answer-text">{message.role==='assistant'&&index===messages.length-1?highlightClaims(message.content,claims):message.content}</div></article>):<Empty title="Check an answer’s best-before date"><p>Ask about a software version, product price, or another public fact. Verification depends on your configured policy.</p></Empty>}{busy&&<p role="status">Waiting for Bifrost and the selected verification policy…</p>}</div>{error&&<ErrorNotice message={error}/>}<label htmlFor="prompt">Message</label><textarea id="prompt" rows={4} required maxLength={12000} value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="What is the latest stable version of…" disabled={busy}/><div className="compose-actions"><span className="muted">Only public, externally checkable facts are eligible.</span><button className="primary" disabled={busy||!prompt.trim()||!model}>{busy?'Verifying…':'Send request'}</button></div></form></section><section className="inspector-pane"><nav className="tabs" aria-label="Response details">{['claims','evidence','trace','raw'].map(name=><button key={name} aria-current={tab===name?'page':undefined} onClick={()=>{const next=new URLSearchParams(params);next.set('tab',name);setParams(next);}}>{name[0].toUpperCase()+name.slice(1)}</button>)}</nav>{!result?<Empty title="Response details"><p>Claims, evidence, and cache decisions appear here after a request.</p></Empty>:<><div className="annotation-summary"><Badge value={annotation.decision??'pending'}/><Badge value={annotation.cache??'unknown'}/><span>Freshness: {display(annotation.min_freshness)}</span></div>{annotation.status!=='complete'&&<p role="status">Verification {display(annotation.status??'pending')}. Annotations update automatically.</p>}{tab==='claims'&&<><Claims claims={claims}/>{typeof annotation.original_text==='string'&&<div className="correction"><h2>Original answer</h2><del>{annotation.original_text}</del><h2>Corrected answer</h2><p>{String(result.text??'')}</p></div>}</>}{tab==='evidence'&&<Evidence items={evidence}/>} {tab==='trace'&&<><Json value={result.headers} label="Response headers"/><Json value={progress} label="Verification events"/><Json value={result.trace_id} label="Trace identifier"/></>}{tab==='raw'&&<Json value={{...result,annotation}} label="Response JSON"/>}</>}</section></div>{curl&&<section><div className="split-line"><h2>Gateway request</h2><button onClick={()=>setCurl('')}>Close</button></div><p className="muted">Set BIFROST_URL and your gateway credentials locally. Replace the cache key with your application’s scoped cache key.</p><pre>{curl}</pre></section>}</>;
}
