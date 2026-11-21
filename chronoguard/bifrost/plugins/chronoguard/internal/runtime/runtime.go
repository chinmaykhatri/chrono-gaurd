// Package runtime provides shared, explicitly authenticated plugin state.
package runtime

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/chronoguard/chronoguard/internal/decide"
	"github.com/chronoguard/chronoguard/internal/manifest"
	"github.com/chronoguard/chronoguard/internal/verifierclient"
	"github.com/maximhq/bifrost/core/schemas"
	"github.com/redis/go-redis/v9"
)

type Config struct {
	RedisURL            string `json:"redis_url"`
	VerifierURL         string `json:"verifier_url"`
	InternalKeyEnv      string `json:"internal_key_env"`
	InternalKey         string `json:"internal_key"`
	DefaultPolicy       string `json:"default_policy"`
	SingleTenantID      string `json:"single_tenant_id"`
	Enabled             bool   `json:"enabled"`
	ShadowEnabled       bool   `json:"shadow_enabled"`
	GuardEnabled        bool   `json:"guard_enabled"`
	AllowSimulatedClock bool   `json:"allow_simulated_clock"`
	AllowShadowHeader   bool   `json:"allow_shadow_header"`
}
type State struct {
	ID, Tenant, Class, Model                                             string
	Policy                                                               decide.Policy
	Internal, Skip, Stream, Verified, Shadow, GuardEnabled, GuardTripped bool
	ShadowDecision, ShadowReason, GuardReason                            string
	Prompt, QuerySignature                                               string
	Messages                                                             []map[string]string
	Annotation                                                           map[string]any
	Decision                                                             string
	Cache                                                                string
	GroundID                                                             string
	Chat                                                                 json.RawMessage
	BypassCache                                                          bool
	Started                                                              time.Time
}

const StateKey schemas.BifrostContextKey = "chronoguard.state"
const NoCacheKey schemas.BifrostContextKey = "chronoguard.cache-disabled"

type Runtime struct {
	Config   Config
	Key      string
	Redis    *redis.Client
	Verifier *verifierclient.Client
}

