# Document 6: Backend Schema
6.1 Conventions
PostgreSQL 16. UTC timestamptz. uuid primary keys through gen_random_uuid().
Enums for closed sets. jsonb only for flexible payloads. snake_case names. Alembic
migrations. Every table has created_at.
Clock rule: columns that drive behavior (best_before, fresh_until, next check) store
clock time, which can be simulated. Audit columns (created_at, started_at) store real
time. Where both matter the table keeps a sim_now column.
Redis holds hot copies. Postgres is the truth. Retention job deletes content older than
privacy.retention_days.
6.2 Entity overview
policies --< policy_rules
volatility_classes --< facts --< verifications --< evidence
                        |  \--< evidence_pins
                        +--< claims >-- responses >-- requests
                        claims >-- cache_entries (self reference: supersedes)
requests --< regenerations >-- cache_entries
verification_jobs >-- facts
cost_ledger (ids by reference, no foreign keys)
eval_datasets --< eval_items ; eval_runs --< eval_run_items ; 
calibration_snapshots
settings, events, model_profiles, source_authority, entity_aliases 
(standalone)
6.3 PostgreSQL DDL
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TYPE strictness AS ENUM ('strict','standard','lenient');
CREATE TYPE policy_mode AS ENUM ('async','verify_before_return');
CREATE TYPE cache_status AS ENUM 
('miss','hit_direct','hit_semantic','bypass');
CREATE TYPE decision_type AS ENUM 
('passthrough','serve','serve_swr','revalidate_blocking',
  'evict_regen','evict_lazy','fail_open','fail_closed','bypass');
