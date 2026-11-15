package decide

import (
	"testing"
	"time"
	"github.com/chronoguard/chronoguard/internal/manifest"
)
func TestSafetyMatrix(t *testing.T) {
	now:=time.Date(2026,1,1,0,0,0,0,time.UTC)
	future,past:=now.Add(time.Hour),now.Add(-time.Hour)
	for _, policy:=range []string{"strict","standard","lenient"} {
		for _, status:=range []string{"fresh","due","stale","pending","unverifiable","unknown"} {
			next:=&future; if status=="due" {next=&past}
			m:=&manifest.Manifest{Status:"fresh", Claims:[]manifest.Claim{{Status:status,Class:"software_versions",NextCheckAt:next}}}
			d:=Decide(m,Default(policy),now)
			if policy=="strict" && status!="fresh" && d==Serve {t.Fatalf("strict served %s",status)}
			if status=="fresh" && d!=Serve {t.Fatalf("fresh %s got %s",policy,d)}
			if status=="due" && policy!="strict" && d!=SWR {t.Fatalf("due got %s",d)}
		}
	}
}
func TestFailClosedMissingAndBoundary(t *testing.T) {
	now:=time.Now(); p:=Default("strict")
	if Decide(nil,p,now)!=Blocking {t.Fatal("missing must verify")}
	m:=&manifest.Manifest{Status:"fresh",BestBefore:&now}
	if Decide(m,p,now)!=Blocking {t.Fatal("expiry is inclusive")}
	m=&manifest.Manifest{Status:"fresh",Claims:[]manifest.Claim{{Status:"fresh",Class:"pricing_plans"}}}
	if Decide(m,p,now)!=Blocking {t.Fatal("undated dynamic claim must verify")}
	if Unavailable(p)!=FailClosed {t.Fatal("strict outage must fail closed")}
}
func BenchmarkFreshDecision(b *testing.B) {
	now:=time.Now(); next:=now.Add(time.Hour)
	m:=&manifest.Manifest{Status:"fresh",Claims:[]manifest.Claim{{Status:"fresh",NextCheckAt:&next}}}; p:=Default("strict")
	for b.Loop() {Decide(m,p,now)}
}
