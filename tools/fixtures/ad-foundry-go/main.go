// A public, inert Go fixture for Foundry lifecycle RDTE; NOT Agent Dispatch.
package main

import (
    "fmt"
    "io"
    "log"
    "net/http"
    "os"
    "path/filepath"
    "strconv"
    "strings"
)

const requiredCustody = "public-synthetic"

func custodyValid(dir string) bool {
    b, err := os.ReadFile(filepath.Join(dir, "source.txt"))
    return err == nil && strings.TrimSpace(string(b)) == requiredCustody
}

func countFile(dir string) string { return filepath.Join(dir, "count") }

func count(dir string) (int, error) {
    b, err := os.ReadFile(countFile(dir))
    if os.IsNotExist(err) { return 0, nil }
    if err != nil { return 0, err }
    n, err := strconv.Atoi(strings.TrimSpace(string(b)))
    if err != nil || n < 0 { return 0, fmt.Errorf("invalid synthetic ledger count") }
    return n, nil
}

func work(custody, ledger string) error {
    if !custodyValid(custody) { return fmt.Errorf("synthetic custody missing or invalid") }
    n, err := count(ledger)
    if err != nil { return err }
    tmp, err := os.CreateTemp(ledger, ".synthetic-")
    if err != nil { return err }
    name := tmp.Name()
    defer os.Remove(name)
    if err := tmp.Chmod(0644); err != nil { tmp.Close(); return err }
    if _, err := io.WriteString(tmp, strconv.Itoa(n+1)+"\n"); err != nil { tmp.Close(); return err }
    if err := tmp.Sync(); err != nil { tmp.Close(); return err }
    if err := tmp.Close(); err != nil { return err }
    if err := os.Rename(name, countFile(ledger)); err != nil { return err }
    fmt.Printf("public-synthetic-worker-count=%d\n", n+1)
    return nil
}

func handler(custody, ledger string) http.Handler {
    mux := http.NewServeMux()
    mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodGet { http.Error(w,"method not allowed",http.StatusMethodNotAllowed); return }
        w.WriteHeader(http.StatusOK)
        _, _ = io.WriteString(w,"PUBLIC_SYNTHETIC_LIVE\n")
    })
    mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodGet { http.Error(w,"method not allowed",http.StatusMethodNotAllowed); return }
        n, err := count(ledger)
        if !custodyValid(custody) || err != nil || n < 1 {
            http.Error(w,"synthetic worker not ready",http.StatusServiceUnavailable)
            return
        }
        w.WriteHeader(http.StatusOK)
        _, _ = io.WriteString(w,"PUBLIC_SYNTHETIC_READY\n")
    })
    return mux
}

func main() {
    if len(os.Args) != 2 { log.Fatal("usage: synthetic serve|worker") }
    custody, ledger := "/custody", "/ledger"
    switch os.Args[1] {
    case "worker":
        if err := work(custody, ledger); err != nil { log.Fatal(err) }
    case "serve":
        log.Fatal(http.ListenAndServe(":8080", handler(custody, ledger)))
    default:
        log.Fatal("unknown synthetic mode")
    }
}
