#!/usr/bin/env python3
"""Public-safe, stdlib-only reference oracle for xyOps -> Agent Dispatch.

This is NOT a production scheduler, HTTP service, sidecar adapter, credential
manager, or admission grant.  It models only the unresolved authority seam.
Canonical GitHub DLE state is represented by a deliberately simple in-memory
test double; everything with a side effect is a synthetic receipt.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
TIMING_KEYS = frozenset({"kind", "at_utc", "weekday", "hour", "minute", "time_zone"})
CREATE_KEYS = frozenset({"authority_ref", "expected_revision", "schedule_id", "timing"})
CHANGE_KEYS = frozenset({"schedule_id", "expected_schedule_revision", "timing", "enabled"})
BANNED_EVENT_KEYS = frozenset({"script", "command", "plugin", "params", "targets", "workflow", "url", "shell"})
REF_RE = re.compile(r"^https://github[.]com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*$")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
HEX_RE = re.compile(r"^[0-9a-f]{40}$")

def reject_extra(obj: dict, fields: frozenset[str], what: str) -> None:
    if not isinstance(obj, dict) or set(obj) - fields:
        raise ValueError(f"{what}: unsupported or execution-bearing fields")
    if BANNED_EVENT_KEYS & set(obj):
        raise ValueError(f"{what}: unsafe execution field")

def parse_timing(obj: dict) -> dict:
    reject_extra(obj, TIMING_KEYS, "timing")
    kind = obj.get("kind")
    if kind == "once":
        if set(obj) != {"kind", "at_utc"}: raise ValueError("one-shot requires UTC and nothing else")
        dt = datetime.fromisoformat(obj["at_utc"].replace("Z", "+00:00"))
        if dt.utcoffset() != timedelta(0) or dt.second or dt.microsecond:
            raise ValueError("one-shot requires whole-minute UTC")
        return {"type":"single", "epoch":int(dt.timestamp()), "enabled":True}
    if kind == "weekly":
        if set(obj) != {"kind", "weekday", "hour", "minute", "time_zone"}:
            raise ValueError("weekly requires explicit timezone and time")
        if type(obj["weekday"]) is not int or not 1 <= obj["weekday"] <= 7:
            raise ValueError("weekday out of range")
        if type(obj["hour"]) is not int or not 0 <= obj["hour"] <= 23: raise ValueError("hour out of range")
        if type(obj["minute"]) is not int or not 0 <= obj["minute"] <= 59: raise ValueError("minute out of range")
        if not isinstance(obj["time_zone"], str): raise ValueError("timezone type")
        try: ZoneInfo(obj["time_zone"])
        except (KeyError, ValueError) as exc: raise ValueError("unknown IANA timezone") from exc
        # ISO weekday -> xyOps Sunday=0
        return {"type":"schedule", "weekdays":[(obj["weekday"] % 7)],
            "hours":[obj["hour"]], "minutes":[obj["minute"]],
            "timezone":obj["time_zone"], "enabled":True}
    raise ValueError("unsupported recurrence; do not accept raw cron or plugin parameters")

@dataclass(frozen=True)
class Owner:
    authority_ref: str
    revision: str
    admitted: bool
    state: str

@dataclass
class Projection:
    schedule_id: str
    authority_ref: str
    authority_revision: str
    schedule_revision: int
    trigger: dict
    enabled: bool = True

def create(request:dict, owners:dict[str,Owner], stable_template:dict) -> tuple[Projection,dict]:
    reject_extra(request, CREATE_KEYS, "create")
    if set(request) != CREATE_KEYS: raise ValueError("create missing a required field")
    ref, revision, sid = (request[k] for k in ("authority_ref", "expected_revision", "schedule_id"))
    if not isinstance(ref,str) or not REF_RE.fullmatch(ref): raise ValueError("bad exact authority ref")
    if not isinstance(revision,str) or not HEX_RE.fullmatch(revision):raise ValueError("bad authority revision")
    if not isinstance(sid,str) or not ID_RE.fullmatch(sid):raise ValueError("bad stable schedule identifier")
    owner=owners.get(ref)
    if not owner or not owner.admitted or owner.state!="approved" or owner.revision!=revision:
        raise PermissionError("not an admitted, current approved owner")
    trigger=parse_timing(request["timing"])
    # The execution-bearing template may ONLY be supplied by trusted host
    # configuration; never supplied by untrusted ChatGPT/MCP caller request.
    if not isinstance(stable_template,dict) or stable_template.get("plugin") != "approved-wake":
        raise PermissionError("trusted wake plugin not configured")
    event=copy.deepcopy(stable_template)
    event["title"]="Wake "+sid
    event["enabled"]=True
    event["triggers"]=[trigger]
    event["params"]["authority_ref"]=ref
    event["params"]["authority_revision"]=revision
    event["params"]["schedule_id"]=sid
    return Projection(sid,ref,revision,1,trigger),event

def change(proj:Projection,request:dict)->Projection:
    reject_extra(request, CHANGE_KEYS, "change")
    if set(request)-{"schedule_id","expected_schedule_revision"} not in ({"timing"},{"enabled"}):
        raise ValueError("change exactly one of timing or enabled")
    if request.get("schedule_id")!=proj.schedule_id or request.get("expected_schedule_revision")!=proj.schedule_revision:
        raise ValueError("stale schedule revision")
    next_=copy.deepcopy(proj)
    if "timing" in request: next_.trigger=parse_timing(request["timing"])
    elif type(request.get("enabled")) is bool: next_.enabled=request["enabled"]
    else: raise ValueError("invalid enabled")
    next_.schedule_revision+=1
    return next_

def occurrence_key(proj:Projection,due_utc:datetime)->str:
    if due_utc.utcoffset()!=timedelta(0) or due_utc.second or due_utc.microsecond:
        raise ValueError("due must be UTC whole minute")
    payload={"schedule_id":proj.schedule_id,"schedule_revision":proj.schedule_revision,
             "authority_ref":proj.authority_ref,"authority_revision":proj.authority_revision,
             "due_utc":due_utc.isoformat()}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()

@dataclass
class SyntheticClaimLedger:
    # An oracle for WOW's create-once behavior. Not a replacement database.
    claims:dict[str,str]=field(default_factory=dict)
    effects:list[str]=field(default_factory=list)

    def wake(self,proj:Projection,at:datetime,owners:dict[str,Owner], *,lost_ack:bool=False)->str:
        owner=owners.get(proj.authority_ref)
        if not proj.enabled or not owner or not owner.admitted or owner.state!="approved":
            return "NOOP_STALE_OR_UNADMITTED"
        if owner.revision!=proj.authority_revision:
            return "NOOP_REVISION_CHANGED"
        key=occurrence_key(proj,at)
        if key in self.claims:
            return "UNKNOWN_RECONCILE" if self.claims[key]=="unknown" else "DUPLICATE_NOOP"
        # Claim first; all effects below occur only AFTER create-once.
        self.claims[key]="claimed"
        if lost_ack:
            self.claims[key]="unknown"
            return "UNKNOWN_RECONCILE"
        self.effects.append(key)
        self.claims[key]="receipt"
        return "ACCEPTED_SYNTHETIC_RECEIPT"

def wall_clock_occurrences(weekday:int,hour:int,minute:int,zone:str,
                           start_utc:datetime,days:int=15)->list[datetime]:
    """Reference preview policy, not an implementation of xyOps calendar engine.

    Spring-forward nonexistent local times are SKIPPED; fall-back ambiguous
    local times are emitted ONCE using the first fold. Return UTC instants.
    """
    tz=ZoneInfo(zone)
    day=start_utc.astimezone(tz).date()
    found=[]
    for n in range(days):
        date_=day+timedelta(days=n)
        if date_.isoweekday()!=weekday:continue
        naive=datetime(date_.year,date_.month,date_.day,hour,minute)
        candidates=[]
        for fold in (0,1):
            instant=naive.replace(tzinfo=tz,fold=fold).astimezone(UTC)
            back=instant.astimezone(tz)
            if (back.year,back.month,back.day,back.hour,back.minute)==(naive.year,naive.month,naive.day,hour,minute):
                candidates.append(instant)
        if candidates:
            first=min(candidates)
            if first>start_utc:found.append(first)
    return found

class Contract(unittest.TestCase):
    def setUp(self):
        self.ref="https://github.com/example/project/issues/42"
        self.rev="a"*40
        self.owners={self.ref:Owner(self.ref,self.rev,True,"approved")}
        self.template={"plugin":"approved-wake","targets":["registered-operator"],
            "params":{"fixed_action":"reconcile-owner"}}
        self.now=datetime(2026,11,8,18,0,tzinfo=UTC)
        self.once={"kind":"once","at_utc":"2026-11-09T08:30:00Z"}
        self.req={"authority_ref":self.ref,"expected_revision":self.rev,
            "schedule_id":"owner-research", "timing":self.once}
        self.proj,self.event=create(self.req,self.owners,self.template)

    def test_creates_only_fixed_execution_profile(self):
        self.assertEqual(self.event["plugin"],"approved-wake")
        self.assertEqual(self.event["targets"],["registered-operator"])
        self.assertEqual(self.event["params"]["fixed_action"],"reconcile-owner")
        self.assertEqual(self.template["params"],{"fixed_action":"reconcile-owner"})
        self.assertEqual(self.event["triggers"][0]["type"],"single")

    def test_rejects_all_execution_bearing_input(self):
        for key in ("plugin","targets","params","command","script","workflow","shell","url","category","extra"):
            with self.subTest(key=key):
                bad=dict(self.req);bad[key]="arbitrary"
                with self.assertRaises(ValueError):create(bad,self.owners,self.template)
        for key in ("script","command","targets","params","workflow","plugin"):
            with self.subTest(key=key):
                bad=dict(self.req);bad["timing"]={**self.once,key:"evil"}
                with self.assertRaises(ValueError):create(bad,self.owners,self.template)

    def test_owner_state_and_revision_are_nonnegotiable(self):
        for owner in (None, Owner(self.ref,"b"*40,True,"approved"),
                      Owner(self.ref,self.rev,False,"approved"),
                      Owner(self.ref,self.rev,True,"cancelled"),
                      Owner(self.ref,self.rev,True,"complete")):
            with self.subTest(owner=owner):
                with self.assertRaises(PermissionError):
                    create(self.req,({self.ref:owner} if owner else {}),self.template)
        with self.assertRaises(PermissionError):
            create(self.req,self.owners,{"plugin":"shellplug","params":{"script":"whoami"}})

    def test_revision_checked_edit_and_no_authority_widening(self):
        disabled=change(self.proj,{"schedule_id":self.proj.schedule_id,
            "expected_schedule_revision":1,"enabled":False})
        self.assertEqual(disabled.schedule_revision,2)
        with self.assertRaises(ValueError):
            change(disabled,{"schedule_id":disabled.schedule_id,
                "expected_schedule_revision":1,"enabled":True})
        for key in ("plugin","command","targets","params","workflow","authority_ref"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    change(disabled,{"schedule_id":disabled.schedule_id,
                        "expected_schedule_revision":2,key:"evil"})

    def test_duplicate_and_lost_ack_fail_closed(self):
        ledger=SyntheticClaimLedger()
        self.assertEqual(ledger.wake(self.proj,self.now,self.owners,lost_ack=True),"UNKNOWN_RECONCILE")
        self.assertEqual(ledger.wake(self.proj,self.now,self.owners),"UNKNOWN_RECONCILE")
        self.assertEqual(ledger.effects,[])
        new_time=self.now+timedelta(minutes=1)
        self.assertEqual(ledger.wake(self.proj,new_time,self.owners),"ACCEPTED_SYNTHETIC_RECEIPT")
        self.assertEqual(ledger.wake(self.proj,new_time,self.owners),"DUPLICATE_NOOP")
        self.assertEqual(len(ledger.effects),1)

    def test_stale_or_cancelled_work_does_not_execute(self):
        for owner in (Owner(self.ref,self.rev,True,"cancelled"),
                      Owner(self.ref,"b"*40,True,"approved"),
                      Owner(self.ref,self.rev,False,"approved")):
            ledger=SyntheticClaimLedger()
            result=ledger.wake(self.proj,self.now,{self.ref:owner})
            self.assertTrue(result.startswith("NOOP"))
            self.assertEqual(ledger.effects,[])

    def test_weekly_explicit_zone_and_rejects_invalid(self):
        wk={"kind":"weekly","weekday":7,"hour":2,"minute":30,"time_zone":"Europe/Berlin"}
        self.assertEqual(parse_timing(wk)["weekdays"],[0])
        for key,value in (("hour",24),("minute",60),("weekday",0),("time_zone","Not/AZone")):
            bad=dict(wk);bad[key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):parse_timing(bad)

    def test_spring_gap_skip_and_fall_fold_once(self):
        spring=wall_clock_occurrences(7,2,30,"Europe/Berlin",datetime(2027,3,26,tzinfo=UTC),11)
        self.assertEqual([x.isoformat() for x in spring],["2027-04-04T00:30:00+00:00"])
        autumn=wall_clock_occurrences(7,2,30,"Europe/Berlin",datetime(2027,10,29,tzinfo=UTC),11)
        self.assertEqual([x.isoformat() for x in autumn],
                         ["2027-10-31T00:30:00+00:00","2027-11-07T01:30:00+00:00"])

    def test_rejects_ambiguous_one_shot_and_raw_cron(self):
        for bad in ({"kind":"once","at_utc":"2026-11-09T09:30:00+01:00"},
                    {"kind":"once","at_utc":"2026-11-09T08:30:30Z"},
                    {"kind":"cron","expression":"* * * * *"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):parse_timing(bad)

if __name__=="__main__":
    unittest.main(verbosity=2)
