-- ChronoGuard — PostgreSQL 16 init DDL
-- Generated from Document 6: Backend Schema §6.3–§6.4
-- This file is mounted at /docker-entrypoint-initdb.d/01-init.sql

-- ─── Extensions ────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── Enums ─────────────────────────────────────────────────────
CREATE TYPE strictness AS ENUM ('strict','standard','lenient');
CREATE TYPE policy_mode AS ENUM ('async','verify_before_return');
CREATE TYPE cache_status AS ENUM ('miss','hit_direct','hit_semantic','bypass');
CREATE TYPE decision_type AS ENUM (
  'passthrough','serve','serve_swr','revalidate_blocking',
  'evict_regen','evict_lazy','fail_open','fail_closed','bypass'
);
CREATE TYPE entry_status AS ENUM ('unverified','fresh','due','stale','evicted');
CREATE TYPE claim_status AS ENUM ('pending','fresh','due','stale','unverifiable','skipped');
CREATE TYPE verdict_type AS ENUM ('confirmed','outdated','contradicted','unverifiable');
CREATE TYPE trigger_type AS ENUM ('ingest','due','blocking','cascade','refresh_ahead','manual','eval');
CREATE TYPE job_state AS ENUM ('queued','running','succeeded','failed','dead','cancelled');
CREATE TYPE ledger_kind AS ENUM ('tavily_search','tavily_extract','llm_extract','llm_judge','llm_regen','llm_saved');
CREATE TYPE support_label AS ENUM ('supports','contradicts','neutral');
CREATE TYPE truth_label AS ENUM ('current','outdated','contradicted');
CREATE TYPE regen_status AS ENUM ('started','succeeded','failed','timeout');
CREATE TYPE origin_type AS ENUM ('provider','cache','regenerated','legacy_cache');

