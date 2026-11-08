package main

// Standalone public-safe contract hypothesis: a native xyOps special wake can
// submit a bounded synthetic claim; its HTTP peer is httptest, not Pandora/WOW.
// The production operator's transport/schema/admission are NOT represented.
import (
  "bytes"
  "context"
  "encoding/json"
  "errors"
  "io"
  "net"
  "net/http"
  "net/http/httptest"
  "net/url"
  "strconv"
  "strings"
  "sync"
  "testing"
  "time"
)
type wakeClaim struct {
  Version, EventID, OccurrenceKey string
  DueUTC int64
  AuthorityRef, AuthorityRevision, Delegation string
}
type claimReceipt struct { State, Key string }

func compileSyntheticClaim(raw []byte, trusted []byte) (wakeClaim,error) {
  result,err:=handle(raw,trusted)
  if err!=nil {return wakeClaim{},err}
  var job Job
  if err:=readJSON(raw,&job,false);err!=nil{return wakeClaim{},err}
  var params Params
  if err:=readJSON(job.Params,&params,true);err!=nil{return wakeClaim{},err}
  due,err:=strconv.ParseInt(job.Now.String(),10,64)
  if err!=nil{return wakeClaim{},err}
  key,ok:=result.Data["occurrence_key"].(string)
  if !ok || len(key)!=64 {return wakeClaim{},errors.New("no correlation key")}
  return wakeClaim{"xyops-wake-v1",job.Event,key,due,
    params.AuthorityRef,params.AuthorityRevision,params.Delegation},nil
}
func mockSend(ctx context.Context, endpoint string, c wakeClaim) (string,error) {
  u,err:=url.Parse(endpoint)
  if err!=nil || u.Scheme!="http" || u.Path!="/v1/claim" || u.RawQuery!="" || u.User!=nil {
    return "DENIED",errors.New("invalid synthetic receiver")
  }
  host,_,err:=net.SplitHostPort(u.Host)
  if err!=nil || net.ParseIP(host)==nil || !net.ParseIP(host).IsLoopback() {
    return "DENIED",errors.New("receiver must be loopback")
  }
  payload:=map[string]any{"version":c.Version,"event_id":c.EventID,
    "occurrence_key":c.OccurrenceKey,"due_utc":c.DueUTC,
    "authority_ref":c.AuthorityRef,"authority_revision":c.AuthorityRevision,
    "delegation":c.Delegation}
  data,err:=json.Marshal(payload)
  if err!=nil {return "DENIED",err}
  req,err:=http.NewRequestWithContext(ctx,"POST",endpoint,bytes.NewReader(data))
  if err!=nil{return "DENIED",err}
  req.Header.Set("Content-Type","application/json")
  req.Header.Set("X-Occurrence-Key",c.OccurrenceKey)
  client:=&http.Client{Timeout:1800*time.Millisecond,
    CheckRedirect:func(*http.Request,[]*http.Request)error{return http.ErrUseLastResponse}}
  resp,err:=client.Do(req)
  if err!=nil{return "UNKNOWN_RECONCILE",nil}
  defer resp.Body.Close()
  if resp.StatusCode==403 || resp.StatusCode==409 {return "DENIED",nil}
  if resp.StatusCode!=202 {return "UNKNOWN_RECONCILE",nil}
  raw,err:=io.ReadAll(io.LimitReader(resp.Body,2049))
  if err!=nil||len(raw)>2048 {return "UNKNOWN_RECONCILE",nil}
  var body map[string]any
  if err:=readJSON(raw,&body,false);err!=nil{return "UNKNOWN_RECONCILE",nil}
  if body["key"]!=c.OccurrenceKey {return "UNKNOWN_RECONCILE",nil}
  if body["state"]=="CLAIM_ACCEPTED" {return "SYNTHETIC_CLAIM_ACCEPTED",nil}
  if body["state"]=="DUPLICATE" {return "DUPLICATE_NOOP",nil}
  return "UNKNOWN_RECONCILE",nil
}
type fakeOwner struct {
  mu sync.Mutex
  revision string
  permitted, dropAck bool
  claims map[string]bool
  deliveries, effects int
}
func newOwner() *fakeOwner {
  return &fakeOwner{revision:testRevision,permitted:true,claims:map[string]bool{}}
}
func (f *fakeOwner) ServeHTTP(w http.ResponseWriter,r *http.Request) {
  f.mu.Lock(); defer f.mu.Unlock()
  f.deliveries++
  raw,_:=io.ReadAll(io.LimitReader(r.Body,2049))
  var body map[string]any
  err:=readJSON(raw,&body,false)
  if err!=nil || len(raw)>2048 || r.Method!="POST" || r.URL.Path!="/v1/claim" ||
    r.Header.Get("Content-Type")!="application/json" ||
    body["version"]!="xyops-wake-v1" || body["authority_ref"]!=testRef ||
    body["authority_revision"]!=f.revision || body["delegation"]!="synthetic-observe" ||
    body["occurrence_key"]!=r.Header.Get("X-Occurrence-Key") || !f.permitted {
      http.Error(w,"no synthetic admission",http.StatusForbidden);return
  }
  key:=body["occurrence_key"].(string)
  state:="CLAIM_ACCEPTED"
  if f.claims[key] {state="DUPLICATE"}else{f.claims[key]=true;f.effects++}
  if f.dropAck {
    if h,ok:=w.(http.Hijacker);ok {if conn,_,err:=h.Hijack();err==nil{_ = conn.Close();return}}
    return
  }
  w.Header().Set("Content-Type","application/json")
  w.WriteHeader(202)
  _=json.NewEncoder(w).Encode(map[string]any{"state":state,"key":key})
}
func TestBoundedSyntheticClaimAndDuplicate(t *testing.T) {
  f:=newOwner(); s:=httptest.NewServer(f);defer s.Close()
  c,err:=compileSyntheticClaim(exampleJob(1794171600),[]byte(testPolicy));if err!=nil{t.Fatal(err)}
  a,err:=mockSend(context.Background(),s.URL+"/v1/claim",c)
  if err!=nil||a!="SYNTHETIC_CLAIM_ACCEPTED"{t.Fatalf("first: %s %v",a,err)}
  a,err=mockSend(context.Background(),s.URL+"/v1/claim",c)
  if err!=nil||a!="DUPLICATE_NOOP"||f.effects!=1||f.deliveries!=2 {t.Fatalf("duplicate: %s %v",a,err)}
}
func TestBoundedSyntheticStaleOrCancelled(t *testing.T) {
  for _,scenario:=range []string{"stale","cancelled"}{
    t.Run(scenario,func(t *testing.T){
      f:=newOwner()
      if scenario=="stale"{f.revision=strings.Repeat("b",40)}else{f.permitted=false}
      s:=httptest.NewServer(f);defer s.Close()
      c,err:=compileSyntheticClaim(exampleJob(1794171600),[]byte(testPolicy));if err!=nil{t.Fatal(err)}
      x,err:=mockSend(context.Background(),s.URL+"/v1/claim",c)
      if x!="DENIED"||err!=nil||f.effects!=0 {t.Fatalf("not denied: %s %v",x,err)}
    })
  }
}
func TestBoundedSyntheticLostAcknowledgment(t *testing.T) {
  f:=newOwner();f.dropAck=true
  s:=httptest.NewServer(f);defer s.Close()
  c,err:=compileSyntheticClaim(exampleJob(1794171600),[]byte(testPolicy));if err!=nil{t.Fatal(err)}
  x,err:=mockSend(context.Background(),s.URL+"/v1/claim",c)
  if x!="UNKNOWN_RECONCILE"||err!=nil||f.effects!=1||f.deliveries!=1 {
    t.Fatalf("lost acknowledgement must be UNKNOWN no automatic replay: %s %v",x,err)
  }
}
func TestBoundedSyntheticRejectsWideningAndExternalEndpoints(t *testing.T) {
  c,err:=compileSyntheticClaim(exampleJob(1794171600),[]byte(testPolicy));if err!=nil{t.Fatal(err)}
  for _,dest:=range []string{"https://example.org/v1/claim","http://example.org/v1/claim",
     "http://127.0.0.1:5555/other","http://127.0.0.1:5555/v1/claim?q=1"}{
     result,err:=mockSend(context.Background(),dest,c)
     if result!="DENIED"||err==nil{t.Fatalf("unsafe mock destination allowed: %s",dest)}
  }
  b:=strings.Replace(string(exampleJob(1794171600)),
    "\"params\":{","\"params\":{\"command\":\"whoami\",",1)
  if _,err:=compileSyntheticClaim([]byte(b),[]byte(testPolicy));err==nil {
    t.Fatal("special job accepted arbitrary command")
  }
}
