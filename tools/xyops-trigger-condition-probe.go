// Public-safe native xyOps Trigger Plugin seam probe: synthetic fixtures only.
// It is NOT an Agent Dispatch client or an accepted condition-watch migration.
// A repeated true result is expected until a separate durable owner ledger is used.
package main

import (
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "os"
 "regexp"
 "strings"
)

const maxInputBytes = 128 * 1024
var watchKey = regexp.MustCompile(`^[a-z][a-z0-9_-]{1,63}$`)
var revision = regexp.MustCompile(`^[a-f0-9]{40}$`)

type Watch struct {
 Key string `json:"key"`
 Condition string `json:"condition"`
 ObservedRevision string `json:"observed_revision"`
 AcceptedRevision string `json:"accepted_revision"`
}
type Policy struct { Watches []Watch `json:"watches"` }
type Input struct {
 XY int `json:"xy"`
 Type string `json:"type"`
 Items []struct { Params json.RawMessage `json:"params"` } `json:"items"`
}
type Output struct {
 XY int `json:"xy"`
 Items []bool `json:"items"`
}

func decodeOne(raw []byte, dest any, strict bool) error {
 d:=json.NewDecoder(strings.NewReader(string(raw)))
 if strict {d.DisallowUnknownFields()}
 if err:=d.Decode(dest);err!=nil{return err}
 var extra any
 if d.Decode(&extra)!=io.EOF{return errors.New("multiple JSON documents")}
 return nil
}

func evaluate(inputRaw, policyRaw []byte) (Output,error) {
 var in Input
 if len(inputRaw)==0||len(inputRaw)>maxInputBytes {return Output{},errors.New("invalid input size")}
 if err:=decodeOne(inputRaw,&in,false);err!=nil{return Output{},errors.New("malformed trigger input")}
 if in.XY!=1||in.Type!="trigger"||len(in.Items)==0||len(in.Items)>64 {
  return Output{},errors.New("unsupported trigger batch")
 }
 var p Policy
 if len(policyRaw)==0||len(policyRaw)>65536 {return Output{},errors.New("policy absent or oversized")}
 if err:=decodeOne(policyRaw,&p,true);err!=nil{return Output{},errors.New("invalid trusted policy")}
 valid:=map[string]Watch{}
 for _,w:=range p.Watches{
  if !watchKey.MatchString(w.Key)||!revision.MatchString(w.ObservedRevision)||
   (w.AcceptedRevision!=""&&!revision.MatchString(w.AcceptedRevision))||
   (w.Condition!="TRUE"&&w.Condition!="FALSE"&&w.Condition!="UNKNOWN") {
   return Output{},errors.New("invalid policy watch")
  }
  if _,ok:=valid[w.Key];ok{return Output{},errors.New("duplicate trusted watch")}
  valid[w.Key]=w
 }
 out:=Output{XY:1,Items:make([]bool,len(in.Items))}
 for i,item:=range in.Items{
  var q struct{ WatchKey string `json:"watch_key"` }
  if err:=decodeOne(item.Params,&q,true);err!=nil{continue}
  w,ok:=valid[q.WatchKey]
  if !ok {continue}
  // A static fixture alone cannot confirm accepted effects or suppress
  // repeat-true polls. That responsibility remains in owner-native ledger.
  out.Items[i]=w.Condition=="TRUE"&&w.ObservedRevision!=w.AcceptedRevision
 }
 return out,nil
}
func main(){
 raw,err:=io.ReadAll(io.LimitReader(os.Stdin,maxInputBytes+1))
 if err!=nil{fmt.Fprintln(os.Stderr,"invalid trigger input");os.Exit(1)}
 // Trusted public test fixture is bind-mounted read-only to the conductor.
 // The untrusted event cannot override the policy path or execute code.
 trusted,err:=os.ReadFile("/opt/xyops-rdte/condition-policy.json")
 if err!=nil{fmt.Fprintln(os.Stderr,"trusted condition fixture unavailable");os.Exit(1)}
 result,err:=evaluate(raw,trusted)
 if err!=nil{fmt.Fprintln(os.Stderr,"condition gate fail closed:",err);os.Exit(1)}
 if err:=json.NewEncoder(os.Stdout).Encode(result);err!=nil{os.Exit(1)}
}