-- ─── Settings ──────────────────────────────────────────────────
CREATE TABLE settings (
  key        text        PRIMARY KEY,
  value      jsonb       NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ─── Volatility Classes ────────────────────────────────────────
CREATE TABLE volatility_classes (
  class_key            text        PRIMARY KEY,
  description          text        NOT NULL,
  half_life_seconds    bigint,
  soft_ttl_seconds     bigint,
  min_interval_seconds bigint,
  max_interval_seconds bigint,
  default_strictness   strictness  NOT NULL DEFAULT 'standard',
  salience_weight      numeric(3,2) NOT NULL DEFAULT 1.0,
  cacheable            boolean     NOT NULL DEFAULT true,
  tavily_profile       jsonb       NOT NULL DEFAULT '{}'::jsonb
);

-- ─── Source Authority ──────────────────────────────────────────
CREATE TABLE source_authority (
  domain     text    PRIMARY KEY,
  tier       smallint NOT NULL CHECK (tier BETWEEN 1 AND 4),
  category   text,
  denylisted boolean NOT NULL DEFAULT false,
  notes      text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ─── Model Profiles ───────────────────────────────────────────
CREATE TABLE model_profiles (
  model_id          text    PRIMARY KEY,
  knowledge_cutoff  date    NOT NULL,
  input_usd_per_mtok  numeric(10,4) NOT NULL DEFAULT 0,
  output_usd_per_mtok numeric(10,4) NOT NULL DEFAULT 0,
  notes             text
);

-- ─── Policies ──────────────────────────────────────────────────
CREATE TABLE policies (
  id                       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  name                     text        UNIQUE NOT NULL,
  strictness               strictness  NOT NULL,
  mode                     policy_mode NOT NULL,
  blocking_budget_ms       int         NOT NULL DEFAULT 4500,
  revalidate_budget_ms     int         NOT NULL DEFAULT 3000,
  regen_budget_ms          int         NOT NULL DEFAULT 12000,
  serve_min_freshness      smallint    NOT NULL DEFAULT 60,
  evict_below              smallint    NOT NULL DEFAULT 35,
  on_unverifiable          text        NOT NULL DEFAULT 'serve_annotated'
    CHECK (on_unverifiable IN ('serve_annotated','fail_closed')),
  regen_on_stale           boolean     NOT NULL DEFAULT true,
  stream_buffer            boolean     NOT NULL DEFAULT false,
  force_ttl                boolean     NOT NULL DEFAULT false,
  max_claims_per_response  smallint    NOT NULL DEFAULT 8,
  max_credits_per_response numeric(6,2) NOT NULL DEFAULT 6,
  class_overrides          jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now()
);

-- ─── Policy Rules ──────────────────────────────────────────────
CREATE TABLE policy_rules (
  id               uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  priority         int     NOT NULL DEFAULT 100,
  match_virtual_key text,
  match_model      text,
  match_header     text,
  match_path       text,
  policy_id        uuid    NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
  enabled          boolean NOT NULL DEFAULT true
);

-- ─── Requests ──────────────────────────────────────────────────
CREATE TABLE requests (
  id                 uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  bifrost_request_id text          UNIQUE,
  cache_key          text,
  prompt_hash        text          NOT NULL,
  messages           jsonb,
  model_id           text          NOT NULL,
  provider           text,
  stream             boolean       NOT NULL DEFAULT false,
  policy_id          uuid          REFERENCES policies(id),
  prompt_class       text          REFERENCES volatility_classes(class_key),
  cache_status       cache_status  NOT NULL,
  cache_entry_id     uuid,
  decision           decision_type NOT NULL,
  decision_detail    jsonb         NOT NULL DEFAULT '{}'::jsonb,
  hook_overhead_us   int,
  verify_latency_ms  int,
  total_latency_ms   int,
  clock_mode         text          NOT NULL DEFAULT 'real',
  sim_now            timestamptz,
  created_at         timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX requests_created_idx  ON requests (created_at DESC);
CREATE INDEX requests_decision_idx ON requests (decision, created_at DESC);
CREATE INDEX requests_entry_idx    ON requests (cache_entry_id);

-- ─── Responses ─────────────────────────────────────────────────
CREATE TABLE responses (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id        uuid        NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
  origin            origin_type NOT NULL,
  content           text,
  content_hash      text        NOT NULL,
  model_id          text        NOT NULL,
  input_tokens      int,
  output_tokens     int,
  annotation_status text        NOT NULL DEFAULT 'pending'
    CHECK (annotation_status IN ('pending','partial','complete','failed')),
  min_freshness     smallint,
  original_text     text,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX responses_request_idx ON responses (request_id);

-- ─── Cache Entries ─────────────────────────────────────────────
CREATE TABLE cache_entries (
  id                  uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  bifrost_cache_id    text         UNIQUE NOT NULL,
  cache_key           text,
  prompt_hash         text         NOT NULL,
  response_id         uuid         REFERENCES responses(id),
  status              entry_status NOT NULL DEFAULT 'unverified',
  best_before         timestamptz,
  hard_expiry         timestamptz,
  last_verified_at    timestamptz,
  hit_count           int          NOT NULL DEFAULT 0,
  hits_24h            int          NOT NULL DEFAULT 0,
  last_hit_at         timestamptz,
  policy_id           uuid         REFERENCES policies(id),
  pinned              boolean      NOT NULL DEFAULT false,
  manifest_rev        int          NOT NULL DEFAULT 0,
  supersedes_entry_id uuid         REFERENCES cache_entries(id),
  evicted_at          timestamptz,
  evict_reason        text,
  created_at          timestamptz  NOT NULL DEFAULT now()
);
ALTER TABLE requests ADD CONSTRAINT requests_entry_fk
  FOREIGN KEY (cache_entry_id) REFERENCES cache_entries(id);
CREATE INDEX cache_entries_status_idx ON cache_entries (status, best_before);
CREATE INDEX cache_entries_hot_idx    ON cache_entries (hits_24h DESC)
  WHERE status <> 'evicted';

-- ─── Facts ─────────────────────────────────────────────────────
CREATE TABLE facts (
  id                          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_key                    text        UNIQUE NOT NULL,
  fact_hash                   char(40)    NOT NULL UNIQUE,
  class_key                   text        NOT NULL REFERENCES volatility_classes(class_key),
  entity                      text        NOT NULL,
  entity_slug                 text        NOT NULL,
  attribute                   text        NOT NULL,
  qualifier                   text,
  current_value               text,
  last_verdict                verdict_type,
  freshness                   smallint,
  evidence_confidence         numeric(4,3),
  last_verified_at            timestamptz,
  fresh_until                 timestamptz,
  interval_seconds            bigint,
  consecutive_confirmations   int         NOT NULL DEFAULT 0,
  last_changed_at             timestamptz,
  verification_count          int         NOT NULL DEFAULT 0,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX facts_due_idx        ON facts (fresh_until);
CREATE INDEX facts_entity_trgm    ON facts USING gin (entity_slug gin_trgm_ops);

-- ─── Claims ────────────────────────────────────────────────────
CREATE TABLE claims (
  id                uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  response_id       uuid         NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
  cache_entry_id    uuid         REFERENCES cache_entries(id) ON DELETE SET NULL,
  fact_id           uuid         REFERENCES facts(id),
  ordinal           smallint     NOT NULL,
  text              text         NOT NULL,
  span_start        int,
  span_end          int,
  claim_type        text         NOT NULL
    CHECK (claim_type IN ('fact','opinion','procedure','definition','personal')),
  entity            text,
  attribute         text,
  stated_value      text,
  class_key         text         REFERENCES volatility_classes(class_key),
  importance        numeric(3,2) NOT NULL DEFAULT 0.5,
  as_of_hint        date,
  prior_stale       numeric(4,3),
  status            claim_status NOT NULL DEFAULT 'pending',
  skip_reason       text,
  freshness         smallint,
  last_verdict      verdict_type,
  extractor_version text         NOT NULL,
  created_at        timestamptz  NOT NULL DEFAULT now(),
  updated_at        timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX claims_response_idx ON claims (response_id);
CREATE INDEX claims_fact_idx     ON claims (fact_id);
CREATE INDEX claims_entry_idx    ON claims (cache_entry_id);

-- ─── Verifications ─────────────────────────────────────────────
CREATE TABLE verifications (
  id                       uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_id                  uuid         NOT NULL REFERENCES facts(id),
  claim_id                 uuid         REFERENCES claims(id) ON DELETE SET NULL,
  trigger_kind             trigger_type NOT NULL,
  started_at               timestamptz  NOT NULL DEFAULT now(),
  finished_at              timestamptz,
  status                   text         NOT NULL DEFAULT 'running'
    CHECK (status IN ('running','succeeded','failed','timeout','ledger_hit','coalesced')),
  queries                  jsonb        NOT NULL DEFAULT '[]'::jsonb,
  tavily_search_calls      smallint     NOT NULL DEFAULT 0,
  tavily_extract_calls     smallint     NOT NULL DEFAULT 0,
  tavily_credits           numeric(6,2) NOT NULL DEFAULT 0,
  judge_model              text,
  judge_escalated          boolean      NOT NULL DEFAULT false,
  judge_input_tokens       int,
  judge_output_tokens      int,
  verdict                  verdict_type,
  effective_verdict        verdict_type,
  corrected_value          text,
  judge_confidence         numeric(4,3),
  rationale                text,
  features                 jsonb        NOT NULL DEFAULT '{}'::jsonb,
  raw_freshness            smallint,
  freshness                smallint,
  evidence_confidence      numeric(4,3),
  evict_rule_met           boolean,
  evict_rule_reason        text,
  calibration_snapshot_id  uuid,
  latency_ms               int,
  error                    text
);
CREATE INDEX verifications_fact_idx   ON verifications (fact_id, started_at DESC);
CREATE INDEX verifications_status_idx ON verifications (status, started_at DESC);

-- ─── Evidence ──────────────────────────────────────────────────
CREATE TABLE evidence (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  verification_id  uuid        NOT NULL REFERENCES verifications(id) ON DELETE CASCADE,
  url              text        NOT NULL,
  domain           text        NOT NULL,
  title            text,
  snippet          text,
  published_at     timestamptz,
  retrieved_at     timestamptz NOT NULL DEFAULT now(),
  authority_tier   smallint    NOT NULL DEFAULT 4,
  tavily_score     numeric(5,4),
  source           text        NOT NULL CHECK (source IN ('search','extract')),
  query_index      smallint,
  label            support_label,
  label_strength   numeric(4,3),
  content_hash     text
);
CREATE INDEX evidence_verification_idx ON evidence (verification_id);
CREATE INDEX evidence_domain_idx       ON evidence (domain);

-- ─── Evidence Pins ─────────────────────────────────────────────
CREATE TABLE evidence_pins (
  id                       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_id                  uuid        NOT NULL REFERENCES facts(id),
  corrected_value          text        NOT NULL,
  evidence_ids             uuid[]      NOT NULL,
  valid_until              timestamptz NOT NULL,
  created_from_verification uuid       REFERENCES verifications(id),
  created_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evidence_pins_fact_idx ON evidence_pins (fact_id, valid_until DESC);

-- ─── Regenerations ─────────────────────────────────────────────
CREATE TABLE regenerations (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id    uuid        REFERENCES requests(id),
  old_entry_id  uuid        REFERENCES cache_entries(id),
  new_entry_id  uuid        REFERENCES cache_entries(id),
  fact_ids      uuid[]      NOT NULL,
  evidence_ids  uuid[]      NOT NULL,
  plan          text        NOT NULL CHECK (plan IN ('A_loopback','A2_prime','B_direct')),
  status        regen_status NOT NULL DEFAULT 'started',
  input_tokens  int,
  output_tokens int,
  cost_usd      numeric(10,6),
  latency_ms    int,
  error         text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- ─── Verification Jobs ─────────────────────────────────────────
CREATE TABLE verification_jobs (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_id       uuid        NOT NULL REFERENCES facts(id),
  trigger_kind  trigger_type NOT NULL,
  priority      numeric(10,4) NOT NULL DEFAULT 0,
  state         job_state   NOT NULL DEFAULT 'queued',
  attempts      smallint    NOT NULL DEFAULT 0,
  max_attempts  smallint    NOT NULL DEFAULT 3,
  run_after     timestamptz NOT NULL DEFAULT now(),
  locked_by     text,
  locked_at     timestamptz,
  last_error    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz
);
CREATE INDEX jobs_ready_idx ON verification_jobs (state, run_after, priority DESC);

-- ─── Cost Ledger ───────────────────────────────────────────────
CREATE TABLE cost_ledger (
  id               bigserial   PRIMARY KEY,
  ts               timestamptz NOT NULL DEFAULT now(),
  kind             ledger_kind NOT NULL,
  units            numeric(12,4) NOT NULL,
  unit_label       text        NOT NULL,
  usd              numeric(12,6) NOT NULL DEFAULT 0,
  class_key        text,
  model_id         text,
  virtual_key      text,
  request_id       uuid,
  verification_id  uuid,
  cache_entry_id   uuid
);
CREATE INDEX cost_ledger_ts_idx ON cost_ledger (ts DESC, kind);

-- ─── Events ────────────────────────────────────────────────────
CREATE TABLE events (
  id      bigserial   PRIMARY KEY,
  ts      timestamptz NOT NULL DEFAULT now(),
  type    text        NOT NULL,
  payload jsonb       NOT NULL
);
CREATE INDEX events_ts_idx ON events (ts DESC);

-- ─── Entity Aliases ────────────────────────────────────────────
CREATE TABLE entity_aliases (
  alias_slug    text PRIMARY KEY,
  canonical_slug text NOT NULL
);

-- ─── Evaluation Tables ─────────────────────────────────────────
CREATE TABLE eval_datasets (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text        NOT NULL,
  version     text        NOT NULL,
  description text,
  label_date  date        NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);

CREATE TABLE eval_items (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id        uuid        NOT NULL REFERENCES eval_datasets(id) ON DELETE CASCADE,
  class_key         text        NOT NULL REFERENCES volatility_classes(class_key),
  prompt            text        NOT NULL,
  model_id          text        NOT NULL,
  answer_text       text        NOT NULL,
  claim_text        text        NOT NULL,
  fact_key          text,
  label             truth_label NOT NULL,
  label_source_url  text,
  label_notes       text,
  labeler_a         text,
  labeler_b         text,
  agreed            boolean,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eval_items_dataset_idx ON eval_items (dataset_id, class_key);

CREATE TABLE eval_runs (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id  uuid        NOT NULL REFERENCES eval_datasets(id),
  variant     text        NOT NULL,
  config      jsonb       NOT NULL DEFAULT '{}'::jsonb,
  replay      boolean     NOT NULL DEFAULT false,
  status      text        NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','running','done','failed')),
  started_at  timestamptz,
  finished_at timestamptz,
  metrics     jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE eval_run_items (
  run_id             uuid        NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
  item_id            uuid        NOT NULL REFERENCES eval_items(id) ON DELETE CASCADE,
  predicted_verdict  verdict_type,
  raw_freshness      smallint,
  freshness          smallint,
  correct            boolean,
  credits            numeric(6,2),
  tokens             int,
  latency_ms         int,
  verification_id    uuid,
  PRIMARY KEY (run_id, item_id)
);

CREATE TABLE calibration_snapshots (
  id         uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id     uuid    REFERENCES eval_runs(id),
  method     text    NOT NULL CHECK (method IN ('platt','isotonic','none')),
  weights    jsonb   NOT NULL,
  bins       jsonb   NOT NULL,
  ece        numeric(5,4),
  brier      numeric(5,4),
  active     boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE verifications ADD CONSTRAINT verifications_calibration_fk
  FOREIGN KEY (calibration_snapshot_id) REFERENCES calibration_snapshots(id);

-- ─── Seed Data ─────────────────────────────────────────────────

INSERT INTO volatility_classes
  (class_key, description, half_life_seconds, soft_ttl_seconds,
   min_interval_seconds, max_interval_seconds, default_strictness,
   salience_weight, cacheable, tavily_profile)
VALUES
  ('static', 'Math, definitions, settled history',
   NULL, NULL, NULL, NULL, 'lenient', 0, true, '{}'::jsonb),
  ('slow_facts', 'Geography, institutions, long-lived statistics',
   31536000, 7776000, 2592000, 15552000, 'lenient', 0.4, true,
   jsonb_build_object('topic','general','search_depth','basic','max_results',5)),
  ('org_people', 'CEOs, founders, team, headcount',
   7776000, 1814400, 604800, 5184000, 'standard', 0.8, true,
   jsonb_build_object('topic','general','search_depth','basic','max_results',5,'news_query',true)),
  ('software_versions', 'Latest versions, deprecations, API signatures, model availability',
   1814400, 604800, 172800, 2592000, 'strict', 1.0, true,
   jsonb_build_object('topic','general','search_depth','advanced','max_results',5,'official_domains',true,'extract',true)),
  ('pricing_plans', 'Prices, tiers, quotas, rate limits',
   1209600, 259200, 43200, 1209600, 'strict', 1.0, true,
   jsonb_build_object('topic','general','search_depth','advanced','max_results',5,'official_domains',true,'extract',true)),
  ('regulation_policy', 'Laws, tax rates, deadlines, compliance rules',
   5184000, 1209600, 259200, 3888000, 'strict', 1.0, true,
   jsonb_build_object('topic','general','search_depth','advanced','max_results',5,'official_domains',true,'extract',true,'start_date_months_back',12)),
  ('news_events', 'Recent events, launches, outcomes',
   345600, 86400, 21600, 259200, 'standard', 0.7, true,
   jsonb_build_object('topic','news','search_depth','basic','max_results',6,'time_range','week','widen_to','month')),
  ('realtime', 'Asset prices, scores, weather, FX',
   900, 0, NULL, NULL, 'strict', 1.0, false,
   jsonb_build_object('topic','finance','search_depth','basic','max_results',5,'time_range','day'));

INSERT INTO policies
  (name, strictness, mode, blocking_budget_ms, revalidate_budget_ms, regen_budget_ms,
   serve_min_freshness, evict_below, on_unverifiable, regen_on_stale,
   max_claims_per_response, max_credits_per_response, class_overrides)
VALUES
  ('strict', 'strict', 'verify_before_return', 4500, 3000, 12000, 80, 50, 'fail_closed', true, 6, 6,
   jsonb_build_object('serve_annotated_classes', jsonb_build_array('slow_facts','org_people','news_events'))),
  ('standard', 'standard', 'async', 4500, 3000, 12000, 60, 35, 'serve_annotated', true, 8, 6, '{}'::jsonb),
  ('lenient', 'lenient', 'async', 4500, 3000, 12000, 40, 20, 'serve_annotated', false, 10, 4, '{}'::jsonb);

INSERT INTO source_authority (domain, tier, category, notes) VALUES
  ('pypi.org', 2, 'package_registry', NULL),
  ('www.npmjs.com', 2, 'package_registry', NULL),
  ('github.com', 3, 'code_host', 'Tier 1 only for release pages of the official organization'),
  ('stackoverflow.com', 3, 'community', NULL),
  ('www.reddit.com', 3, 'community', NULL),
  ('medium.com', 3, 'blog', NULL);

INSERT INTO model_profiles (model_id, knowledge_cutoff, notes)
VALUES ('*', (current_date - interval '18 months')::date, 'Default for unknown models');

-- Done.

