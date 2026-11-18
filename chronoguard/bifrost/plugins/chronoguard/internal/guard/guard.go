package guard

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"
)

// Signature represents the extracted syntactic and entity fingerprint of a query.
type Signature struct {
	Numbers   []string `json:"numbers"`   // Extracted digits, floats, versions
	Years     []string `json:"years"`     // 4-digit years (1900-2099)
	Entities  []string `json:"entities"`  // Capitalized terms, quoted entities
	Polarity  []string `json:"polarity"`  // Temporal and negation tokens
	Relations []string `json:"relations"` // Key relation roles (ceo, founder, capital, etc.)
}

var (
	// Number/Version/Year regex
	numberRegex = regexp.MustCompile(`(?i)\b(v?\d+(?:\.\d+)+|\d{4}|\d+)\b`)

	// Quoted strings regex
	quotedRegex = regexp.MustCompile(`["']([^"']+)["']`)

	// Stop words to exclude from entity candidate extraction (lowercased)
	commonQuestionWords = map[string]bool{
		"what": true, "who": true, "where": true, "when": true, "why": true, "how": true,
		"which": true, "is": true, "are": true, "was": true, "were": true, "can": true,
		"could": true, "would": true, "should": true, "does": true, "do": true, "did": true,
		"has": true, "have": true, "had": true, "will": true, "shall": true, "may": true, "might": true,
		"tell": true, "give": true, "name": true, "find": true, "list": true, "explain": true,
		"show": true, "the": true, "a": true, "an": true, "in": true, "on": true, "at": true,
		"to": true, "for": true, "of": true, "with": true, "by": true, "about": true, "from": true,
	}

	// Polarity & temporal tokens
	polarityWords = map[string]bool{
		"not": true, "never": true, "no": true,
		"former": true, "previous": true, "past": true,
		"current": true, "present": true, "now": true, "currently": true,
		"next": true, "future": true,
		"first": true, "last": true, "latest": true,
		"old": true, "new": true,
	}

	// Opposing polarity pairs
	opposingPolarity = map[string]string{
		"current":   "former",
		"currently": "former",
		"present":   "former",
		"former":    "current",
		"previous":  "current",
		"past":      "current",
		"latest":    "first",
		"new":       "old",
		"old":       "new",
	}

	// Relations
	relationWords = map[string]bool{
		"ceo": true, "founder": true, "founded": true, "founding": true,
		"capital": true, "president": true, "minister": true, "prime": true,
		"city": true, "largest": true, "chancellor": true, "governor": true,
		"mayor": true, "director": true, "chairman": true, "population": true,
		"currency": true, "headquarters": true, "cto": true, "cfo": true,
		"author": true, "creator": true,
	}
)

