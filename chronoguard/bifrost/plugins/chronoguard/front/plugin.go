// Package front implements the cg-front Bifrost plugin.
//
// cg-front is registered BEFORE semantic_cache in the plugin chain. Pre-hooks
// run in registration order and post-hooks run in reverse, so cg-front's
// PostLLMHook sees cache hits on the way out while cg-back only runs when the
// provider is really called.
//
// Responsibilities (per Doc 4 §4.4.1):
//   - HTTPTransportPreHook:  classify prompt headers, policy, cache headers, kill-switch
//   - PreRequestHook:        extract prompt text from BifrostRequest, classify volatility
//   - PreLLMHook:            timer / state management
//   - PostLLMHook:           miss -> ingest/verify-inline; hit -> manifest lookup, decision, annotations, regen
//   - HTTPTransportPostHook / HTTPTransportResponseHeadersHook: add x-cg-* response headers
//   - HTTPTransportStreamChunkHook: stream pass-through
//   - Cleanup:               drain queues, close Redis
package front

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/chronoguard/chronoguard/internal/classify"
	"github.com/chronoguard/chronoguard/internal/decide"
	"github.com/chronoguard/chronoguard/internal/guard"
	"github.com/chronoguard/chronoguard/internal/manifest"
	"github.com/chronoguard/chronoguard/internal/runtime"
	"github.com/maximhq/bifrost/core/schemas"
)

// Plugin is the cg-front Bifrost plugin.
type Plugin struct {
	rt *runtime.Runtime
}

// Ensure Plugin implements required Bifrost plugin interfaces.
var (
	_ schemas.BasePlugin          = (*Plugin)(nil)
	_ schemas.HTTPTransportPlugin = (*Plugin)(nil)
	_ schemas.LLMPlugin           = (*Plugin)(nil)
)

// New creates the cg-front plugin and initialises its shared runtime.
func New(raw json.RawMessage) (*Plugin, error) {
	cfg := runtime.Config{Enabled: true}
	if len(raw) > 0 {
		if err := json.Unmarshal(raw, &cfg); err != nil {
			return nil, err
		}
	}
	rt, err := runtime.New(cfg)
	if err != nil {
		return nil, err
	}
	return &Plugin{rt: rt}, nil
}

// GetName returns the plugin name for Bifrost registration.
func (p *Plugin) GetName() string {
	return "cg-front"
}

// HTTPTransportPreAuthHook is a no-op for cg-front.
func (p *Plugin) HTTPTransportPreAuthHook(ctx *schemas.BifrostContext, req *schemas.HTTPRequest) (*schemas.HTTPResponse, error) {
	return nil, nil
}

// HTTPTransportPreHook inspects request headers, sets cache TTLs, and initializes state.
func (p *Plugin) HTTPTransportPreHook(ctx *schemas.BifrostContext, req *schemas.HTTPRequest) (*schemas.HTTPResponse, error) {
	if !p.rt.Config.Enabled {
		return nil, nil
	}

	s := &runtime.State{
		ID:      runtime.NewID(),
		Started: time.Now(),
		Tenant:  runtime.Tenant(ctx, p.rt.Config.SingleTenantID),
		Policy:  decide.Default(p.rt.Config.DefaultPolicy),
	}

	if req != nil {
		// Resolve policy from header or default.
		policyName := req.CaseInsensitiveHeaderLookup("x-cg-policy")
		if policyName == "" {
			policyName = p.rt.Config.DefaultPolicy
		}
		if policyName == "" {
			policyName = "standard"
		}
		s.Policy = decide.Default(policyName)

		// Check shadow mode header or config
		shadowHeader := req.CaseInsensitiveHeaderLookup("x-cg-shadow")
		if p.rt.Config.ShadowEnabled || (p.rt.Config.AllowShadowHeader && (shadowHeader == "1" || strings.EqualFold(shadowHeader, "true"))) {
			s.Shadow = true
		}

		// Check guard mode header or config
		guardHeader := req.CaseInsensitiveHeaderLookup("x-cg-guard")
		if guardHeader == "1" || strings.EqualFold(guardHeader, "true") || p.rt.Config.GuardEnabled {
			s.GuardEnabled = true
		}

		// Internal requests from verifier's regeneration loop skip ChronoGuard.
		internalKey := req.CaseInsensitiveHeaderLookup("x-cg-internal-key")
		if internalKey != "" && runtime.Trusted(internalKey, p.rt.Key) {
			s.Internal = true
			s.Skip = true
		}

		if strings.HasSuffix(req.Path, "/chat/completions") && json.Valid(req.Body) {
			s.Chat = append(json.RawMessage(nil), req.Body...)
		}
		if req.Headers == nil {
			req.Headers = make(map[string]string)
		}
	}

	ctx.SetValue(runtime.StateKey, s)
	return nil, nil
}