func New(cfg Config) (*Runtime, error) {
	if cfg.RedisURL == "" {
		cfg.RedisURL = os.Getenv("CG_REDIS_URL")
	}
	if cfg.VerifierURL == "" {
		cfg.VerifierURL = os.Getenv("CG_VERIFIER_URL")
	}
	if cfg.DefaultPolicy == "" {
		cfg.DefaultPolicy = os.Getenv("CG_DEFAULT_POLICY")
	}
	allowClock, _ := strconv.ParseBool(os.Getenv("CG_ALLOW_SIMULATED_CLOCK"))
	cfg.AllowSimulatedClock = cfg.AllowSimulatedClock || allowClock
	guard, _ := strconv.ParseBool(os.Getenv("CG_GUARD_ENABLED"))
	cfg.GuardEnabled = cfg.GuardEnabled || guard
	shadow, _ := strconv.ParseBool(os.Getenv("CG_SHADOW_ENABLED"))
	cfg.ShadowEnabled = cfg.ShadowEnabled || shadow
	allowShadowHeader, _ := strconv.ParseBool(os.Getenv("CG_ALLOW_SHADOW_HEADER"))
	cfg.AllowShadowHeader = cfg.AllowShadowHeader || allowShadowHeader
	key := cfg.InternalKey
	if key == "" {
		if cfg.InternalKeyEnv == "" {
			cfg.InternalKeyEnv = "CG_INTERNAL_KEY"
		}
		key = os.Getenv(cfg.InternalKeyEnv)
	}
	c, err := verifierclient.New(cfg.VerifierURL, key)
	if err != nil {
		return nil, err
	}
	opts, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		return nil, errors.New("invalid Redis URL")
	}
	opts.DialTimeout = time.Second
	opts.ReadTimeout = 50 * time.Millisecond
	opts.WriteTimeout = 50 * time.Millisecond
	opts.MaxRetries = 0
	return &Runtime{cfg, key, redis.NewClient(opts), c}, nil
}
func (s *Runtime) Cleanup() error { return s.Redis.Close() }
func (r *Runtime) Policy(ctx context.Context, tenant, name string) (decide.Policy, error) {
	policy := decide.Default(name)
	raw, err := r.Redis.Get(ctx, manifest.Key(tenant, "policy", policy.Name)).Bytes()
	if errors.Is(err, redis.Nil) {
		return policy, nil
	}
	if err != nil {
		return policy, err
	}
	if err := json.Unmarshal(raw, &policy); err != nil {
		return decide.Default(name), err
	}
	return policy, nil
}
func Get(ctx *schemas.BifrostContext) *State { s, _ := ctx.Value(StateKey).(*State); return s }
func Trusted(given, want string) bool {
	return len(given) == len(want) && subtle.ConstantTimeCompare([]byte(given), []byte(want)) == 1
}
func NewID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("secure random unavailable")
	}
	b[6] = (b[6] & 15) | 64
	b[8] = (b[8] & 63) | 128
	h := hex.EncodeToString(b[:])
	return h[:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:]
}
func Tenant(ctx *schemas.BifrostContext, fallback string) string {
	if grant := ctx.Grant(); grant != nil {
		if identity := grant.Identity(); identity != nil {
			if vk := identity.VirtualKey(); vk != nil && vk.ID != "" {
				return "vk:" + vk.ID
			}
			if user := identity.User(); user != nil && user.ID != "" {
				return "user:" + user.ID
			}
		}
	}
	if fallback == "" {
		return "default"
	}
	return fallback
}
func (r *Runtime) Load(ctx context.Context, tenant, id string) (*manifest.Manifest, error) {
	b, err := r.Redis.Get(ctx, manifest.Key(tenant, "manifest", id)).Bytes()
	if err != nil {
		return nil, err
	}
	var m manifest.Manifest
	if err = json.Unmarshal(b, &m); err != nil {
		return nil, err
	}
	if m.TenantID != tenant || m.CacheID != id || m.Version != 1 {
		return nil, errors.New("manifest identity or version mismatch")
	}
	return &m, nil
}
func (r *Runtime) Now(ctx context.Context, tenant string) (time.Time, error) {
	now := time.Now().UTC()
	if !r.Config.AllowSimulatedClock {
		return now, nil
	}
	raw, err := r.Redis.Get(ctx, manifest.Key(tenant, "clock", "")).Bytes()
	if errors.Is(err, redis.Nil) {
		return now, nil
	}
	if err != nil {
		return time.Time{}, err
	}
	var clock struct {
		Mode          string     `json:"mode"`
		OffsetSeconds int64      `json:"offset_seconds"`
		FrozenAt      *time.Time `json:"frozen_at"`
	}
	if err := json.Unmarshal(raw, &clock); err != nil {
		return time.Time{}, err
	}
	switch clock.Mode {
	case "real":
		return now, nil
	case "simulated":
		return now.Add(time.Duration(clock.OffsetSeconds) * time.Second), nil
	case "frozen":
		if clock.FrozenAt != nil {
			return *clock.FrozenAt, nil
		}
	}
	return time.Time{}, errors.New("invalid clock state")
}
func Text(res *schemas.BifrostResponse) string {
	if res == nil || res.ChatResponse == nil || len(res.ChatResponse.Choices) == 0 {
		return ""
	}
	c := res.ChatResponse.Choices[0]
	if c.ChatNonStreamResponseChoice == nil || c.Message == nil || c.Message.Content == nil || c.Message.Content.ContentStr == nil {
		return ""
	}
	return *c.Message.Content.ContentStr
}
func Replace(res *schemas.BifrostResponse, replacement *Replacement) {
	if res == nil || res.ChatResponse == nil || len(res.ChatResponse.Choices) == 0 {
		return
	}
	c := &res.ChatResponse.Choices[0]
	if c.ChatNonStreamResponseChoice == nil || c.Message == nil {
		return
	}
	c.Message.Content = &schemas.ChatMessageContent{ContentStr: &replacement.Text}
	res.ChatResponse.ID = replacement.ID
	res.ChatResponse.Model = replacement.Model
	res.ChatResponse.Created = replacement.Created
	res.ChatResponse.Usage = replacement.Usage
	res.ChatResponse.SystemFingerprint = ""
}
func Fail() *schemas.BifrostError {
	code := "chronoguard_unverifiable"
	status := 503
	fallback := false
	return &schemas.BifrostError{IsBifrostError: true, StatusCode: &status, AllowFallbacks: &fallback, Error: &schemas.ErrorField{Code: &code, Message: "ChronoGuard could not verify this response within the configured policy."}}
}
func HTTPFail(status int, message string) *schemas.HTTPResponse {
	b, _ := json.Marshal(map[string]any{"error": map[string]string{"code": "chronoguard_unverifiable", "message": message}})
	return &schemas.HTTPResponse{StatusCode: status, Headers: map[string]string{"Content-Type": "application/json"}, Body: b}
}
func Payload(s *State, text, cacheID string) map[string]any {
	var id any
	if cacheID != "" {
		id = cacheID
	}
	m := map[string]any{"request_id": s.ID, "tenant_id": s.Tenant, "cache_id": id, "origin": "provider", "model_id": s.Model, "messages": s.Messages, "prompt_text": s.Prompt, "query_signature": s.QuerySignature, "response_text": text, "prompt_class": s.Class, "policy": s.Policy.Name, "usage": map[string]int{"input_tokens": 0, "output_tokens": 0}}
	if s.Shadow {
		m["decision_shadow"] = s.ShadowDecision
		m["shadow_reason"] = s.ShadowReason
	}
	if s.GuardTripped {
		m["guard_tripped"] = true
		m["guard_reason"] = s.GuardReason
	}
	return m
}