// Extract parses a prompt and returns its Signature in pure Go (< 100 microseconds).
func Extract(prompt string) Signature {
	sig := Signature{
		Numbers:   make([]string, 0),
		Years:     make([]string, 0),
		Entities:  make([]string, 0),
		Polarity:  make([]string, 0),
		Relations: make([]string, 0),
	}

	trimmed := strings.TrimSpace(prompt)
	if trimmed == "" {
		return sig
	}

	// 1. Extract numbers, versions, years
	rawNumbers := numberRegex.FindAllString(trimmed, -1)
	numSet := make(map[string]bool)
	yearSet := make(map[string]bool)
	for _, n := range rawNumbers {
		lower := strings.ToLower(n)
		if len(lower) == 4 {
			if y, err := strconv.Atoi(lower); err == nil && y >= 1900 && y <= 2099 {
				yearSet[lower] = true
				continue
			}
		}
		numSet[lower] = true
	}
	for y := range yearSet {
		sig.Years = append(sig.Years, y)
	}
	for n := range numSet {
		sig.Numbers = append(sig.Numbers, n)
	}
	sort.Strings(sig.Years)
	sort.Strings(sig.Numbers)

	// 2. Extract quoted terms as entities
	entitySet := make(map[string]bool)
	quotes := quotedRegex.FindAllStringSubmatch(trimmed, -1)
	for _, match := range quotes {
		if len(match) > 1 {
			ent := strings.TrimSpace(match[1])
			if ent != "" {
				entitySet[cleanEntity(ent)] = true
			}
		}
	}

	// 3. Extract tokens, capitalized entities, polarity, relations
	tokens := tokenize(trimmed)
	var currentEntityTokens []string

	for i, token := range tokens {
		lower := strings.ToLower(token)

		// Check polarity
		if polarityWords[lower] {
			sig.Polarity = append(sig.Polarity, lower)
		}

		// Check relation
		if relationWords[lower] {
			sig.Relations = append(sig.Relations, canonicalRelation(lower))
		}

		// Check entity candidate (capitalized word that isn't just a sentence starter, relation, or polarity token)
		isCapitalized := len(token) > 0 && unicode.IsUpper(rune(token[0]))
		isSentenceStarter := (i == 0) && commonQuestionWords[lower]

		if isCapitalized && !isSentenceStarter && !commonQuestionWords[lower] && !relationWords[lower] && !polarityWords[lower] {
			currentEntityTokens = append(currentEntityTokens, token)
		} else {
			if len(currentEntityTokens) > 0 {
				ent := cleanEntity(strings.Join(currentEntityTokens, " "))
				if ent != "" && !commonQuestionWords[strings.ToLower(ent)] {
					entitySet[ent] = true
				}
				currentEntityTokens = nil
			}
		}
	}
	if len(currentEntityTokens) > 0 {
		ent := cleanEntity(strings.Join(currentEntityTokens, " "))
		if ent != "" && !commonQuestionWords[strings.ToLower(ent)] {
			entitySet[ent] = true
		}
	}

	for ent := range entitySet {
		if len(ent) > 1 { // skip single character punctuation/letters
			sig.Entities = append(sig.Entities, ent)
		}
	}
	sort.Strings(sig.Entities)
	sig.Polarity = deduplicateAndSort(sig.Polarity)
	sig.Relations = deduplicateAndSort(sig.Relations)

	return sig
}

// Encode produces a compact canonical string for storage and logging.
func (s Signature) Encode() string {
	parts := make([]string, 0, 5)
	if len(s.Years) > 0 {
		parts = append(parts, "yr:"+strings.Join(s.Years, ","))
	}
	if len(s.Numbers) > 0 {
		parts = append(parts, "num:"+strings.Join(s.Numbers, ","))
	}
	if len(s.Entities) > 0 {
		parts = append(parts, "ent:"+strings.Join(s.Entities, ","))
	}
	if len(s.Polarity) > 0 {
		parts = append(parts, "pol:"+strings.Join(s.Polarity, ","))
	}
	if len(s.Relations) > 0 {
		parts = append(parts, "rel:"+strings.Join(s.Relations, ","))
	}
	return strings.Join(parts, "|")
}

// Check compares an incoming query signature with a cached entry signature.
// Returns tripped=true and a specific reason code if a mismatch is detected.
func Check(incoming, cached Signature) (bool, string) {
	// 1. Year Mismatch
	if !equalSets(incoming.Years, cached.Years) {
		return true, "year_mismatch"
	}

	// 2. Number/Version Mismatch
	if !equalSets(incoming.Numbers, cached.Numbers) {
		return true, "number_mismatch"
	}

	// 3. Polarity Mismatch
	// Check negation presence
	inHasNeg := containsAny(incoming.Polarity, "not", "never", "no")
	caHasNeg := containsAny(cached.Polarity, "not", "never", "no")
	if inHasNeg != caHasNeg {
		return true, "polarity_mismatch"
	}

	// Check opposing polarity (e.g. current vs former)
	for _, inPol := range incoming.Polarity {
		if opp, exists := opposingPolarity[inPol]; exists {
			if contains(cached.Polarity, opp) {
				return true, "polarity_mismatch"
			}
		}
	}
	for _, caPol := range cached.Polarity {
		if opp, exists := opposingPolarity[caPol]; exists {
			if contains(incoming.Polarity, opp) {
				return true, "polarity_mismatch"
			}
		}
	}

	// 4. Entity Mismatch
	// If one has entities and the other has none -> mismatch
	if len(incoming.Entities) > 0 && len(cached.Entities) == 0 {
		return true, "entity_mismatch"
	}
	if len(cached.Entities) > 0 && len(incoming.Entities) == 0 {
		return true, "entity_mismatch"
	}

	// Check that every incoming entity has a corresponding close match in cached
	for _, inEnt := range incoming.Entities {
		if !hasCloseMatch(inEnt, cached.Entities) {
			return true, "entity_mismatch"
		}
	}
	// Check that every cached entity has a corresponding close match in incoming
	for _, caEnt := range cached.Entities {
		if !hasCloseMatch(caEnt, incoming.Entities) {
			return true, "entity_mismatch"
		}
	}

	// 5. Relation Mismatch (e.g., ceo vs founder, capital vs largest city)
	if len(incoming.Relations) > 0 && len(cached.Relations) > 0 {
		sharesCommon := false
		for _, inR := range incoming.Relations {
			if contains(cached.Relations, inR) {
				sharesCommon = true
				break
			}
		}
		if !sharesCommon {
			return true, "relation_mismatch"
		}
	}

	return false, ""
}

