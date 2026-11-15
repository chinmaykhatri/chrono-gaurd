package classify
import "testing"
func TestPrompt(t *testing.T){for text,want:=range map[string]string{"What is the current stock price?":"realtime","Who is the CEO?":"org_people","Explain a triangle":"slow_facts","Latest stable version of Python":"software_versions","API pricing plans":"pricing_plans"}{if got:=Prompt(text);got!=want{t.Errorf("%q got %s want %s",text,got,want)}}}
