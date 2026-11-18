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
	var cfg runtime.Config
	if len(raw) > 0 {
		if err := json.Unmarshal(raw, &cfg); err != nil {
			return nil, err
		}
	}
	if !cfg.Enabled {
		cfg.Enabled = true // safe default; kill-switch is checked per request
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

	// Kill switch: x-cg-mode: off bypasses everything.
	if req != nil && strings.EqualFold(req.CaseInsensitiveHeaderLookup("x-cg-mode"), "off") {
		ctx.SetValue(runtime.StateKey, &runtime.State{Skip: true})
		return nil, nil
	}

	s := &runtime.State{
		ID:     runtime.NewID(),
		Tenant: runtime.Tenant(ctx, p.rt.Config.SingleTenantID),
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
		if shadowHeader == "1" || strings.EqualFold(shadowHeader, "true") || p.rt.Config.ShadowEnabled {
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

	if req.ChatRequest != nil {
		s.Model = req.ChatRequest.Model
		s.Messages = extractMessages(req)
		text := lastUserMessage(req)
		s.Prompt = text
		s.QuerySignature = guard.Extract(text).Encode()
		s.Class = classify.Prompt(text)

		// Apply TTL / bypass if classified
		if s.Class == "realtime" {
			s.Skip = true
		}
	}

	return nil
}

// PreLLMHook is called before the provider call.
func (p *Plugin) PreLLMHook(ctx *schemas.BifrostContext, req *schemas.BifrostRequest) (*schemas.BifrostRequest, *schemas.LLMPluginShortCircuit, error) {
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

	text := runtime.Text(resp)
	if text == "" {
		return resp, bifrostErr, nil
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

	if s.Policy.Strictness == "strict" {
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
		s.Decision = "passthrough"
		return res, nil, nil
	}

	// Standard/lenient: async ingest.
	payload := runtime.Payload(s, text, cacheID)
	go func() {
		bgCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := p.rt.Verifier.Post(bgCtx, "/internal/v1/ingest", payload, nil); err != nil {
			log.Printf("[cg-front] async ingest failed: %v", err)
		}
	}()
	s.Decision = "passthrough"
	return res, nil, nil
}

// handleHit processes a cache-served response.
func (p *Plugin) handleHit(ctx *schemas.BifrostContext, s *runtime.State, res *schemas.BifrostResponse, cacheID string) (*schemas.BifrostResponse, *schemas.BifrostError, error) {
	now := p.rt.Now(ctx)

	// Load manifest from Redis.
	m, err := p.rt.Load(ctx, s.Tenant, cacheID)
	if err != nil {
		d := decide.Unavailable(s.Policy)
		s.Decision = string(d)
		if d == decide.FailClosed {
			return nil, runtime.Fail(), nil
		}
		s.Annotation = map[string]any{
			"status": "unknown", "decision": string(d),
			"cache": "hit", "reason": "no_manifest",
		}
		return res, nil, nil
	}

	// Increment hit count asynchronously.
	go func() {
		bgCtx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
		defer cancel()
		p.rt.Redis.HIncrBy(bgCtx, manifest.Key(s.Tenant, "manifest_hits", cacheID), "count", 1)
	}()

	// Semantic Hit Guard: inspect query signature against cached prompt signature
	if s.GuardEnabled && s.Prompt != "" && (m.PromptText != "" || m.QuerySignature != "") {
		inSig := guard.Extract(s.Prompt)
		cachedPrompt := m.PromptText
		cachedSig := guard.Extract(cachedPrompt)
		if tripped, reason := guard.Check(inSig, cachedSig); tripped {
			s.GuardTripped = true
			s.GuardReason = reason
			s.Decision = "guard_bypass"
			s.Annotation = map[string]any{
				"status":        "bypassed",
				"decision":      "guard_bypass",
				"reason":        reason,
				"guard_tripped": true,
			}
			log.Printf("[cg-front] semantic guard tripped: %s (incoming: %q, cached: %q); bypassing cache", reason, s.Prompt, m.PromptText)

			// Bypass cached response: regenerate fresh answer via provider
			payload := map[string]any{
				"tenant_id":   s.Tenant,
				"cache_id":    cacheID,
				"policy":      s.Policy.Name,
				"deadline_ms": s.Policy.BlockingBudgetMS,
				"reason":      "guard_bypass",
				"force":       true,
			}
			deadline, cancel := context.WithTimeout(ctx, time.Duration(s.Policy.BlockingBudgetMS)*time.Millisecond)
			defer cancel()
			var result runtime.Result
			if err := p.rt.Verifier.Post(deadline, "/internal/v1/revalidate", payload, &result); err == nil {
				if result.Replacement != nil && result.Replacement.Text != "" {
					runtime.Replace(res, result.Replacement.Text)
				}
			}

			go func() {
				bgCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
				defer cancel()
				hitPayload := map[string]any{
					"tenant_id":       s.Tenant,
					"request_id":      s.ID,
					"cache_id":        cacheID,
					"origin":          "guard_bypassed",
					"model_id":        s.Model,
					"policy":          s.Policy.Name,
					"prompt_class":    s.Class,
					"cache_status":    "hit",
					"decision":        "guard_bypass",
					"guard_tripped":   true,
					"guard_reason":    s.GuardReason,
					"query_signature": s.QuerySignature,
				}
				_ = p.rt.Verifier.Post(bgCtx, "/internal/v1/record-hit", hitPayload, nil)
			}()

			return res, nil, nil
		}
	}

	// Run pure-Go decision engine.
	d := decide.Decide(m, s.Policy, now)

	if s.Shadow {
		s.ShadowDecision = string(d)
		s.Decision = "passthrough"
		s.ShadowReason = "shadow_mode_evaluation"
		s.Annotation = manifestAnnotation(m, "shadow_passthrough")

		if d == decide.SWR || d == decide.Regenerate || d == decide.EvictLazy || d == decide.Blocking {
			go func() {
				bgCtx, cancel := context.WithTimeout(context.Background(), time.Duration(s.Policy.RevalidateBudgetMS)*time.Millisecond)
				defer cancel()
				payload := map[string]any{
					"tenant_id":   s.Tenant,
					"cache_id":    cacheID,
					"policy":      s.Policy.Name,
					"deadline_ms": s.Policy.RevalidateBudgetMS,
					"reason":      "shadow_revalidation",
					"force":       false,
				}
				_ = p.rt.Verifier.Post(bgCtx, "/internal/v1/revalidate", payload, nil)
			}()
		}

		go func() {
			bgCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			hitPayload := map[string]any{
				"tenant_id":       s.Tenant,
				"request_id":      s.ID,
				"cache_id":        cacheID,
				"origin":          "legacy_cache",
				"model_id":        s.Model,
				"policy":          s.Policy.Name,
				"prompt_class":    s.Class,
				"cache_status":    "hit",
				"decision":        "passthrough",
				"decision_shadow": s.ShadowDecision,
				"shadow_reason":   s.ShadowReason,
			}
			_ = p.rt.Verifier.Post(bgCtx, "/internal/v1/record-hit", hitPayload, nil)
		}()

		return res, nil, nil
	}

	s.Decision = string(d)

	switch d {
	case decide.Serve:
		// Fresh: zero Tavily calls, zero upstream LLM calls.
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
		// Strict revalidation: block and wait.
		payload := map[string]any{
			"tenant_id":   s.Tenant,
			"cache_id":    cacheID,
			"policy":      s.Policy.Name,
			"deadline_ms": s.Policy.BlockingBudgetMS,
			"reason":      "blocking_revalidation",
			"force":       false,
		}
		deadline, cancel := context.WithTimeout(ctx, time.Duration(s.Policy.BlockingBudgetMS)*time.Millisecond)
		defer cancel()
		var result runtime.Result
		if err := p.rt.Verifier.Post(deadline, "/internal/v1/revalidate", payload, &result); err != nil {
			s.Decision = string(decide.FailClosed)
			return nil, runtime.Fail(), nil
		}
		s.Annotation = result.Annotation
		if result.Replacement != nil && result.Replacement.Text != "" {
			runtime.Replace(res, result.Replacement.Text)
		}
		if !runtime.SafeAnnotation(result.Annotation) && s.Policy.Strictness == "strict" {
			s.Decision = string(decide.FailClosed)
			return nil, runtime.Fail(), nil
		}
		s.Decision = result.Decision
		return res, nil, nil

	case decide.Regenerate:
		// Evict and regenerate with current evidence.
		payload := map[string]any{
			"tenant_id":   s.Tenant,
			"cache_id":    cacheID,
			"policy":      s.Policy.Name,
			"deadline_ms": s.Policy.RevalidateBudgetMS,
			"reason":      "evict_regen",
			"force":       true,
		}
		deadline, cancel := context.WithTimeout(ctx, time.Duration(s.Policy.RevalidateBudgetMS)*time.Millisecond)
		defer cancel()
		var result runtime.Result
		if err := p.rt.Verifier.Post(deadline, "/internal/v1/revalidate", payload, &result); err != nil {
			s.Annotation = map[string]any{"status": "failed", "decision": "evict_regen", "reason": "regen_failed"}
			s.Decision = string(decide.FailOpen)
			return res, nil, nil
		}
		if result.Replacement != nil && result.Replacement.Text != "" {
			runtime.Replace(res, result.Replacement.Text)
			s.Decision = "regenerated"
		}
		s.Annotation = result.Annotation
		return res, nil, nil

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
		return res, nil, nil

	case decide.FailClosed:
		s.Annotation = map[string]any{"status": "blocked", "decision": "fail_closed", "reason": "policy_strict"}
		return nil, runtime.Fail(), nil

	case decide.FailOpen:
		s.Annotation = manifestAnnotation(m, "fail_open")
		return res, nil, nil
	}

	return res, nil, nil
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

	if s.Shadow {
		resp.Headers["x-cg-shadow"] = "1"
		if s.ShadowDecision != "" {
			resp.Headers["x-cg-decision-shadow"] = s.ShadowDecision
		}
	}

	if s.GuardTripped {
		resp.Headers["x-cg-guard"] = fmt.Sprintf("tripped; reason=%s", s.GuardReason)
		resp.Headers["x-bf-cache-bypass"] = "1"
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
			resp.Headers["x-bf-cache-bypass"] = "1"
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
	if cacheMeta, ok := schemas.CacheMetadataFromContext(ctx); ok && cacheMeta != nil {
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
