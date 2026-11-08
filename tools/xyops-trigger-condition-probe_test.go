package main

import (
 "encoding/json"
 "strings"
 "testing"
)

const shaA="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
const shaB="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
const fixture=`{"watches":[{"key":"watch-ready","condition":"TRUE","observed_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","accepted_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"key":"watch-false","condition":"FALSE","observed_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","accepted_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"key":"watch-unknown","condition":"UNKNOWN","observed_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","accepted_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"key":"watch-accepted","condition":"TRUE","observed_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","accepted_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}`

func inp(keys ...string) []byte {
 items:=make([]any,0,len(keys))
 for _,k:=range keys{items=append(items,map[string]any{"params":map[string]any{"watch_key":k},"now":1794182400})}
 b,_:=json.Marshal(map[string]any{"xy":1,"type":"trigger","items":items})
 return b
}
func TestMixedNativeTriggerDecisions(t *testing.T){
 o,err:=evaluate(inp("watch-ready","watch-false","watch-unknown","watch-accepted","unknown-key"),[]byte(fixture))
 if err!=nil{t.Fatal(err)}
 want:=[]bool{true,false,false,false,false}
 if len(o.Items)!=len(want)||o.XY!=1{t.Fatalf("unexpected shape %+v",o)}
 for i,v:=range want{if o.Items[i]!=v{t.Fatalf("idx %d got %v want %v",i,o.Items[i],v)}}
}
func TestReplayTrueNeedsExternalReceipt(t *testing.T){
 a,e:=evaluate(inp("watch-ready"),[]byte(fixture));if e!=nil{t.Fatal(e)}
 b,e:=evaluate(inp("watch-ready"),[]byte(fixture));if e!=nil{t.Fatal(e)}
 if !a.Items[0]||!b.Items[0]{t.Fatal("static predicate must remain TRUE; dedup is not provided by plugin")}
}
func TestUntrustedParamsCannotWiden(t *testing.T){
 payload:=`{"xy":1,"type":"trigger","items":[{"params":{"watch_key":"watch-ready","script":"echo unsafe"}},{"params":{"watch_key":"../policy"}},{"params":{}},{"params":{"watch_key":"watch-false"}}]}`
 o,e:=evaluate([]byte(payload),[]byte(fixture));if e!=nil{t.Fatal(e)}
 for i,v:=range o.Items{if v{t.Fatalf("unauthorized launch at %d",i)}}
}
func TestInvalidBatchAndPolicyFailClosed(t *testing.T){
 invalidInputs:=[]string{"", "{}", "[]", `{"xy":2,"type":"trigger","items":[{"params":{"watch_key":"watch-ready"}}]}`, `{"xy":1,"type":"event","items":[{"params":{"watch_key":"watch-ready"}}]}`, `{"xy":1,"type":"trigger","items":[]}`}
 for _,x:=range invalidInputs{if _,err:=evaluate([]byte(x),[]byte(fixture));err==nil{t.Errorf("accepted invalid input %q",x)}}
 invalidPolicies:=[]string{"", "{}", `{"watches":[{"key":"watch-ready","condition":"surprise","observed_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}`, `{"watches":[{"key":"watch-ready","condition":"TRUE","observed_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},{"key":"watch-ready","condition":"TRUE","observed_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}`}
 for _,x:=range invalidPolicies{if _,err:=evaluate(inp("watch-ready"),[]byte(x));err==nil{t.Errorf("accepted invalid policy %q",x)}}
 if _,err:=evaluate([]byte(strings.Repeat("x",maxInputBytes+1)),[]byte(fixture));err==nil{t.Fatal("accepted oversized input")}
}
func TestOutputIsOnlyBoolArray(t *testing.T){
 o,e:=evaluate(inp("watch-ready","watch-unknown"),[]byte(fixture));if e!=nil{t.Fatal(e)}
 b,_:=json.Marshal(o)
 if string(b)!=`{"xy":1,"items":[true,false]}`{t.Fatalf("unexpected extra execution content: %s",b)}
}