type Result struct {
	ResponseID  string         `json:"response_id"`
	Status      string         `json:"status"`
	Decision    string         `json:"decision"`
	Annotation  map[string]any `json:"annotation"`
	Replacement *Replacement   `json:"replacement"`
}

type Replacement struct {
	Text    string                   `json:"text"`
	ID      string                   `json:"id"`
	Model   string                   `json:"model"`
	Created int                      `json:"created"`
	Usage   *schemas.BifrostLLMUsage `json:"usage"`
}

func SafeAnnotation(a map[string]any) bool {
	if a == nil {
		return false
	}
	if status, _ := a["status"].(string); status != "complete" {
		return false
	}
	claims, ok := a["claims"].([]any)
	if !ok {
		return false
	}
	for _, item := range claims {
		c, ok := item.(map[string]any)
		if !ok {
			return false
		}
		s, _ := c["status"].(string)
		if s != "fresh" && s != "skipped" {
			return false
		}
	}
	return true
}
func (r *Runtime) Verify(ctx context.Context, s *State, res *schemas.BifrostResponse, cacheID string) error {
	text := Text(res)
	if text == "" {
		return errors.New("unsupported response")
	}
	payload := Payload(s, text, cacheID)
	payload["deadline_ms"] = s.Policy.BlockingBudgetMS
	payload["chat"] = s.Chat
	deadline, cancel := context.WithTimeout(ctx, time.Duration(s.Policy.BlockingBudgetMS+s.Policy.RegenBudgetMS)*time.Millisecond)
	defer cancel()
	var out Result
	if err := r.Verifier.Post(deadline, "/internal/v1/verify-inline", payload, &out); err != nil {
		return err
	}
	s.Annotation = out.Annotation
	if s.Policy.VerifyBeforeReturn() && (out.Status != "complete" || !SafeAnnotation(out.Annotation)) {
		return errors.New("verification incomplete")
	}
	s.Verified = true
	s.Decision = "passthrough"
	if out.Decision == "regenerated" && out.Replacement != nil && strings.TrimSpace(out.Replacement.Text) != "" {
		Replace(res, out.Replacement)
		s.Decision = out.Decision
	}
	return nil
}
func DeleteHeader(headers map[string]string, name string) {
	for k := range headers {
		if strings.EqualFold(k, name) {
			delete(headers, k)
		}
	}
}