// PreRequestHook extracts messages from BifrostRequest and classifies the prompt.
func (p *Plugin) PreRequestHook(ctx *schemas.BifrostContext, req *schemas.BifrostRequest) error {
	s := runtime.Get(ctx)
	if s == nil || s.Skip || req == nil {
		return nil
	}
	s.Tenant = runtime.Tenant(ctx, p.rt.Config.SingleTenantID)

	if req.ChatRequest != nil {
		s.Model = req.ChatRequest.Model
		s.Messages = extractMessages(req)
		text := lastUserMessage(req)
		s.Prompt = text
		s.QuerySignature = guard.Extract(text).Encode()
		s.Class = classify.Prompt(text)

		// Apply TTL / bypass if classified
		if s.Class == "realtime" {
			s.BypassCache = true
		}
	}

	return nil
}

// PreLLMHook is called before the provider call.
func (p *Plugin) PreLLMHook(ctx *schemas.BifrostContext, req *schemas.BifrostRequest) (*schemas.BifrostRequest, *schemas.LLMPluginShortCircuit, error) {
	s := runtime.Get(ctx)
	if s == nil || s.Skip || req == nil {
		return req, nil, nil
	}
	policy, err := p.rt.Policy(ctx, s.Tenant, s.Policy.Name)
	s.Policy = policy
	if !s.Shadow && (err != nil || (s.Policy.VerifyBeforeReturn() && req.RequestType != schemas.ChatCompletionRequest)) {
		s.Decision = string(decide.FailClosed)
		return req, &schemas.LLMPluginShortCircuit{Error: runtime.Fail()}, nil
	}
	// The HTTP transport decodes this cache type before the LLM hooks.
	// Verifier-originated retries and realtime chat never use the answer cache.
	if s.BypassCache && !s.Shadow {
		// A negative TTL only affects writes. Use a dedicated context flag
		// honoured by the pinned semantic-cache integration for read/write bypass.
		ctx.SetValue(runtime.NoCacheKey, true)
	}
	return req, nil, nil
}

// PostLLMHook handles cache miss (verify/ingest) and cache hit (decision engine).
func (p *Plugin) PostLLMHook(ctx *schemas.BifrostContext, resp *schemas.BifrostResponse, bifrostErr *schemas.BifrostError) (*schemas.BifrostResponse, *schemas.BifrostError, error) {
	s := runtime.Get(ctx)
	if s == nil || s.Skip {
		return resp, bifrostErr, nil
	}

	if bifrostErr != nil {
		return resp, bifrostErr, nil
	}
	if !s.Shadow && s.Policy.VerifyBeforeReturn() && (resp == nil || resp.ChatResponse == nil || len(resp.ChatResponse.Choices) != 1) {
		s.Decision = string(decide.FailClosed)
		return nil, runtime.Fail(), nil
	}

	text := runtime.Text(resp)
	if text == "" {
		if !s.Shadow && s.Policy.VerifyBeforeReturn() {
			s.Decision = string(decide.FailClosed)
			return nil, runtime.Fail(), nil
		}
		return resp, nil, nil
	}

	cacheHit, cacheID := isCacheHit(ctx, resp)
	s.Cache = cacheID

	if cacheHit && cacheID != "" {
		return p.handleHit(ctx, s, resp, cacheID)
	}

	return p.handleMiss(ctx, s, resp, cacheID)
}