CREATE TYPE entry_status AS ENUM 
('unverified','fresh','due','stale','evicted');
CREATE TYPE claim_status AS ENUM 
('pending','fresh','due','stale','unverifiable','skipped');
CREATE TYPE verdict_type AS ENUM 
('confirmed','outdated','contradicted','unverifiable');
CREATE TYPE trigger_type AS ENUM 
('ingest','due','blocking','cascade','refresh_ahead','manual','eval');
CREATE TYPE job_state AS ENUM 
('queued','running','succeeded','failed','dead','cancelled');
CREATE TYPE ledger_kind AS ENUM 
('tavily_search','tavily_extract','llm_extract','llm_judge','llm_regen','llm_
saved');
CREATE TYPE support_label AS ENUM ('supports','contradicts','neutral');
CREATE TYPE truth_label AS ENUM ('current','outdated','contradicted');
CREATE TYPE regen_status AS ENUM ('started','succeeded','failed','timeout');
CREATE TYPE origin_type AS ENUM 
('provider','cache','regenerated','legacy_cache');
CREATE TABLE settings (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE volatility_classes (
  class_key text PRIMARY KEY,
  description text NOT NULL,
  half_life_seconds bigint,               -- NULL means no decay
  soft_ttl_seconds bigint,                -- NULL means none, 0 means never 
cache
  min_interval_seconds bigint,
  max_interval_seconds bigint,
  default_strictness strictness NOT NULL DEFAULT 'standard',
  salience_weight numeric(3,2) NOT NULL DEFAULT 1.0,
  cacheable boolean NOT NULL DEFAULT true,
  tavily_profile jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE source_authority (
  domain text PRIMARY KEY,
  tier smallint NOT NULL CHECK (tier BETWEEN 1 AND 4),
  category text,
  denylisted boolean NOT NULL DEFAULT false,
  notes text,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE model_profiles (
  model_id text PRIMARY KEY,              -- provider/model as used in 
Bifrost
  knowledge_cutoff date NOT NULL,
  input_usd_per_mtok numeric(10,4) NOT NULL DEFAULT 0,
  output_usd_per_mtok numeric(10,4) NOT NULL DEFAULT 0,
  notes text
);
CREATE TABLE policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  strictness strictness NOT NULL,
  mode policy_mode NOT NULL,
  blocking_budget_ms int NOT NULL DEFAULT 4500,
  revalidate_budget_ms int NOT NULL DEFAULT 3000,
  regen_budget_ms int NOT NULL DEFAULT 12000,
  serve_min_freshness smallint NOT NULL DEFAULT 60,
  evict_below smallint NOT NULL DEFAULT 35,
  on_unverifiable text NOT NULL DEFAULT 'serve_annotated'
    CHECK (on_unverifiable IN ('serve_annotated','fail_closed')),
  regen_on_stale boolean NOT NULL DEFAULT true,
  stream_buffer boolean NOT NULL DEFAULT false,
  force_ttl boolean NOT NULL DEFAULT false,
  max_claims_per_response smallint NOT NULL DEFAULT 8,
  max_credits_per_response numeric(6,2) NOT NULL DEFAULT 6,
  class_overrides jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE policy_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  priority int NOT NULL DEFAULT 100,
  match_virtual_key text,
  match_model text,
  match_header text,
  match_path text,
  policy_id uuid NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
  enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bifrost_request_id text UNIQUE,
  cache_key text,
  prompt_hash text NOT NULL,
  messages jsonb,                         -- only when privacy.store_content 
is true
  model_id text NOT NULL,
  provider text,
  stream boolean NOT NULL DEFAULT false,
  policy_id uuid REFERENCES policies(id),
  prompt_class text REFERENCES volatility_classes(class_key),
  cache_status cache_status NOT NULL,
  cache_entry_id uuid,                    -- foreign key added below
  decision decision_type NOT NULL,
  decision_detail jsonb NOT NULL DEFAULT '{}'::jsonb,   -- trace steps and 
reason codes
  hook_overhead_us int,
  verify_latency_ms int,
  total_latency_ms int,
  clock_mode text NOT NULL DEFAULT 'real',
  sim_now timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX requests_created_idx ON requests (created_at DESC);
CREATE INDEX requests_decision_idx ON requests (decision, created_at DESC);
CREATE INDEX requests_entry_idx ON requests (cache_entry_id);
CREATE TABLE responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
  origin origin_type NOT NULL,
  content text,                           -- NULL when store_content is false
  content_hash text NOT NULL,
  model_id text NOT NULL,
  input_tokens int,
  output_tokens int,
  annotation_status text NOT NULL DEFAULT 'pending'
    CHECK (annotation_status IN ('pending','partial','complete','failed')),
  min_freshness smallint,
  original_text text,                     -- set when repair mode replaced 
the text
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX responses_request_idx ON responses (request_id);
CREATE TABLE cache_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bifrost_cache_id text UNIQUE NOT NULL,  -- id used by the Bifrost cache 
plugin [verify V2]
  cache_key text,
  prompt_hash text NOT NULL,
  response_id uuid REFERENCES responses(id),
  status entry_status NOT NULL DEFAULT 'unverified',
  best_before timestamptz,
  hard_expiry timestamptz,
  last_verified_at timestamptz,
  hit_count int NOT NULL DEFAULT 0,
  hits_24h int NOT NULL DEFAULT 0,
  last_hit_at timestamptz,
  policy_id uuid REFERENCES policies(id),
  pinned boolean NOT NULL DEFAULT false,
  manifest_rev int NOT NULL DEFAULT 0,
  supersedes_entry_id uuid REFERENCES cache_entries(id),
  evicted_at timestamptz,
  evict_reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE requests ADD CONSTRAINT requests_entry_fk
  FOREIGN KEY (cache_entry_id) REFERENCES cache_entries(id);
CREATE INDEX cache_entries_status_idx ON cache_entries (status, best_before);
CREATE INDEX cache_entries_hot_idx ON cache_entries (hits_24h DESC) WHERE 
status <> 'evicted';
CREATE TABLE facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_key text UNIQUE NOT NULL,          -- 
class:entity_slug:attribute[:qualifier]
  fact_hash char(40) NOT NULL UNIQUE,     -- sha1(fact_key), Redis key suffix
  class_key text NOT NULL REFERENCES volatility_classes(class_key),
  entity text NOT NULL,
  entity_slug text NOT NULL,
  attribute text NOT NULL,
  qualifier text,
  current_value text,                     -- latest verified value
  last_verdict verdict_type,
  freshness smallint,
  evidence_confidence numeric(4,3),
  last_verified_at timestamptz,
  fresh_until timestamptz,
  interval_seconds bigint,
  consecutive_confirmations int NOT NULL DEFAULT 0,
  last_changed_at timestamptz,
  verification_count int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX facts_due_idx ON facts (fresh_until);
CREATE INDEX facts_entity_trgm ON facts USING gin (entity_slug gin_trgm_ops);
CREATE TABLE claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  response_id uuid NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
  cache_entry_id uuid REFERENCES cache_entries(id) ON DELETE SET NULL,
  fact_id uuid REFERENCES facts(id),
  ordinal smallint NOT NULL,
  text text NOT NULL,
  span_start int,
  span_end int,
  claim_type text NOT NULL
    CHECK (claim_type IN 
('fact','opinion','procedure','definition','personal')),
  entity text,
  attribute text,
  stated_value text,
  class_key text REFERENCES volatility_classes(class_key),
  importance numeric(3,2) NOT NULL DEFAULT 0.5,
  as_of_hint date,
  prior_stale numeric(4,3),
  status claim_status NOT NULL DEFAULT 'pending',
  skip_reason text,
  freshness smallint,
  last_verdict verdict_type,
  extractor_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX claims_response_idx ON claims (response_id);
CREATE INDEX claims_fact_idx ON claims (fact_id);
CREATE INDEX claims_entry_idx ON claims (cache_entry_id);
6.3 (continued) Verification, evidence and regeneration tables
CREATE TABLE verifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_id uuid NOT NULL REFERENCES facts(id),
  claim_id uuid REFERENCES claims(id) ON DELETE SET NULL,
  trigger_kind trigger_type NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL DEFAULT 'running'
    CHECK (status IN 
('running','succeeded','failed','timeout','ledger_hit','coalesced')),
  queries jsonb NOT NULL DEFAULT '[]'::jsonb,        -- queries and Tavily 
parameters used
  tavily_search_calls smallint NOT NULL DEFAULT 0,
  tavily_extract_calls smallint NOT NULL DEFAULT 0,
  tavily_credits numeric(6,2) NOT NULL DEFAULT 0,
  judge_model text,
  judge_escalated boolean NOT NULL DEFAULT false,
  judge_input_tokens int,
  judge_output_tokens int,
  verdict verdict_type,
  effective_verdict verdict_type,                     -- after the two-key 
rule
  corrected_value text,
  judge_confidence numeric(4,3),
  rationale text,
  features jsonb NOT NULL DEFAULT '{}'::jsonb,
  raw_freshness smallint,
  freshness smallint,                                 -- after calibration
  evidence_confidence numeric(4,3),
  evict_rule_met boolean,
  evict_rule_reason text,
  calibration_snapshot_id uuid,                       -- foreign key added 
below
  latency_ms int,
  error text
);
CREATE INDEX verifications_fact_idx ON verifications (fact_id, started_at 
DESC);
CREATE INDEX verifications_status_idx ON verifications (status, started_at 
DESC);
CREATE TABLE evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  verification_id uuid NOT NULL REFERENCES verifications(id) ON DELETE 
CASCADE,
  url text NOT NULL,
  domain text NOT NULL,
  title text,
  snippet text,                                       -- at most 600 
characters
  published_at timestamptz,
  retrieved_at timestamptz NOT NULL DEFAULT now(),
  authority_tier smallint NOT NULL DEFAULT 4,
  tavily_score numeric(5,4),
  source text NOT NULL CHECK (source IN ('search','extract')),
  query_index smallint,                               -- which synthesized 
query returned it
  label support_label,
  label_strength numeric(4,3),
  content_hash text
);
CREATE INDEX evidence_verification_idx ON evidence (verification_id);
CREATE INDEX evidence_domain_idx ON evidence (domain);
CREATE TABLE evidence_pins (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_id uuid NOT NULL REFERENCES facts(id),
  corrected_value text NOT NULL,
  evidence_ids uuid[] NOT NULL,
  valid_until timestamptz NOT NULL,
  created_from_verification uuid REFERENCES verifications(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evidence_pins_fact_idx ON evidence_pins (fact_id, valid_until 
DESC);
CREATE TABLE regenerations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid REFERENCES requests(id),
  old_entry_id uuid REFERENCES cache_entries(id),
  new_entry_id uuid REFERENCES cache_entries(id),
  fact_ids uuid[] NOT NULL,
  evidence_ids uuid[] NOT NULL,
  plan text NOT NULL CHECK (plan IN ('A_loopback','A2_prime','B_direct')),
  status regen_status NOT NULL DEFAULT 'started',
  input_tokens int,
  output_tokens int,
  cost_usd numeric(10,6),
  latency_ms int,
  error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
6.3 (continued) Jobs, costs, events and aliases
-- The live queue is the Redis stream cg:q:verify. This table is the audit 
and retry backup.
CREATE TABLE verification_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_id uuid NOT NULL REFERENCES facts(id),
  trigger_kind trigger_type NOT NULL,
  priority numeric(10,4) NOT NULL DEFAULT 0,
  state job_state NOT NULL DEFAULT 'queued',
  attempts smallint NOT NULL DEFAULT 0,
  max_attempts smallint NOT NULL DEFAULT 3,
  run_after timestamptz NOT NULL DEFAULT now(),
  locked_by text,
  locked_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX jobs_ready_idx ON verification_jobs (state, run_after, priority 
DESC);
CREATE TABLE cost_ledger (
  id bigserial PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  kind ledger_kind NOT NULL,
  units numeric(12,4) NOT NULL,
  unit_label text NOT NULL,                           -- credits, 
input_tokens, output_tokens
  usd numeric(12,6) NOT NULL DEFAULT 0,
  class_key text,
  model_id text,
  virtual_key text,                                   -- Bifrost virtual key 
used, if any
  request_id uuid,
  verification_id uuid,
  cache_entry_id uuid
);
CREATE INDEX cost_ledger_ts_idx ON cost_ledger (ts DESC, kind);
CREATE TABLE events (
  id bigserial PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  type text NOT NULL,
  payload jsonb NOT NULL
);
CREATE INDEX events_ts_idx ON events (ts DESC);
CREATE TABLE entity_aliases (
  alias_slug text PRIMARY KEY,
  canonical_slug text NOT NULL
);
6.3 (continued) Evaluation tables
CREATE TABLE eval_datasets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  version text NOT NULL,
  description text,
  label_date date NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);
CREATE TABLE eval_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id uuid NOT NULL REFERENCES eval_datasets(id) ON DELETE CASCADE,
  class_key text NOT NULL REFERENCES volatility_classes(class_key),
  prompt text NOT NULL,
  model_id text NOT NULL,
  answer_text text NOT NULL,
  claim_text text NOT NULL,
  fact_key text,
  label truth_label NOT NULL,
  label_source_url text,
  label_notes text,
  labeler_a text,
  labeler_b text,
  agreed boolean,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eval_items_dataset_idx ON eval_items (dataset_id, class_key);
CREATE TABLE eval_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id uuid NOT NULL REFERENCES eval_datasets(id),
  variant text NOT NULL,        -- B0_none, B1_ttl, B2_selfcheck, 
B3_verify_all, CG_full, CG_no_ledger, ...
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  replay boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN 
('queued','running','done','failed')),
  started_at timestamptz,
  finished_at timestamptz,
  metrics jsonb,                -- precision, recall, f1, auroc, pr_auc, ece, 
brier, abstain_rate, credits, tokens, p50, p95
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE eval_run_items (
  run_id uuid NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
  item_id uuid NOT NULL REFERENCES eval_items(id) ON DELETE CASCADE,
  predicted_verdict verdict_type,
  raw_freshness smallint,
  freshness smallint,
  correct boolean,
  credits numeric(6,2),
  tokens int,
  latency_ms int,
  verification_id uuid,
  PRIMARY KEY (run_id, item_id)
);
CREATE TABLE calibration_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES eval_runs(id),
  method text NOT NULL CHECK (method IN ('platt','isotonic','none')),
  weights jsonb NOT NULL,
  bins jsonb NOT NULL,
  ece numeric(5,4),
  brier numeric(5,4),
  active boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE verifications ADD CONSTRAINT verifications_calibration_fk
  FOREIGN KEY (calibration_snapshot_id) REFERENCES calibration_snapshots(id);
6.4 Seed data
INSERT INTO volatility_classes
 (class_key, description, half_life_seconds, soft_ttl_seconds, 
min_interval_seconds,
  max_interval_seconds, default_strictness, salience_weight, cacheable, 
tavily_profile)
VALUES
 ('static','Math, definitions, settled 
history',NULL,NULL,NULL,NULL,'lenient',0,true,'{}'::jsonb),
 ('slow_facts','Geography, institutions, long-lived 
statistics',31536000,7776000,2592000,15552000,'lenient',0.4,true,
   
jsonb_build_object('topic','general','search_depth','basic','max_results',5))
,
 ('org_people','CEOs, founders, team, 
headcount',7776000,1814400,604800,5184000,'standard',0.8,true,
   
jsonb_build_object('topic','general','search_depth','basic','max_results',5,'
news_query',true)),
 ('software_versions','Latest versions, deprecations, API signatures, model 
availability',1814400,604800,172800,2592000,'strict',1.0,true,
   
jsonb_build_object('topic','general','search_depth','advanced','max_results',
5,'official_domains',true,'extract',true)),
 ('pricing_plans','Prices, tiers, quotas, rate 
limits',1209600,259200,43200,1209600,'strict',1.0,true,
   
jsonb_build_object('topic','general','search_depth','advanced','max_results',
5,'official_domains',true,'extract',true)),
 ('regulation_policy','Laws, tax rates, deadlines, compliance 
rules',5184000,1209600,259200,3888000,'strict',1.0,true,
   
jsonb_build_object('topic','general','search_depth','advanced','max_results',
5,'official_domains',true,'extract',true,'start_date_months_back',12)),
 ('news_events','Recent events, launches, 
outcomes',345600,86400,21600,259200,'standard',0.7,true,
   
jsonb_build_object('topic','news','search_depth','basic','max_results',6,'tim
e_range','week','widen_to','month')),
 ('realtime','Asset prices, scores, weather, 
FX',900,0,NULL,NULL,'strict',1.0,false,
   
jsonb_build_object('topic','finance','search_depth','basic','max_results',5,'
time_range','day'));
INSERT INTO policies
 (name, strictness, mode, blocking_budget_ms, revalidate_budget_ms, 
regen_budget_ms,
  serve_min_freshness, evict_below, on_unverifiable, regen_on_stale,
  max_claims_per_response, max_credits_per_response, class_overrides)
VALUES
 
('strict','strict','verify_before_return',4500,3000,12000,80,50,'fail_closed'
,true,6,6,
   jsonb_build_object('serve_annotated_classes', 
jsonb_build_array('slow_facts','org_people','news_events'))),
 
('standard','standard','async',4500,3000,12000,60,35,'serve_annotated',true,8
,6,'{}'::jsonb),
 
('lenient','lenient','async',4500,3000,12000,40,20,'serve_annotated',false,10
,4,'{}'::jsonb);
INSERT INTO source_authority (domain, tier, category, notes) VALUES
 ('pypi.org',2,'package_registry',NULL),
 ('www.npmjs.com',2,'package_registry',NULL),
 ('github.com',3,'code_host','Tier 1 only for release pages of the official 
organization. Set per demo entity'),
 ('stackoverflow.com',3,'community',NULL),
 ('www.reddit.com',3,'community',NULL),
 ('medium.com',3,'blog',NULL);
INSERT INTO model_profiles (model_id, knowledge_cutoff, notes)
VALUES ('*', (current_date - interval '18 months')::date, 'Default for 
unknown models');
Notes: (1) the strict policy sets on_unverifiable to fail_closed, and the class override
serve_annotated_classes exempts classes where failing closed would be too harsh, so in
practice only software_versions, pricing_plans and regulation_policy fail closed. (2)
Vendor documentation, pricing and changelog domains for the demo entities are added as
tier 1 rows in source_authority before the demo. Government and standards-body
suffixes are tier 1 by suffix rule in code. (3) Add one model_profiles row per model you
use, with its real knowledge cutoff and prices. Without it the 18-month default applies.
6.5 Redis keys
Key
Type
Value
TTL
Writer, reader
cg:manifest:
{cache_id}
string
(JSON)
Claim manifest with
revision (6.6)
hard_expiry
+ 1 day
Verifier
(compare-and-
set), cg-front
cg:idx:fact:
{fact_hash}:entries
set
Cache ids that
mention the fact
none, SREM
on evict
Verifier
Key
Type
Value
TTL
Writer, reader
cg:fact:{fact_hash}
hash
last_verdict,
freshness,
current_value,
fresh_until,
interval_s,
confirmations,
version
fresh_until +
7 days
Verifier
cg:sf:{fact_hash}
string
Singleflight lock
token
30 s
Verifier
cg:sfdone:
{fact_hash}
pub/sub
Result id
n/a
Verifier
cg:rv:{fact_hash}
string
Revalidation dedupe
flag
60 s
Verifier
cg:ing:{request_id}
string
Ingest dedupe flag
1 h
Verifier
cg:q:verify
stream
Verification jobs,
consumer group
verifiers
Trimmed to
10,000
Verifier
cg:q:dead
stream
Dead-lettered jobs
Trimmed
Operators
cg:ground:
{ground_id}
string
(JSON)
Grounding bundle
(6.6)
600 s
Verifier, cg-
back
cg:prime:{prime_id}
string
(JSON)
Pre-generated
answer for Plan A2
600 s
Verifier, cg-
back
cg:bucket:tavily and
cg:bucket:llm
hash
tokens, last_refill
none
Verifier
cg:clock
hash
mode,
offset_seconds,
frozen_at
none
Verifier writes,
all read
cg:pol:{policy_id}
string
(JSON)
Resolved policy
none
Verifier, cg-
front
cg:cfg:version
string
Integer config
version
none
Verifier writes,
plugins poll
6.6 Wire schemas (JSON shown as YAML)
Claim manifest (Redis cg:manifest:{cache_id})
v: 1
rev: 7
cache_id: string
response_id: uuid
model_id: provider/model
created_at: timestamp
as_of: date                  # model knowledge cutoff used for the prior
best_before: timestamp | null
hard_expiry: timestamp
status: unverified | fresh | due | stale | evicted
policy: strict | standard | lenient
pinned: boolean
claims:
  - claim_id: uuid
    fact_key: string
    class: string
    text: string
    span: [start, end]
    status: pending | fresh | due | stale | unverifiable | skipped
    freshness: 0..100 | null
    verdict: confirmed | outdated | contradicted | unverifiable | null
    corrected_value: string | null
    last_verified_at: timestamp | null
    next_check_at: timestamp | null
Response annotation (extra_fields.chronoguard, and the annotation URL)
Key
Type
Value
TTL
Writer, reader
cg:hits:{cache_id}
hash
Hourly hit counters
(hits_24h is the sum)
26 h
cg-front
(HINCRBY),
Verifier
cg:events
pub/sub
JSON events for SSE
n/a
Verifier
cg:evstream
stream
Event buffer while
Postgres is down
Trimmed
Verifier
response_id: uuid
decision: passthrough | serve | serve_swr | revalidate_blocking | evict_regen 
| evict_lazy | fail_open | fail_closed | bypass
cache: hit | miss | bypass
mode: inline | async | manifest
status: complete | partial | pending
clock: real | simulated
min_freshness: 0..100 | null
policy: string
claims:
  - claim_id: uuid
    text: string
    span: [start, end]
    status: string
    freshness: 0..100 | null
    verdict: string | null
    corrected_value: string | null
    checked_at: timestamp | null
    next_check_at: timestamp | null
    evidence:
      - url: string
        title: string
        domain: string
        published_at: timestamp | null
        tier: 1..4
        source: tavily_search | tavily_extract
original_text: string | null   # set when repair mode replaced the text
annotations_url: string
Grounding bundle (Redis cg:ground:{ground_id})
ground_id: string
request_id: string
facts: [{fact_key, old_value, new_value, as_of}]
evidence: [{id, url, title, published_at, snippet}]   # at most 8, snippets 
escaped
instruction: string
expires_at: timestamp
SSE envelope: event: {type}, id: {events.id}, data: {ts, type, payload}. Types are listed in
Document 2, section 2.7.
6.7 Console REST API and SSE
Base path /api/v1. Authentication: httpOnly cookie after POST /auth/login. JSON bodies,
ISO timestamps, cursor pagination (limit up to 200, opaque cursor). Errors use {error:
{code, message, details}} with codes unauthorized, validation_error, not_found,
budget_exhausted, chronoguard_unverifiable and upstream_unavailable.
Method
Path
Purpose
POST
/auth/login
Log in with the admin password
GET
/summary?window=24h
KPIs (shape below)
GET
/requests
List with filters: decision, class, policy,
cache_status, cursor
GET
/requests/{id}
Detail with decision trace
GET
/responses/{id}/annotations
Annotation object (6.6)
GET
/cache-entries
List with filters: status, class, model, hot
GET
/cache-entries/{id}
Detail with manifest and history
POST
/cache-
entries/{id}/revalidate
Force revalidation (bypass the ledger)
POST
/cache-entries/{id}/evict
Evict through Bifrost cache clear
POST
/cache-entries/{id}/pin
Pin or unpin (body: pinned)
GET
/claims/{id}
Claim with verifications, evidence and score
features
GET
/facts and /facts/{id}
Fact Ledger with affected entries
POST
/facts/{id}/reverify
Force a new verification
GET, PUT
/policies and /policies/{id}
Read and edit policies
GET, PUT
/classes and /classes/{key}
Read and edit volatility classes
POST
/policies/dry-run
Resolve a pasted prompt to class and policy
GET
/costs?window=
Spend, savings, net, by day, kind and class
GET
/latency?window=
Histograms for hook overhead, verification,
regeneration
Summary shape
window: 24h
requests: int
hit_rate: number
stale_prevented: int            # evict_regen plus fail_closed
tokens_saved: int
tavily_credits: number
net_usd: number
hook_overhead_p99_us: int
decisions: {serve: n, serve_swr: n, revalidate_blocking: n, evict_regen: n, 
...}
entry_status: {fresh: n, due: n, stale: n, unverified: n}
Playground chat
POST /playground/chat
  request:  {model, messages, policy, cache: bool, stream: false}
  response: {response_id, request_id, text, annotation, headers, trace_id}
Method
Path
Purpose
POST
/playground/chat
Proxy to Bifrost with the right headers
GET,
POST
/clock
Read the clock. Set, advance, freeze or reset it
GET,
POST
/eval/datasets
List and import datasets
GET
/eval/datasets/{id}/items
Items with labels
POST,
GET
/eval/runs and /eval/runs/{id}
Start a run. Read status and metrics
GET
/eval/runs/{id}/report
Report data: curves, calibration bins,
confusion matrix, per-class table
GET
/events/stream
SSE stream of events
GET
/settings/health
Connection checks
GET
/settings/bifrost
Bifrost version, plugin order, virtual keys and
their spend [verify]
6.8 Data lifecycle and retention
A reconcile job runs every 5 minutes. It rebuilds missing Redis manifests from Postgres,
drops orphan manifests, and corrects hits_24h from cg:hits counters.
6.9 Sample queries for the console
-- Cache hit rate, last 24 hours
SELECT count(*) FILTER (WHERE cache_status IN 
('hit_direct','hit_semantic'))::float
       / NULLIF(count(*), 0) AS hit_rate
FROM requests WHERE created_at > now() - interval '24 hours';
-- Stale answers prevented
SELECT count(*) FROM requests
WHERE created_at > now() - interval '24 hours' AND decision IN 
('evict_regen','fail_closed');
Data
Retention
Mechanism
requests.messages,
responses.content, claims text
privacy.retention_days
(7)
Nightly job nulls content
columns and deletes rows
past retention, except rows
referenced by evaluation
evidence snippets
7 days
Snippet nulled. URL, domain,
date and hash kept
cache_entries
Until evicted, then 30
days
Nightly delete
facts
Kept
Small table. Needed for the
ledger
verifications
30 days
Nightly delete
cost_ledger
90 days
Nightly delete
events
7 days
Nightly delete
eval_datasets, eval_runs and
children
Kept
Needed for reproducibility
Redis manifests
hard_expiry + 1 day
TTL
-- Saved, spent and net
SELECT sum(usd) FILTER (WHERE kind = 'llm_saved') AS saved,
       sum(usd) FILTER (WHERE kind <> 'llm_saved') AS spent,
       coalesce(sum(usd) FILTER (WHERE kind = 'llm_saved'), 0)
         - coalesce(sum(usd) FILTER (WHERE kind <> 'llm_saved'), 0) AS net
FROM cost_ledger WHERE ts > now() - interval '24 hours';
-- Ledger reuse rate
SELECT count(*) FILTER (WHERE status IN ('ledger_hit','coalesced'))::float
       / NULLIF(count(*), 0) AS reuse
FROM verifications WHERE started_at > now() - interval '24 hours';
-- Cascade impact of one fact
SELECT ce.id, ce.status, ce.hits_24h
FROM claims c JOIN cache_entries ce ON ce.id = c.cache_entry_id
WHERE c.fact_id = $1 AND ce.status <> 'evicted';
-- Hook overhead p99 on cache hits, last hour
SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY hook_overhead_us)
FROM requests
WHERE cache_status IN ('hit_direct','hit_semantic') AND created_at > now() - 
interval '1 hour';
-- Tavily credits by class, last 24 hours
SELECT class_key, sum(units) AS credits
FROM cost_ledger
WHERE kind IN ('tavily_search','tavily_extract') AND ts > now() - interval 
'24 hours'
GROUP BY class_key ORDER BY credits DESC;
