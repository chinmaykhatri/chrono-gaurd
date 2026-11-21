package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/chronoguard/chronoguard/internal/guard"
)

type GuardPair struct {
	ID             string `json:"id"`
	Incoming       string `json:"incoming"`
	Cached         string `json:"cached"`
	Type           string `json:"type"`
	ExpectedTrip   bool   `json:"expected_trip"`
	ExpectedReason string `json:"expected_reason"`
}

type GuardDataset struct {
	Description string      `json:"description"`
	TotalPairs  int         `json:"total_pairs"`
	Pairs       []GuardPair `json:"pairs"`
}

type PairResult struct {
	ID              string  `json:"id"`
	Incoming        string  `json:"incoming"`
	Cached          string  `json:"cached"`
	ExpectedTrip    bool    `json:"expected_trip"`
	PredictedTrip   bool    `json:"predicted_trip"`
	ExpectedReason  string  `json:"expected_reason"`
	PredictedReason string  `json:"predicted_reason"`
	Correct         bool    `json:"correct"`
	LatencyUs       float64 `json:"latency_us"`
}

type GuardReport struct {
	Provenance      string       `json:"provenance"`
	Timestamp       string       `json:"timestamp"`
	TotalPairs      int          `json:"total_pairs"`
	NearMissCount   int          `json:"near_miss_count"`
	ParaphraseCount int          `json:"paraphrase_count"`
	TruePositives   int          `json:"tp"`
	FalsePositives  int          `json:"fp"`
	FalseNegatives  int          `json:"fn"`
	TrueNegatives   int          `json:"tn"`
	Precision       float64      `json:"precision"`
	Recall          float64      `json:"recall"`
	F1              float64      `json:"f1"`
	Accuracy        float64      `json:"accuracy"`
	AvgExtractionUs float64      `json:"avg_extraction_us"`
	AvgCheckUs      float64      `json:"avg_check_us"`
	AvgOverheadUs   float64      `json:"avg_total_overhead_us"`
	BudgetCompliant bool         `json:"budget_compliant_under_100us"`
	Results         []PairResult `json:"results"`
}

func main() {
	pairsPath := flag.String("dataset", "../../../../eval/guard_pairs.json", "Path to guard_pairs.json")
	outPath := flag.String("output", "../../../../eval/reports/guard-eval.json", "Path to write report")
	flag.Parse()

	data, err := os.ReadFile(*pairsPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to read dataset: %v\n", err)
		os.Exit(1)
	}

	var ds GuardDataset
	if err := json.Unmarshal(data, &ds); err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse dataset: %v\n", err)
		os.Exit(1)
	}

	tp, fp, fn, tn := 0, 0, 0, 0
	nearMisses := 0
	paraphrases := 0
	var results []PairResult
	var totalExtractDuration time.Duration
	var totalCheckDuration time.Duration

	// Warmup
	for i := 0; i < 50; i++ {
		_ = guard.Extract("Who was the CEO of Apple in 2010?")
	}

	for _, pair := range ds.Pairs {
		if pair.Type == "near_miss" {
			nearMisses++
		} else {
			paraphrases++
		}

		startEx := time.Now()
		inSig := guard.Extract(pair.Incoming)
		caSig := guard.Extract(pair.Cached)
		extractDur := time.Since(startEx)
		totalExtractDuration += extractDur

		startCk := time.Now()
		tripped, reason := guard.Check(inSig, caSig)
		checkDur := time.Since(startCk)
		totalCheckDuration += checkDur

		pairTotalUs := float64((extractDur + checkDur).Nanoseconds()) / 1000.0

		correct := (tripped == pair.ExpectedTrip)
		if tripped && pair.ExpectedTrip {
			tp++
		} else if tripped && !pair.ExpectedTrip {
			fp++
		} else if !tripped && pair.ExpectedTrip {
			fn++
		} else {
			tn++
		}

		results = append(results, PairResult{
			ID:              pair.ID,
			Incoming:        pair.Incoming,
			Cached:          pair.Cached,
			ExpectedTrip:    pair.ExpectedTrip,
			PredictedTrip:   tripped,
			ExpectedReason:  pair.ExpectedReason,
			PredictedReason: reason,
			Correct:         correct,
			LatencyUs:       round2(pairTotalUs),
		})
	}

	precision := 1.0
	if tp+fp > 0 {
		precision = float64(tp) / float64(tp+fp)
	}
	recall := 1.0
	if tp+fn > 0 {
		recall = float64(tp) / float64(tp+fn)
	}
	f1 := 0.0
	if precision+recall > 0 {
		f1 = 2 * (precision * recall) / (precision + recall)
	}
	accuracy := float64(tp+tn) / float64(len(ds.Pairs))

	avgExtractUs := (float64(totalExtractDuration.Nanoseconds()) / 1000.0) / float64(len(ds.Pairs)*2)
	avgCheckUs := (float64(totalCheckDuration.Nanoseconds()) / 1000.0) / float64(len(ds.Pairs))
	avgTotalUs := (float64((totalExtractDuration + totalCheckDuration).Nanoseconds()) / 1000.0) / float64(len(ds.Pairs))

	report := GuardReport{
		Provenance:      "classifier_fixture",
		Timestamp:       time.Now().UTC().Format(time.RFC3339),
		TotalPairs:      len(ds.Pairs),
		NearMissCount:   nearMisses,
		ParaphraseCount: paraphrases,
		TruePositives:   tp,
		FalsePositives:  fp,
		FalseNegatives:  fn,
		TrueNegatives:   tn,
		Precision:       round4(precision),
		Recall:          round4(recall),
		F1:              round4(f1),
		Accuracy:        round4(accuracy),
		AvgExtractionUs: round2(avgExtractUs),
		AvgCheckUs:      round2(avgCheckUs),
		AvgOverheadUs:   round2(avgTotalUs),
		BudgetCompliant: avgTotalUs < 100.0,
		Results:         results,
	}

	outJson, _ := json.MarshalIndent(report, "", "  ")
	_ = os.MkdirAll(filepath.Dir(*outPath), 0755)
	if err := os.WriteFile(*outPath, outJson, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "failed to write report: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Guard Eval Complete:\n")
	fmt.Printf("  Total Pairs: %d (Near-miss: %d, Paraphrase: %d)\n", len(ds.Pairs), nearMisses, paraphrases)
	fmt.Printf("  Accuracy: %.2f%%  Precision: %.4f  Recall: %.4f  F1: %.4f\n", accuracy*100, precision, recall, f1)
	fmt.Printf("  Avg Extraction Latency: %.2f us  Avg Check Latency: %.2f us  Avg Total Overhead: %.2f us [classifier fixture]\n", avgExtractUs, avgCheckUs, avgTotalUs)
	fmt.Printf("  Budget Compliant (<100us): %v\n", avgTotalUs < 100.0)
	fmt.Printf("  Report written to: %s\n", *outPath)
}

func round4(val float64) float64 {
	return float64(int(val*10000+0.5)) / 10000
}

func round2(val float64) float64 {
	return float64(int(val*100+0.5)) / 100
}
