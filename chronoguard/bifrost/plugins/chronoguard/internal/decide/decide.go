// Package decide implements the side-effect-free cache safety policy.
package decide

import (
	"time"
	"github.com/chronoguard/chronoguard/internal/manifest"
)

type Decision string
const (
	Serve Decision = "serve"
	SWR Decision = "serve_swr"
	Blocking Decision = "revalidate_blocking"
	Regenerate Decision = "evict_regen"
	EvictLazy Decision = "evict_lazy"
	FailOpen Decision = "fail_open"
	FailClosed Decision = "fail_closed"
)
type Policy struct {
	Name string `json:"name"`
	Strictness string `json:"strictness"`
	OnUnverifiable string `json:"on_unverifiable"`
	RegenOnStale bool `json:"regen_on_stale"`
	BlockingBudgetMS int `json:"blocking_budget_ms"`
	RevalidateBudgetMS int `json:"revalidate_budget_ms"`
}
func Default(name string) Policy {
	switch name {
	case "strict": return Policy{name, "strict", "fail_closed", true, 4500, 3000}
	case "lenient": return Policy{name, "lenient", "serve_annotated", false, 4500, 3000}
	default: return Policy{"standard", "standard", "serve_annotated", true, 4500, 3000}
	}
}
func Unavailable(p Policy) Decision {
	if p.Strictness == "strict" || p.OnUnverifiable == "fail_closed" { return FailClosed }
	return FailOpen
}
func Decide(m *manifest.Manifest, p Policy, now time.Time) Decision {
	if m == nil { if p.Strictness == "strict" { return Blocking }; return FailOpen }
	stale, due, uncertain := m.Status == "stale" || m.Status == "evicted", m.Status == "due", m.Status == "unverified"
	if m.BestBefore != nil && !now.Before(*m.BestBefore) { due = true }
	if m.HardExpiry != nil && !now.Before(*m.HardExpiry) { stale = true }
	for _, c := range m.Claims {
		switch c.Status {
		case "stale": stale = true
		case "due": due = true
		case "skipped": continue
		case "fresh":
			if c.Class != "static" && c.NextCheckAt == nil { uncertain = true }
		default: uncertain = true
		}
		if c.NextCheckAt != nil && !now.Before(*c.NextCheckAt) { due = true }
	}
	if stale { if p.Strictness == "strict" || p.RegenOnStale { return Regenerate }; return EvictLazy }
	if uncertain { if p.Strictness == "strict" { return Blocking }; return FailOpen }
	if due { if p.Strictness == "strict" { return Blocking }; return SWR }
	if m.Status != "fresh" { return Unavailable(p) }
	return Serve
}