// handleMiss processes a provider-generated response (cache miss).
func (p *Plugin) handleMiss(ctx *schemas.BifrostContext, s *runtime.State, res *schemas.BifrostResponse, cacheID string) (*schemas.BifrostResponse, *schemas.BifrostError, error) {
	text := runtime.Text(res)
	if text == "" {
		return res, nil, nil
	}

	if !s.Shadow && s.Policy.VerifyBeforeReturn() {
		// Strict: inline verification - block until claims are scored.
		if err := p.rt.Verify(ctx, s, res, cacheID); err != nil {
			log.Printf("[cg-front] inline verify failed: %v", err)
			s.Decision = "fail_closed"
			s.Annotation = map[string]any{
				"status": "failed", "decision": "fail_closed",
				"reason": "verification_failed",
			}
			return nil, runtime.Fail(), nil
		}
		return res, nil, nil
	}

	// Standard/lenient: async ingest.
	if s.Shadow {
		s.ShadowDecision = "observe"
		s.ShadowReason = "miss"
	}
	payload := runtime.Payload(s, text, cacheID)
	// Queue the durable job before returning a receipt. Evidence verification
	// stays off the miss path for asynchronous policies.
	enqueueCtx, cancel := context.WithTimeout(ctx, 350*time.Millisecond)
	defer cancel()
	var queued runtime.Result
	if err := p.rt.Verifier.Post(enqueueCtx, "/internal/v1/ingest", payload, &queued); err != nil {
		log.Printf("[cg-front] ingest unavailable: %v", err)
	} else if queued.ResponseID != "" {
		s.Annotation = map[string]any{"response_id": queued.ResponseID, "status": "pending"}
	}
	s.Decision = "passthrough"
	return res, nil, nil
}

