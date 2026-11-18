package manifest

import (
	"crypto/sha256"
	"encoding/hex"
	"time"
)

type Claim struct {
	ID string `json:"claim_id"`
	FactKey string `json:"fact_key"`
	Class string `json:"class"`
	Text string `json:"text"`
	Status string `json:"status"`
	Freshness *float64 `json:"freshness"`
	NextCheckAt *time.Time `json:"next_check_at"`
}
type Manifest struct {
	Version int `json:"v"`
	Revision int `json:"rev"`
	TenantID string `json:"tenant_id"`
	CacheID string `json:"cache_id"`
	ResponseID string `json:"response_id"`
	PromptText string `json:"prompt_text,omitempty"`
	QuerySignature string `json:"query_signature,omitempty"`
	Status string `json:"status"`
	BestBefore *time.Time `json:"best_before"`
	HardExpiry *time.Time `json:"hard_expiry"`
	Claims []Claim `json:"claims"`
}

// Key is shared with the verifier. Neither raw caller identity nor untrusted
// separators become Redis key syntax.
func Key(tenant, kind, identity string) string {
	t := sha256.Sum256([]byte(tenant))
	i := sha256.Sum256([]byte(identity))
	return "cg:" + hex.EncodeToString(t[:])[:24] + ":" + kind + ":" + hex.EncodeToString(i[:])
}
