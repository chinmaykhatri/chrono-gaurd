package front

import (
	"testing"

	"github.com/chronoguard/chronoguard/internal/decide"
	"github.com/chronoguard/chronoguard/internal/manifest"
	"github.com/chronoguard/chronoguard/internal/runtime"
	"github.com/maximhq/bifrost/core/schemas"
)

func TestManifestAnnotation(t *testing.T) {
	f := float64(92)
	m := &manifest.Manifest{
		Version:    1,
		Revision:   1,
		Status:     "fresh",
		ResponseID: "resp-1",
		Claims: []manifest.Claim{
			{ID: "c1", FactKey: "sw:react:latest_version", Class: "software_versions", Text: "React 18", Status: "fresh", Freshness: &f},
		},
	}
	ann := manifestAnnotation(m, "serve")
	if ann["status"] != "fresh" {
		t.Fatalf("expected status fresh, got %v", ann["status"])
	}
	if ann["decision"] != "serve" {
		t.Fatalf("expected decision serve, got %v", ann["decision"])
	}
	if ann["cache"] != "hit" {
		t.Fatalf("expected cache hit, got %v", ann["cache"])
	}
	claims, ok := ann["claims"].([]map[string]any)
	if !ok || len(claims) != 1 {
		t.Fatal("expected 1 claim")
	}
	if claims[0]["freshness"] != float64(92) {
		t.Fatalf("expected freshness 92, got %v", claims[0]["freshness"])
	}
}

func TestClassifyFromLastUserMessage(t *testing.T) {
	content := "What is the latest version of React?"
	req := &schemas.BifrostRequest{
		ChatRequest: &schemas.BifrostChatRequest{
			Model: "gpt-4o",
			Input: []schemas.ChatMessage{
				{Role: "user", Content: &schemas.ChatMessageContent{ContentStr: &content}},
			},
		},
	}
	text := lastUserMessage(req)
	if text == "" {
		t.Fatal("expected non-empty user message")
	}
	if text != content {
		t.Fatalf("expected %q, got %q", content, text)
	}
}

func TestExtractMessages(t *testing.T) {
	content := "Hello"
	req := &schemas.BifrostRequest{
		ChatRequest: &schemas.BifrostChatRequest{
			Input: []schemas.ChatMessage{
				{Role: "user", Content: &schemas.ChatMessageContent{ContentStr: &content}},
			},
		},
	}
	msgs := extractMessages(req)
	if len(msgs) != 1 {
		t.Fatalf("expected 1 message, got %d", len(msgs))
	}
	if msgs[0]["role"] != "user" || msgs[0]["content"] != "Hello" {
		t.Fatalf("unexpected message: %v", msgs[0])
	}
}

func TestNilManifestAnnotation(t *testing.T) {
	ann := manifestAnnotation(nil, "fail_open")
	if ann["status"] != "unknown" {
		t.Fatal("nil manifest should produce unknown status")
	}
}

func TestShadowModeHeaders(t *testing.T) {
	s := &runtime.State{
		ID:             "req-test-1",
		Decision:       "passthrough",
		Class:          "software_versions",
		Shadow:         true,
		ShadowDecision: "evict_regen",
		Policy:         decide.Default("standard"),
	}
	ctx := &schemas.BifrostContext{}
	ctx.SetValue(runtime.StateKey, s)
	p := &Plugin{}
	resp := &schemas.HTTPResponseMetadata{
		Headers: make(map[string]string),
	}
	err := p.HTTPTransportResponseHeadersHook(ctx, nil, resp)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.Headers["x-cg-shadow"] != "1" {
		t.Fatalf("expected x-cg-shadow=1, got %v", resp.Headers["x-cg-shadow"])
	}
	if resp.Headers["x-cg-decision-shadow"] != "evict_regen" {
		t.Fatalf("expected x-cg-decision-shadow=evict_regen, got %v", resp.Headers["x-cg-decision-shadow"])
	}
	if resp.Headers["x-cg-decision"] != "passthrough" {
		t.Fatalf("expected x-cg-decision=passthrough, got %v", resp.Headers["x-cg-decision"])
	}
}

func TestSemanticHitGuardHeaders(t *testing.T) {
	s := &runtime.State{
		ID:           "req-guard-1",
		Decision:     "guard_bypass",
		Class:        "slow_facts",
		GuardEnabled: true,
		GuardTripped: true,
		GuardReason:  "entity_mismatch",
		Policy:       decide.Default("standard"),
	}
	ctx := &schemas.BifrostContext{}
	ctx.SetValue(runtime.StateKey, s)
	p := &Plugin{}
	resp := &schemas.HTTPResponseMetadata{
		Headers: make(map[string]string),
	}
	err := p.HTTPTransportResponseHeadersHook(ctx, nil, resp)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.Headers["x-cg-guard"] != "tripped; reason=entity_mismatch" {
		t.Fatalf("expected x-cg-guard=tripped; reason=entity_mismatch, got %v", resp.Headers["x-cg-guard"])
	}
	if resp.Headers["x-bf-cache-bypass"] != "1" {
		t.Fatalf("expected x-bf-cache-bypass=1, got %v", resp.Headers["x-bf-cache-bypass"])
	}
	if resp.Headers["x-cg-decision"] != "guard_bypass" {
		t.Fatalf("expected x-cg-decision=guard_bypass, got %v", resp.Headers["x-cg-decision"])
	}
}

func BenchmarkManifestAnnotation(b *testing.B) {
	f := float64(85)
	m := &manifest.Manifest{
		Status:     "fresh",
		ResponseID: "r1",
		Claims: []manifest.Claim{
			{ID: "c1", Status: "fresh", Freshness: &f, Class: "software_versions"},
			{ID: "c2", Status: "fresh", Freshness: &f, Class: "pricing_plans"},
			{ID: "c3", Status: "skipped", Class: "static"},
		},
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_ = manifestAnnotation(m, "serve")
	}
}