// handleHit processes a cache-served response.
func (p *Plugin) handleHit(ctx *schemas.BifrostContext, s *runtime.State, res *schemas.BifrostResponse, cacheID string) (*schemas.BifrostResponse, *schemas.BifrostError, error) {
	now, clockErr := p.rt.Now(ctx, s.Tenant)

	// Load manifest from Redis.
	m, err := p.rt.Load(ctx, s.Tenant, cacheID)
	if err != nil || clockErr != nil || m.ContentHash != fmt.Sprintf("%x", sha256.Sum256([]byte(runtime.Text(res)))) {
		d := decide.Unavailable(s.Policy)
		s.Decision = string(d)
		s.Annotation = map[string]any{"status": "unknown", "reason": "manifest_unavailable"}
		if s.Shadow {
			s.ShadowDecision, s.Decision = string(d), "passthrough"
			p.recordHit(s, cacheID)
			return res, nil, nil
		}
		p.recordHit(s, cacheID)
		if d == decide.FailClosed {
			return nil, runtime.Fail(), nil
		}
		return res, nil, nil
	}

	d := decide.Decide(m, s.Policy, now)
	if s.GuardEnabled && s.Prompt != "" {
		if cached, ok := guard.Decode(m.QuerySignature); ok {
			s.GuardTripped, s.GuardReason = guard.Check(guard.Extract(s.Prompt), cached)
		} else if m.PromptText != "" {
			s.GuardTripped, s.GuardReason = guard.Check(guard.Extract(s.Prompt), guard.Extract(m.PromptText))
		} else {
			s.GuardTripped, s.GuardReason = true, "missing_signature"
		}
	}
	if s.Shadow {
		s.ShadowDecision, s.Decision = string(d), "passthrough"
		if s.GuardTripped {
			s.ShadowDecision = "guard_bypass"
		}
		s.ShadowReason = "shadow_mode_evaluation"
		if m.Status == "stale" {
			s.ShadowReason = "known_stale"
		}
		s.Annotation = manifestAnnotation(m, "shadow_passthrough")
		p.recordHit(s, cacheID)
		return res, nil, nil
	}
	defer p.recordHit(s, cacheID)
	if s.GuardTripped {
		return p.revalidate(ctx, s, res, cacheID, "guard_bypass", s.Policy.RegenBudgetMS)
	}

	s.Decision = string(d)
	switch d {
	case decide.Serve:
		s.Annotation = manifestAnnotation(m, "serve")
		return res, nil, nil

	case decide.SWR:
		// Stale-while-revalidate: serve immediately, revalidate async.
		s.Annotation = manifestAnnotation(m, "serve_swr")
		go func() {
			bgCtx, cancel := context.WithTimeout(context.Background(), time.Duration(s.Policy.RevalidateBudgetMS)*time.Millisecond)
			defer cancel()
			payload := map[string]any{
				"tenant_id":   s.Tenant,
				"cache_id":    cacheID,
				"policy":      s.Policy.Name,
				"deadline_ms": s.Policy.RevalidateBudgetMS,
				"reason":      "swr",
				"force":       false,
			}
			_ = p.rt.Verifier.Post(bgCtx, "/internal/v1/revalidate", payload, nil)
		}()
		return res, nil, nil

	case decide.Blocking:
		return p.revalidate(ctx, s, res, cacheID, "blocking_revalidation", s.Policy.RegenBudgetMS)

	case decide.Regenerate:
		return p.revalidate(ctx, s, res, cacheID, "evict_regen", s.Policy.RegenBudgetMS)

	case decide.EvictLazy:
		s.Annotation = manifestAnnotation(m, "evict_lazy")
		go func() {
			bgCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			payload := map[string]any{
				"tenant_id":   s.Tenant,
				"cache_id":    cacheID,
				"policy":      s.Policy.Name,
				"deadline_ms": 10000,
				"reason":      "lazy_eviction",
				"force":       true,
			}
			_ = p.rt.Verifier.Post(bgCtx, "/internal/v1/revalidate", payload, nil)
		}()
		return nil, runtime.Fail(), nil

	case decide.FailClosed:
		s.Annotation = map[string]any{"status": "blocked", "decision": "fail_closed", "reason": "policy_strict"}
		return nil, runtime.Fail(), nil

	case decide.FailOpen:
		s.Annotation = manifestAnnotation(m, "fail_open")
		return res, nil, nil
	}

	return res, nil, nil
}

func (p *Plugin) revalidate(ctx context.Context, s *runtime.State, res *schemas.BifrostResponse, cacheID, reason string, budget int) (*schemas.BifrostResponse, *schemas.BifrostError, error) {
	deadline, cancel := context.WithTimeout(ctx, time.Duration(budget)*time.Millisecond)
	defer cancel()
	payload := map[string]any{
		"tenant_id": s.Tenant, "cache_id": cacheID, "policy": s.Policy.Name,
		"deadline_ms": budget, "reason": reason, "chat": s.Chat,
	}
	var result runtime.Result
	err := p.rt.Verifier.Post(deadline, "/internal/v1/revalidate", payload, &result)
	if err == nil && result.Status == "complete" && runtime.SafeAnnotation(result.Annotation) {
		if result.Decision == "serve" && reason != "guard_bypass" {
			s.Decision, s.Annotation = result.Decision, result.Annotation
			return res, nil, nil
		}
		if result.Replacement != nil && strings.TrimSpace(result.Replacement.Text) != "" &&
			(result.Decision == "regenerated" || result.Decision == "guard_bypass") {
			runtime.Replace(res, result.Replacement)
			s.Decision, s.Annotation = result.Decision, result.Annotation
			return res, nil, nil
		}
	}
	s.Decision = string(decide.FailClosed)
	s.Annotation = map[string]any{"status": "unverified", "reason": reason}
	return nil, runtime.Fail(), nil
}

