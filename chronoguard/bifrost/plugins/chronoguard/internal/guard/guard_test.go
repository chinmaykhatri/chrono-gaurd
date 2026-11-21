package guard

import "testing"

func TestExtract(t *testing.T) {
	tests := []struct {
		prompt    string
		wantYears []string
		wantNums  []string
		wantEnts  []string
		wantPols  []string
	}{
		{
			prompt:    "Who was the CEO of Apple in 2010?",
			wantYears: []string{"2010"},
			wantNums:  []string{},
			wantEnts:  []string{"Apple"},
		},
		{
			prompt:    "What is the capital of Australia?",
			wantYears: []string{},
			wantNums:  []string{},
			wantEnts:  []string{"Australia"},
		},
		{
			prompt:    "Is Python 3.12 released?",
			wantYears: []string{},
			wantNums:  []string{"3.12"},
			wantEnts:  []string{"Python"},
		},
		{
			prompt:    "Who is the former CEO of Microsoft?",
			wantYears: []string{},
			wantNums:  []string{},
			wantEnts:  []string{"Microsoft"},
			wantPols:  []string{"former"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.prompt, func(t *testing.T) {
			sig := Extract(tc.prompt)
			if tc.wantYears != nil && !equalSets(sig.Years, tc.wantYears) {
				t.Errorf("Extract(%q).Years = %v, want %v", tc.prompt, sig.Years, tc.wantYears)
			}
			if tc.wantNums != nil && !equalSets(sig.Numbers, tc.wantNums) {
				t.Errorf("Extract(%q).Numbers = %v, want %v", tc.prompt, sig.Numbers, tc.wantNums)
			}
			if tc.wantEnts != nil && !equalSets(sig.Entities, tc.wantEnts) {
				t.Errorf("Extract(%q).Entities = %v, want %v", tc.prompt, sig.Entities, tc.wantEnts)
			}
			if tc.wantPols != nil && !equalSets(sig.Polarity, tc.wantPols) {
				t.Errorf("Extract(%q).Polarity = %v, want %v", tc.prompt, sig.Polarity, tc.wantPols)
			}
		})
	}
}

func TestCheck(t *testing.T) {
	cases := []struct {
		name        string
		incoming    string
		cached      string
		wantTripped bool
		wantReason  string
	}{
		{
			name:        "Entity mismatch: Australia vs Austria",
			incoming:    "What is the capital of Australia?",
			cached:      "What is the capital of Austria?",
			wantTripped: true,
			wantReason:  "entity_mismatch",
		},
		{
			name:        "Year mismatch: 2010 vs present",
			incoming:    "Who is the CEO of Apple?",
			cached:      "Who was the CEO of Apple in 2010?",
			wantTripped: true,
			wantReason:  "year_mismatch",
		},
		{
			name:        "Number mismatch: Python version 3.12 vs 3.10",
			incoming:    "Is Python 3.12 supported?",
			cached:      "Is Python 3.10 supported?",
			wantTripped: true,
			wantReason:  "number_mismatch",
		},
		{
			name:        "Polarity mismatch: current vs former",
			incoming:    "Who is the current CEO of Microsoft?",
			cached:      "Who is the former CEO of Microsoft?",
			wantTripped: true,
			wantReason:  "polarity_mismatch",
		},
		{
			name:        "Polarity mismatch: negation",
			incoming:    "Is TypeScript supported?",
			cached:      "Is TypeScript not supported?",
			wantTripped: true,
			wantReason:  "polarity_mismatch",
		},
		{
			name:        "True paraphrase: Australia's capital",
			incoming:    "What is the capital of Australia?",
			cached:      "What is Australia's capital?",
			wantTripped: false,
			wantReason:  "",
		},
		{
			name:        "True paraphrase: Apple CEO phrasing",
			incoming:    "Who is the CEO of Apple?",
			cached:      "Who is currently the chief executive officer of Apple?",
			wantTripped: false,
			wantReason:  "",
		},
		{
			name:        "True paraphrase: Python 3.12 stability",
			incoming:    "Is Python 3.12 stable?",
			cached:      "Can I run Python 3.12 in production safely?",
			wantTripped: false,
			wantReason:  "",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			inSig := Extract(tc.incoming)
			caSig := Extract(tc.cached)
			tripped, reason := Check(inSig, caSig)

			if tripped != tc.wantTripped {
				t.Fatalf("Check(%q, %q) tripped=%v, want %v (reason=%q)", tc.incoming, tc.cached, tripped, tc.wantTripped, reason)
			}
			if tc.wantReason != "" && reason != tc.wantReason {
				t.Errorf("Check(%q, %q) reason=%q, want %q", tc.incoming, tc.cached, reason, tc.wantReason)
			}
		})
	}
}

func BenchmarkExtractSignature(b *testing.B) {
	prompt := "Who was the CEO of Microsoft in 2010, and is Python 3.12 supported?"
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_ = Extract(prompt)
	}
}

func TestRejectsChangedEntityAndReversedRoles(t *testing.T) {
	for _, test := range []struct{ incoming, cached, reason string }{
		{"what is the capital of australia?", "what is the capital of austria?", "entity_mismatch"},
		{"Did India defeat France?", "Did France defeat India?", "entity_role_mismatch"},
	} {
		persisted, ok := Decode(Extract(test.cached).Encode())
		if !ok {
			t.Fatal("stored signature did not decode")
		}
		if tripped, reason := Check(Extract(test.incoming), persisted); !tripped || reason != test.reason {
			t.Errorf("got tripped=%t, reason=%q, want %q", tripped, reason, test.reason)
		}
	}
}

func TestDistanceIsSymmetricOnlyWithoutRouteQualifiers(t *testing.T) {
	first := Extract("What is the distance between Paris and Lyon?")
	for _, tc := range []struct {
		query  string
		reject bool
	}{
		{"How far is Lyon from Paris?", false},
		{"How far is Lyon from Paris by train?", true},
		{"How far is Lyon from London?", true},
		{"Did Paris defeat Lyon?", true},
	} {
		if rejected, reason := Check(first, Extract(tc.query)); rejected != tc.reject {
			t.Errorf("%q: rejected=%v, reason=%q", tc.query, rejected, reason)
		}
	}
}
