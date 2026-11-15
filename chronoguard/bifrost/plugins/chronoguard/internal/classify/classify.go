package classify

import (
	"regexp"
	"strings"
	"time"
)
var patterns=[]struct{class string; re *regexp.Regexp}{
	{"realtime",regexp.MustCompile(`(?i)\b(stock price|exchange rate|weather|live score|forex)\b`)},
	{"news_events",regexp.MustCompile(`(?i)\b(today|this week|recently|announced|breaking news)\b`)},
	{"pricing_plans",regexp.MustCompile(`(?i)\b(price|pricing|cost per|quota|rate limit)\b`)},
	{"software_versions",regexp.MustCompile(`(?i)\b(version|release|api|deprecated|latest stable)\b`)},
	{"regulation_policy",regexp.MustCompile(`(?i)\b(law|tax rate|regulation|deadline|compliance)\b`)},
	{"org_people",regexp.MustCompile(`(?i)\b(ceo|founder|headcount|leadership)\b`)},
}
func Prompt(text string) string {
	r:=[]rune(text); if len(r)>2000 {r=r[len(r)-2000:]}; text=string(r)
	for _,p:=range patterns {if p.re.MatchString(text){return p.class}}
	if strings.Contains(strings.ToLower(text),"current") || strings.Contains(strings.ToLower(text),"latest") {return "news_events"}
	return "slow_facts"
}
func HardTTL(class string) time.Duration {
	soft:=map[string]time.Duration{"static":30*24*time.Hour,"slow_facts":90*24*time.Hour,"org_people":21*24*time.Hour,"software_versions":7*24*time.Hour,"pricing_plans":3*24*time.Hour,"regulation_policy":14*24*time.Hour,"news_events":24*time.Hour,"realtime":0}[class]
	ttl:=8*soft; if ttl<time.Hour {ttl=time.Hour}; if ttl>30*24*time.Hour {ttl=30*24*time.Hour}; return ttl
}