func (p *Plugin) recordHit(s *runtime.State, cacheID string) {
	payload := map[string]any{
		"tenant_id": s.Tenant, "request_id": s.ID, "cache_id": cacheID, "model_id": s.Model,
		"policy": s.Policy.Name, "prompt_class": s.Class, "decision": s.Decision,
		"guard_tripped": s.GuardTripped, "guard_reason": s.GuardReason,
		"query_signature": s.QuerySignature, "latency_ms": time.Since(s.Started).Milliseconds(),
	}
	if s.Shadow {
		payload["decision_shadow"], payload["shadow_reason"] = s.ShadowDecision, s.ShadowReason
	}
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		if err := p.rt.Verifier.Post(ctx, "/internal/v1/record-hit", payload, nil); err != nil {
			log.Printf("[cg-front] record hit failed: %v", err)
		}
	}()
}

// HTTPTransportResponseHeadersHook sets x-cg-* response headers on the HTTP transport.
func (p *Plugin) HTTPTransportResponseHeadersHook(ctx *schemas.BifrostContext, req *schemas.HTTPRequest, resp *schemas.HTTPResponseMetadata) error {
	s := runtime.Get(ctx)
	if s == nil || s.Skip || resp == nil {
		return nil
	}

	if resp.Headers == nil {
		resp.Headers = make(map[string]string)
	}

	resp.Headers["x-cg-request-id"] = s.ID
	resp.Headers["x-cg-decision"] = s.Decision
	resp.Headers["x-cg-prompt-class"] = s.Class
	resp.Headers["x-cg-policy"] = s.Policy.Name

	if s.Annotation != nil {
		if status, ok := s.Annotation["status"].(string); ok {
			resp.Headers["x-cg-status"] = status
		}
		if freshness, ok := s.Annotation["min_freshness"]; ok && freshness != nil {
			if f, ok := freshness.(float64); ok {
				resp.Headers["x-cg-freshness"] = json.Number(strings.TrimRight(strings.TrimRight(
					func() string { b, _ := json.Marshal(f); return string(b) }(), "0"), ".")).String()
			}
		}
	}

	if s.Cache != "" {
		resp.Headers["x-cg-cache-id"] = s.Cache
	}
	if id, ok := s.Annotation["response_id"].(string); ok {
		resp.Headers["x-cg-response-id"] = id
	}

	if s.Shadow {
		resp.Headers["x-cg-shadow"] = "1"
		if s.ShadowDecision != "" {
			resp.Headers["x-cg-decision-shadow"] = s.ShadowDecision
		}
	}

	if s.GuardTripped {
		resp.Headers["x-cg-guard"] = fmt.Sprintf("tripped; reason=%s", s.GuardReason)
		if s.Decision == "guard_bypass" {
			resp.Headers["x-bf-cache-bypass"] = "1"
		}
	} else if s.GuardEnabled {
		resp.Headers["x-cg-guard"] = "pass"
	}

	return nil
}

// HTTPTransportPostHook ensures response headers are applied on completed HTTP responses.
func (p *Plugin) HTTPTransportPostHook(ctx *schemas.BifrostContext, req *schemas.HTTPRequest, resp *schemas.HTTPResponse) error {
	s := runtime.Get(ctx)
	if s == nil || s.Skip || resp == nil {
		return nil
	}

	if resp.Headers == nil {
		resp.Headers = make(map[string]string)
	}

	if _, ok := resp.Headers["x-cg-request-id"]; !ok {
		resp.Headers["x-cg-request-id"] = s.ID
		resp.Headers["x-cg-decision"] = s.Decision
		resp.Headers["x-cg-prompt-class"] = s.Class
		resp.Headers["x-cg-policy"] = s.Policy.Name
		if s.Cache != "" {
			resp.Headers["x-cg-cache-id"] = s.Cache
		}
		if s.GuardTripped {
			resp.Headers["x-cg-guard"] = fmt.Sprintf("tripped; reason=%s", s.GuardReason)
			if s.Decision == "guard_bypass" {
				resp.Headers["x-bf-cache-bypass"] = "1"
			}
		} else if s.GuardEnabled {
			resp.Headers["x-cg-guard"] = "pass"
		}
	}

	return nil
}

