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
	"strings"
	"time"

	"github.com/chronoguard/chronoguard/internal/decide"
	"github.com/chronoguard/chronoguard/internal/manifest"
	"github.com/chronoguard/chronoguard/internal/verifierclient"
	"github.com/maximhq/bifrost/core/schemas"
	"github.com/redis/go-redis/v9"
)
type Config struct {
	RedisURL string `json:"redis_url"`
	VerifierURL string `json:"verifier_url"`
	InternalKeyEnv string `json:"internal_key_env"`
	InternalKey string `json:"internal_key"`
	DefaultPolicy string `json:"default_policy"`
	SingleTenantID string `json:"single_tenant_id"`
	Enabled bool `json:"enabled"`
}
type State struct {
	ID,Tenant,Class,Model string
	Policy decide.Policy
	Internal,Skip,Stream,Verified bool
	Messages []map[string]string
	Annotation map[string]any
	Decision string
	Cache string
	GroundID string
}
const StateKey schemas.BifrostContextKey="chronoguard.state"
type Runtime struct { Config Config; Key string; Redis *redis.Client; Verifier *verifierclient.Client }
func New(cfg Config)(*Runtime,error){
	key := cfg.InternalKey
	if key == "" {
		if cfg.InternalKeyEnv==""{cfg.InternalKeyEnv="CG_INTERNAL_KEY"}
		key = os.Getenv(cfg.InternalKeyEnv)
	}
	c,err:=verifierclient.New(cfg.VerifierURL,key);if err!=nil{return nil,err}
	opts,err:=redis.ParseURL(cfg.RedisURL);if err!=nil{return nil,errors.New("invalid Redis URL")}
	opts.DialTimeout=time.Second;opts.ReadTimeout=50*time.Millisecond;opts.WriteTimeout=50*time.Millisecond;opts.MaxRetries=0
	return &Runtime{cfg,key,redis.NewClient(opts),c},nil
}
func(s *Runtime)Cleanup()error{return s.Redis.Close()}
func Get(ctx *schemas.BifrostContext)*State {s,_:=ctx.Value(StateKey).(*State);return s}
func Trusted(given,want string)bool {return len(given)==len(want)&&subtle.ConstantTimeCompare([]byte(given),[]byte(want))==1}
func NewID()string{var b [16]byte;if _,err:=rand.Read(b[:]);err!=nil{panic("secure random unavailable")};b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;h:=hex.EncodeToString(b[:]);return h[:8]+"-"+h[8:12]+"-"+h[12:16]+"-"+h[16:20]+"-"+h[20:]}
func Tenant(ctx *schemas.BifrostContext,fallback string)string {
	// These are authenticated/resolved context keys, never client identity headers.
	if s,ok:=ctx.Value(schemas.BifrostContextKeyGovernanceVirtualKeyID).(string);ok&&s!=""{return "vk:"+s}
	if s,ok:=ctx.Value(schemas.BifrostContextKeyUserID).(string);ok&&s!=""{return "user:"+s}
	if fallback == "" { return "default" }
	return fallback
}
func(r *Runtime)Load(ctx context.Context,tenant,id string)(*manifest.Manifest,error){
	b,err:=r.Redis.Get(ctx,manifest.Key(tenant,"manifest",id)).Bytes();if err!=nil{return nil,err}
	var m manifest.Manifest;if err=json.Unmarshal(b,&m);err!=nil{return nil,err}
	if m.TenantID!=tenant||m.CacheID!=id||m.Version!=1{return nil,errors.New("manifest identity or version mismatch")};return &m,nil
}
func(r *Runtime)Now(ctx context.Context)time.Time {
	// Clock state uses real time for expiration of coordination locks. Failure to
	// load the demo clock must not advance a frozen clock silently; callers use
	// real time only in default production mode (clock controls disabled there).
	return time.Now().UTC()
}
func Text(res *schemas.BifrostResponse)string{
	if res==nil||res.ChatResponse==nil||len(res.ChatResponse.Choices)==0{return ""}
	c:=res.ChatResponse.Choices[0];if c.ChatNonStreamResponseChoice==nil||c.Message==nil||c.Message.Content==nil||c.Message.Content.ContentStr==nil{return ""};return *c.Message.Content.ContentStr
}
func Replace(res *schemas.BifrostResponse,text string){
	if res==nil||res.ChatResponse==nil||len(res.ChatResponse.Choices)==0{return};c:=&res.ChatResponse.Choices[0];if c.ChatNonStreamResponseChoice==nil||c.Message==nil{return};c.Message.Content=&schemas.ChatMessageContent{ContentStr:&text}
}
func Fail() *schemas.BifrostError {code:="chronoguard_unverifiable";status:=503;fallback:=false;return &schemas.BifrostError{IsBifrostError:true,StatusCode:&status,AllowFallbacks:&fallback,Error:&schemas.ErrorField{Code:&code,Message:"ChronoGuard could not verify this response within the configured policy."}}}
func HTTPFail(status int,message string)*schemas.HTTPResponse{b,_:=json.Marshal(map[string]any{"error":map[string]string{"code":"chronoguard_unverifiable","message":message}});return &schemas.HTTPResponse{StatusCode:status,Headers:map[string]string{"Content-Type":"application/json"},Body:b}}
func Payload(s *State,text,cacheID string)map[string]any{
	var id any;if cacheID!=""{id=cacheID};return map[string]any{"request_id":s.ID,"tenant_id":s.Tenant,"cache_id":id,"origin":"provider","model_id":s.Model,"messages":s.Messages,"response_text":text,"prompt_class":s.Class,"policy":s.Policy.Name,"usage":map[string]int{"input_tokens":0,"output_tokens":0}}
}
type Result struct {ResponseID string `json:"response_id"`;Status string `json:"status"`;Decision string `json:"decision"`;Annotation map[string]any `json:"annotation"`;RepairedText *string `json:"repaired_text"`;Replacement *struct{Text string `json:"text"`} `json:"replacement"`}
func SafeAnnotation(a map[string]any)bool{
	if a==nil{return false};if s,ok:=a["status"].(string);ok&&s!="complete"{return false}
	claims,ok:=a["claims"].([]any);if !ok{return false};for _,item:=range claims{c,ok:=item.(map[string]any);if !ok{return false};s,_:=c["status"].(string);if s!="fresh"&&s!="skipped"{return false}}
	return true
}
func(r *Runtime)Verify(ctx context.Context,s *State,res *schemas.BifrostResponse,cacheID string)error{
	text:=Text(res);if text==""{return errors.New("unsupported response")};payload:=Payload(s,text,cacheID);payload["deadline_ms"]=s.Policy.BlockingBudgetMS
	deadline,cancel:=context.WithTimeout(ctx,time.Duration(s.Policy.BlockingBudgetMS)*time.Millisecond);defer cancel();var out Result
	if err:=r.Verifier.Post(deadline,"/internal/v1/verify-inline",payload,&out);err!=nil{return err};s.Annotation=out.Annotation
	if s.Policy.Strictness=="strict"&&(out.Status!="complete"||!SafeAnnotation(out.Annotation)){return errors.New("verification incomplete")}
	if out.RepairedText!=nil{Replace(res,*out.RepairedText)};s.Verified=true;s.Decision="passthrough";return nil
}
func DeleteHeader(headers map[string]string,name string){for k:=range headers{if strings.EqualFold(k,name){delete(headers,k)}}}