// Helpers

func tokenize(s string) []string {
	var tokens []string
	var current strings.Builder
	for _, r := range s {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '.' || r == '-' || r == '\'' {
			current.WriteRune(r)
		} else {
			if current.Len() > 0 {
				tokens = append(tokens, current.String())
				current.Reset()
			}
		}
	}
	if current.Len() > 0 {
		tokens = append(tokens, current.String())
	}
	return tokens
}

func cleanEntity(s string) string {
	s = strings.TrimSpace(s)
	// Strip trailing possessive "'s" or punctuation
	s = strings.TrimSuffix(s, "'s")
	s = strings.TrimSuffix(s, "'")
	s = strings.Trim(s, ".,?!:;\"'")
	return strings.TrimSpace(s)
}

func deduplicateAndSort(items []string) []string {
	seen := make(map[string]bool)
	var res []string
	for _, it := range items {
		if !seen[it] {
			seen[it] = true
			res = append(res, it)
		}
	}
	sort.Strings(res)
	return res
}

func equalSets(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	mA := make(map[string]bool, len(a))
	for _, x := range a {
		mA[x] = true
	}
	for _, x := range b {
		if !mA[x] {
			return false
		}
	}
	return true
}

func contains(slice []string, val string) bool {
	for _, s := range slice {
		if s == val {
			return true
		}
	}
	return false
}

func containsAny(slice []string, targets ...string) bool {
	for _, s := range slice {
		for _, t := range targets {
			if s == t {
				return true
			}
		}
	}
	return false
}

func hasCloseMatch(target string, candidates []string) bool {
	tLower := strings.ToLower(target)
	for _, c := range candidates {
		cLower := strings.ToLower(c)
		if tLower == cLower {
			return true
		}
		d := Levenshtein(tLower, cLower)
		// Typos: edit distance 1 allowed for words length >= 5
		if d <= 1 && len(tLower) >= 5 && len(cLower) >= 5 {
			return true
		}
	}
	return false
}

// Levenshtein computes classic edit distance between two lowercase strings.
func Levenshtein(a, b string) int {
	la := len(a)
	lb := len(b)
	if la == 0 {
		return lb
	}
	if lb == 0 {
		return la
	}

	prev := make([]int, lb+1)
	curr := make([]int, lb+1)

	for j := 0; j <= lb; j++ {
		prev[j] = j
	}

	for i := 1; i <= la; i++ {
		curr[0] = i
		for j := 1; j <= lb; j++ {
			cost := 0
			if a[i-1] != b[j-1] {
				cost = 1
			}
			ins := curr[j-1] + 1
			del := prev[j] + 1
			sub := prev[j-1] + cost
			curr[j] = min(ins, min(del, sub))
		}
		copy(prev, curr)
	}

	return prev[lb]
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func canonicalRelation(r string) string {
	switch r {
	case "founded", "founding":
		return "founder"
	case "presidency":
		return "president"
	default:
		return r
	}
}
