// Public-safe xyOps native Event Plugin protocol probe.
// NO Agent Dispatch/WOW calls: a narrow special job type is qualified independently
// while the ordinary xyOps plugins, UI and MCP remain unrestricted by this component.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"regexp"
	"strconv"
	"strings"
)

const maxJobBytes = 65536

var exactRef = regexp.MustCompile(`^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*$`)
var exactSHA = regexp.MustCompile(`^[a-f0-9]{40}$`)
var opaqueID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$`)

type Params struct {
	AuthorityRef      string `json:"authority_ref"`
	AuthorityRevision string `json:"authority_revision"`
	Delegation        string `json:"delegation"`
}

type Job struct {
	XY     int             `json:"xy"`
	Type   string          `json:"type"`
	Plugin string          `json:"plugin"`
	ID     string          `json:"id"`
	Event  string          `json:"event"`
	Source string          `json:"source"`
	Now    json.Number     `json:"now"`
	Params json.RawMessage `json:"params"`
}

type Policy struct {
	Allowed []Params `json:"allowed"`
}

type Result struct {
	XY          int            `json:"xy"`
	Complete    bool           `json:"complete"`
	Code        int            `json:"code"`
	Description string         `json:"description"`
	Data        map[string]any `json:"data,omitempty"`
}

func readJSON(data []byte, value any, strict bool) error {
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.UseNumber()
	if strict { decoder.DisallowUnknownFields() }
	if err := decoder.Decode(value); err != nil { return err }
	var extra any
	if decoder.Decode(&extra) != io.EOF { return errors.New("trailing JSON data") }
	return nil
}

func handle(raw []byte, trustedPolicy []byte) (Result, error) {
	var job Job
	if len(raw) == 0 || len(raw) > maxJobBytes { return Result{}, errors.New("invalid job input size") }
	if err := readJSON(raw, &job, false); err != nil { return Result{}, errors.New("invalid xyOps job JSON") }
	if job.XY != 1 || job.Type != "event" || job.Plugin != "agent_dispatch_wake" ||
		!opaqueID.MatchString(job.ID) || !opaqueID.MatchString(job.Event) {
		return Result{}, errors.New("unsupported job identity or plugin")
	}
	if job.Source != "scheduler" && job.Source != "user" {
		return Result{}, errors.New("unsupported job source")
	}
	epoch, err := strconv.ParseInt(job.Now.String(), 10, 64)
	if err != nil || epoch < 1 { return Result{}, errors.New("invalid occurrence timestamp") }
	var params Params
	if err := readJSON(job.Params, &params, true); err != nil {
		return Result{}, errors.New("unknown or malformed special-job parameter")
	}
	if !exactRef.MatchString(params.AuthorityRef) || !exactSHA.MatchString(params.AuthorityRevision) ||
		!opaqueID.MatchString(params.Delegation) {
		return Result{}, errors.New("invalid bounded authority locator")
	}
	var policy Policy
	if err := readJSON(trustedPolicy, &policy, true); err != nil { return Result{}, errors.New("trusted policy unavailable") }
	matched := false
	for _, a := range policy.Allowed {
		if a == params { matched = true; break }
	}
	if !matched { return Result{}, errors.New("not in trusted synthetic authority fixture") }
	// Key uses upstream xyOps scheduler-selected occurrence time, NEVER wall clock
	// time when a retry happens; it can be reused by the real claim boundary later.
	sum := sha256.Sum256([]byte(fmt.Sprintf("xyops-wake-v1\n%s\n%s\n%s\n%s\n%d",
		params.AuthorityRef, params.AuthorityRevision, params.Delegation, job.Event, epoch)))
	return Result{XY:1,Complete:true,Code:0,Description:"synthetic reference receipt only: no external dispatch",
		Data:map[string]any{"simulated":true,"occurrence_key":hex.EncodeToString(sum[:]),
			"source":job.Source,"event_id":job.Event}}, nil
}

func main() {
	raw, err := io.ReadAll(io.LimitReader(os.Stdin, maxJobBytes+1))
	if err == nil && os.Getenv("XYOPS_RDTE_POLICY") == "" { err = errors.New("no trusted fixture") }
	var trusted []byte
	if err == nil { trusted, err = os.ReadFile(os.Getenv("XYOPS_RDTE_POLICY")) }
	if err == nil {
		var result Result
		result, err = handle(raw, trusted)
		if err == nil {
			_ = json.NewEncoder(os.Stdout).Encode(result)
			return
		}
	}
	// No input/policy strings are echoed: avoid leaking credential-like data.
	_ = json.NewEncoder(os.Stdout).Encode(Result{XY:1,Complete:true,Code:1,
		Description:"special-job synthetic reject: "+err.Error()})
	os.Exit(1)
}
