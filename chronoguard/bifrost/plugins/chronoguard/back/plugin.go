// Package back implements the cg-back Bifrost plugin.
//
// cg-back is registered AFTER semantic_cache in the plugin chain. Because
// post-hooks run in reverse order, cg-back's PostLLMHook runs BEFORE
// semantic_cache writes the entry - meaning it only runs when the provider is
// really called (cache miss path).
//
// Responsibilities (per Doc 4 §4.4.1):
//   - PreLLMHook:   inject grounding evidence when x-cg-ground-id is present
//   - PostLLMHook:  tag origin (provider or regenerated)
//   - Cleanup:      close resources
package back

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/chronoguard/chronoguard/internal/runtime"
	"github.com/maximhq/bifrost/core/schemas"
)

// Plugin is the cg-back Bifrost plugin.
type Plugin struct {
	rt *runtime.Runtime
}

// Ensure Plugin implements required interfaces.
var (
	_ schemas.BasePlugin = (*Plugin)(nil)
	_ schemas.LLMPlugin  = (*Plugin)(nil)
)

// New creates the cg-back plugin and initialises shared runtime state.
func New(raw json.RawMessage) (*Plugin, error) {
	var cfg runtime.Config
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
	return "cg-back"
}

// PreRequestHook is a no-op for cg-back.
func (p *Plugin) PreRequestHook(ctx *schemas.BifrostContext, req *schemas.BifrostRequest) error {
	return nil
}

// PreLLMHook intercepts regeneration requests. When cg-front triggers a
// grounded regeneration, the request carries ground-id. cg-back prepends the
// current evidence as a system message so the LLM generates a factually updated answer.
func (p *Plugin) PreLLMHook(ctx *schemas.BifrostContext, req *schemas.BifrostRequest) (*schemas.BifrostRequest, *schemas.LLMPluginShortCircuit, error) {
	s := runtime.Get(ctx)
	if s == nil || s.Skip || req == nil || req.ChatRequest == nil {
		return req, nil, nil
	}

	groundID := s.GroundID
	if groundID == "" {
		return req, nil, nil
	}

	// Load evidence for the stale entry from Redis.
	tenant := runtime.Tenant(ctx, p.rt.Config.SingleTenantID)
	evidence, err := p.loadEvidence(ctx, tenant, groundID)
	if err != nil {
		log.Printf("[cg-back] failed to load grounding evidence for %s: %v", groundID, err)
		return req, nil, nil
	}

	if evidence == "" {
		return req, nil, nil
	}

	evidenceText := fmt.Sprintf(
		"IMPORTANT: The previous answer to this question contained claims that are now outdated. "+
			"Use the following verified evidence to provide an accurate, up-to-date answer. "+
			"Cite the sources where appropriate.\n\n"+
			"--- VERIFIED EVIDENCE ---\n%s\n--- END EVIDENCE ---",
		evidence,
	)

	// Prepend a grounding system message with the evidence.
	groundingMsg := schemas.ChatMessage{
		Role: "system",
		Content: &schemas.ChatMessageContent{
			ContentStr: &evidenceText,
		},
	}

	// Insert grounding as the first message before existing messages.
	req.ChatRequest.Input = append([]schemas.ChatMessage{groundingMsg}, req.ChatRequest.Input...)

	return req, nil, nil
}

// PostLLMHook tags the origin of the response on runtime state.
func (p *Plugin) PostLLMHook(ctx *schemas.BifrostContext, resp *schemas.BifrostResponse, bifrostErr *schemas.BifrostError) (*schemas.BifrostResponse, *schemas.BifrostError, error) {
	s := runtime.Get(ctx)
	if s == nil || s.Skip {
		return resp, bifrostErr, nil
	}

	// Mark origin on state so downstream logging and headers reflect it.
	if s.GroundID != "" {
		s.Decision = "regenerated"
	}

	return resp, bifrostErr, nil
}

// Cleanup closes the Redis connection.
func (p *Plugin) Cleanup() error {
	return p.rt.Cleanup()
}

// loadEvidence retrieves the evidence summary for a stale cache entry from Redis.
func (p *Plugin) loadEvidence(ctx context.Context, tenant, cacheID string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
	defer cancel()

	m, err := p.rt.Load(ctx, tenant, cacheID)
	if err != nil {
		return "", err
	}

	var parts []string
	for _, claim := range m.Claims {
		if claim.Status == "stale" || claim.Status == "due" {
			entry := fmt.Sprintf("- Claim: %q\n  Fact: %s\n  Status: %s",
				claim.Text, claim.FactKey, claim.Status)
			if claim.Freshness != nil {
				entry += fmt.Sprintf("\n  Freshness: %.0f%%", *claim.Freshness)
			}
			parts = append(parts, entry)
		}
	}

	// Also load corrected values from the fact ledger in Redis.
	for _, claim := range m.Claims {
		if claim.FactKey != "" {
			factData, err := p.rt.Redis.HGetAll(ctx, fmt.Sprintf("cg:fact:%s", claim.FactKey)).Result()
			if err == nil && factData["current_value"] != "" {
				parts = append(parts, fmt.Sprintf(
					"- Updated fact (%s): current value is %q (verified at %s)",
					claim.FactKey, factData["current_value"], factData["verified_at"],
				))
			}
		}
	}

	if len(parts) == 0 {
		return "", nil
	}

	result := ""
	for _, part := range parts {
		result += part + "\n\n"
	}
	return result, nil
}