// HTTPTransportStreamChunkHook passes stream chunks through.
func (p *Plugin) HTTPTransportStreamChunkHook(ctx *schemas.BifrostContext, req *schemas.HTTPRequest, chunk *schemas.BifrostStreamChunk) (*schemas.BifrostStreamChunk, error) {
	return chunk, nil
}

// Cleanup cleans up the runtime.
func (p *Plugin) Cleanup() error {
	return p.rt.Cleanup()
}

// Helpers

func lastUserMessage(req *schemas.BifrostRequest) string {
	if req == nil || req.ChatRequest == nil {
		return ""
	}
	for i := len(req.ChatRequest.Input) - 1; i >= 0; i-- {
		msg := req.ChatRequest.Input[i]
		if msg.Role == "user" && msg.Content != nil && msg.Content.ContentStr != nil {
			return *msg.Content.ContentStr
		}
	}
	return ""
}

func extractMessages(req *schemas.BifrostRequest) []map[string]string {
	if req == nil || req.ChatRequest == nil {
		return nil
	}
	var msgs []map[string]string
	start := 0
	if len(req.ChatRequest.Input) > 6 {
		start = len(req.ChatRequest.Input) - 6
	}
	for _, msg := range req.ChatRequest.Input[start:] {
		content := ""
		if msg.Content != nil && msg.Content.ContentStr != nil {
			content = *msg.Content.ContentStr
		}
		msgs = append(msgs, map[string]string{"role": string(msg.Role), "content": content})
	}
	return msgs
}

func isCacheHit(ctx *schemas.BifrostContext, res *schemas.BifrostResponse) (bool, string) {
	if cacheMeta, ok := schemas.CacheLookupFromContext(ctx); ok && cacheMeta != nil {
		id := ""
		if cacheMeta.CacheID != nil {
			id = *cacheMeta.CacheID
		}
		return cacheMeta.CacheHit, id
	}
	if res != nil && res.GetExtraFields() != nil && res.GetExtraFields().CacheDebug != nil {
		meta := res.GetExtraFields().CacheDebug
		id := ""
		if meta.CacheID != nil {
			id = *meta.CacheID
		}
		return meta.CacheHit, id
	}
	return false, ""
}

func manifestAnnotation(m *manifest.Manifest, decision string) map[string]any {
	if m == nil {
		return map[string]any{"status": "unknown", "decision": decision}
	}
	claims := make([]map[string]any, 0, len(m.Claims))
	for _, c := range m.Claims {
		item := map[string]any{
			"claim_id": c.ID,
			"fact_key": c.FactKey,
			"class":    c.Class,
			"text":     c.Text,
			"status":   c.Status,
		}
		if c.Freshness != nil {
			item["freshness"] = *c.Freshness
		}
		claims = append(claims, item)
	}
	var minFreshness *float64
	for _, c := range m.Claims {
		if c.Freshness != nil && c.Status != "skipped" {
			if minFreshness == nil || *c.Freshness < *minFreshness {
				minFreshness = c.Freshness
			}
		}
	}
	annotation := map[string]any{
		"status":        m.Status,
		"decision":      decision,
		"cache":         "hit",
		"response_id":   m.ResponseID,
		"best_before":   m.BestBefore,
		"min_freshness": minFreshness,
		"claims":        claims,
	}
	return annotation
}
