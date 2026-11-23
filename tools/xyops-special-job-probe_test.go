package main

import (
	"encoding/json"
	"strings"
	"testing"
)

const testRef = "https://github.com/example/synthetic-workset/issues/42"
const testRevision = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
const testPolicy = `{"allowed":[{"authority_ref":"https://github.com/example/synthetic-workset/issues/42","authority_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","delegation":"synthetic-observe"}]}`

func exampleJob(epoch int64) []byte {
	b,_ := json.Marshal(map[string]any{
		"xy":1,"type":"event","plugin":"agent_dispatch_wake","id":"job_123",
		"event":"evt_456","source":"scheduler","now":epoch,
		"params":map[string]any{"authority_ref":testRef,"authority_revision":testRevision,
			"delegation":"synthetic-observe"},
	})
	return b
}

func TestNativeSpecialJobProtocol(t *testing.T) {
	ok,err:=handle(exampleJob(1794171600),[]byte(testPolicy))
	if err!=nil || ok.Code!=0 || !ok.Complete || ok.Data["simulated"]!=true {
		t.Fatalf("expected synthetic receipt: %+v %v",ok,err)
	}
	again,err:=handle(exampleJob(1794171600),[]byte(testPolicy))
	if err!=nil || ok.Data["occurrence_key"]!=again.Data["occurrence_key"] {
		t.Fatalf("identical schedule occurrence must yield stable correlation")
	}
	next,err:=handle(exampleJob(1794171660),[]byte(testPolicy))
	if err!=nil || ok.Data["occurrence_key"]==next.Data["occurrence_key"] {
		t.Fatalf("different due occurrence must have distinct correlation key")
	}
}

func TestRejectsAuthorityAndExecutionInjection(t *testing.T) {
	cases:=[]string{
		`"script":"echo hacked"`, `"plugin":"shellplug"`,
		`"workflow":{}`, `"url":"https://example.com"`,
		`"targets":["main"]`,
	}
	for _,extra:=range cases {
		b:=exampleJob(1794171600)
		needle:=`"params":{`
		if !strings.Contains(string(b),needle){t.Fatalf("missing params in generated fixture")}
		b=[]byte(strings.Replace(string(b),needle,needle+extra+",",1))
		if _,err:=handle(b,[]byte(testPolicy));err==nil {
			t.Errorf("unsafe special param accepted: %s",extra)
		}
	}
	badRef:=strings.Replace(string(exampleJob(1794171600)),testRef,
		"https://github.com/example/other/issues/1",1)
	if _,err:=handle([]byte(badRef),[]byte(testPolicy));err==nil {t.Fatal("unadmitted owner accepted")}
	badRev:=strings.Replace(string(exampleJob(1794171600)),testRevision, strings.Repeat("b",40),1)
	if _,err:=handle([]byte(badRev),[]byte(testPolicy));err==nil {t.Fatal("stale revision accepted")}
	badPlugin:=strings.Replace(string(exampleJob(1794171600)),
		"agent_dispatch_wake","shellplug",1)
	if _,err:=handle([]byte(badPlugin),[]byte(testPolicy));err==nil {t.Fatal("wrong plugin accepted")}
}

func TestMalformedInputFailsClosed(t *testing.T) {
	for _,raw:=range [][]byte{nil,[]byte("{}"),[]byte("not json"),[]byte("[]"),
		[]byte(strings.Repeat("x",maxJobBytes+1))} {
		if _,err:=handle(raw,[]byte(testPolicy));err==nil {t.Errorf("invalid input accepted")}
	}
	if _,err:=handle(exampleJob(1794171600),[]byte("invalid"));err==nil {
		t.Fatal("bad trusted policy accepted")
	}
	if _,err:=handle(exampleJob(1794171600),[]byte(`{"allowed":[]}`));err==nil {
		t.Fatal("missing owner admission accepted")
	}
}
