package back

import (
	"context"
	"testing"
	"time"

	"github.com/maximhq/bifrost/core/schemas"
)

func TestBackPluginName(t *testing.T) {
	p := &Plugin{}
	if p.GetName() != "cg-back" {
		t.Fatalf("expected cg-back, got %s", p.GetName())
	}
}

func TestPreRequestHookNoOp(t *testing.T) {
	p := &Plugin{}
	ctx := schemas.NewBifrostContext(context.Background(), time.Time{})
	req := &schemas.BifrostRequest{}
	if err := p.PreRequestHook(ctx, req); err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
}

func TestPreLLMHookWithoutGroundID(t *testing.T) {
	p := &Plugin{}
	ctx := schemas.NewBifrostContext(context.Background(), time.Time{})
	content := "What is Python?"
	req := &schemas.BifrostRequest{
		ChatRequest: &schemas.BifrostChatRequest{
			Model: "gpt-4o",
			Input: []schemas.ChatMessage{
				{Role: "user", Content: &schemas.ChatMessageContent{ContentStr: &content}},
			},
		},
	}
	r, sc, err := p.PreLLMHook(ctx, req)
	if err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
	if sc != nil {
		t.Fatalf("expected nil short circuit, got %v", sc)
	}
	if len(r.ChatRequest.Input) != 1 {
		t.Fatalf("expected 1 message unchanged, got %d", len(r.ChatRequest.Input))
	}
}

func TestPostLLMHookPassThrough(t *testing.T) {
	p := &Plugin{}
	ctx := schemas.NewBifrostContext(context.Background(), time.Time{})
	resp := &schemas.BifrostResponse{}
	outResp, outErr, err := p.PostLLMHook(ctx, resp, nil)
	if err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
	if outErr != nil {
		t.Fatalf("expected nil bifrostErr, got %v", outErr)
	}
	if outResp != resp {
		t.Fatalf("expected same response object")
	}
}
