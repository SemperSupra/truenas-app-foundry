package main

import (
    "net/http"
    "net/http/httptest"
    "os"
    "path/filepath"
    "strings"
    "testing"
)

func TestSyntheticLifecycleRetainsCounterAcrossRuns(t *testing.T) {
    base := t.TempDir()
    custody, ledger := filepath.Join(base,"custody"), filepath.Join(base,"ledger")
    for _, dir := range []string{custody,ledger} {
        if err := os.Mkdir(dir,0700); err != nil {t.Fatal(err)}
    }
    if err := os.WriteFile(filepath.Join(custody,"source.txt"), []byte(requiredCustody+"\n"),0600); err != nil {t.Fatal(err)}
    rr := httptest.NewRecorder()
    handler(custody,ledger).ServeHTTP(rr,httptest.NewRequest("GET","/readyz",nil))
    if rr.Code != http.StatusServiceUnavailable {t.Fatalf("pre-work readiness %d",rr.Code)}
    for n:=1;n<=2;n++ {
        if err:=work(custody,ledger);err!=nil {t.Fatal(err)}
        got,err:=count(ledger);if err!=nil||got!=n {t.Fatalf("count %d: got %d: %v",n,got,err)}
    }
    rr=httptest.NewRecorder()
    handler(custody,ledger).ServeHTTP(rr,httptest.NewRequest("GET","/readyz",nil))
    if rr.Code!=http.StatusOK {t.Fatalf("post-work readiness %d",rr.Code)}
}

func TestFailClosedMissingCustodyOrCorruptLedger(t *testing.T) {
    base:=t.TempDir()
    if err:=work(filepath.Join(base,"missing"),base);err==nil {t.Fatal("missing custody admitted")}
    custody:=filepath.Join(base,"custody")
    if err:=os.Mkdir(custody,0700);err!=nil {t.Fatal(err)}
    if err:=os.WriteFile(filepath.Join(custody,"source.txt"),[]byte(requiredCustody),0600);err!=nil {t.Fatal(err)}
    if err:=os.WriteFile(filepath.Join(base,"count"),[]byte("bad-counter"),0600);err!=nil {t.Fatal(err)}
    if err:=work(custody,base);err==nil||!strings.Contains(err.Error(),"invalid") {t.Fatalf("corrupt ledger accepted: %v",err)}
}
