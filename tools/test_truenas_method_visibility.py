#!/usr/bin/env python3
"""Source-only adversarial guard for method visibility taxonomy. No network."""
import copy
import importlib.util
import pathlib
import unittest

HERE=pathlib.Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location("truenas_method_visibility",HERE/"truenas_method_visibility.py")
m=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

TARGET="25.04.2.6"
REQUIRED=["system.version","core.get_methods","app.query","app.config",
          "app.create","app.update","app.redeploy","app.stop","app.start","app.delete"]
PUBLIC=[x for x in REQUIRED if x!="core.get_methods"]
PIN=m.PINNED[TARGET]


def source_only_receipt():
    return {
        "method":m.DISCOVERY,
        "target_version":TARGET,
        "middleware_commit":PIN["source_commit"],
        "source_path":PIN["source_path"],
        "source_blob":PIN["source_blob"],
        "transport":"DDP_AUTHENTICATED",
        "invocation":"SUCCESS",
        "returned_as_public":False,
        "side_effects":False,
        "trusted_adapter_attestation":False,
    }


class MethodVisibilityOracle(unittest.TestCase):
    def test_known_private_method_observation_is_candidate_never_apply_ready(self):
        r=m.classify(TARGET,REQUIRED,PUBLIC,source_only_receipt())
        self.assertEqual(r["status"],"SOURCE_VISIBILITY_CANDIDATE")
        self.assertEqual(r["promotion"],"DENIED_UNTIL_INDEPENDENT_TRUSTED_ADAPTER_REVIEW")
        self.assertEqual(r["trusted_adapter_proof"],"NOT_ESTABLISHED")
        self.assertEqual(r["required_authenticated_discovery_methods"],["core.get_methods"])
        self.assertNotIn("core.get_methods",r["required_public_methods_corrected"])
        self.assertEqual(r["receipt_sha256"],m.digest({k:v for k,v in r.items() if k!="receipt_sha256"}))
        self.assertFalse(r["site_mutation"])

    def test_identical_reps_are_deterministic(self):
        a=m.classify(TARGET,REQUIRED,PUBLIC,source_only_receipt())
        for _ in range(6):
            self.assertEqual(a,m.classify(TARGET,REQUIRED,PUBLIC,source_only_receipt()))

    def test_other_versions_fail_closed_until_separate_source_review(self):
        for version in ["25.04.1","25.10.7","26.0.0-BETA.3","26.0.0","",TARGET+"-MODIFIED"]:
            with self.subTest(version=version):
                r=m.classify(version,REQUIRED,PUBLIC,source_only_receipt())
                self.assertEqual(r["status"],"BLOCKED")
                self.assertEqual(r["promotion"],"DENIED")

    def test_method_list_sanitization_never_sneaks_private_or_missing_public(self):
        cases=[
            (REQUIRED,REQUIRED),
            (REQUIRED,PUBLIC[:-1]),
            (REQUIRED,PUBLIC+["app.query"]),
            (REQUIRED,[""]),
            (REQUIRED,[None]),
            (REQUIRED,["app.query","app.query"]),
            ([x for x in REQUIRED if x!="core.get_methods"],PUBLIC),
            (REQUIRED+["unverified.private"],PUBLIC),
            (REQUIRED+[123],PUBLIC),
            (REQUIRED+[REQUIRED[-1]],PUBLIC),
        ]
        for required,observed in cases:
            with self.subTest(required=required,observed=observed):
                self.assertEqual(m.classify(TARGET,required,observed,source_only_receipt())["status"],"BLOCKED")

    def test_exact_receipt_drift_and_forged_attestation_rejected(self):
        original=source_only_receipt()
        poisons={
            "method":"filesystem.file_receive",
            "target_version":"25.10.7",
            "middleware_commit":"f"*40,
            "source_path":"src/middlewared/plugins/foreign.py",
            "source_blob":"a"*40,
            "transport":"UNAUTHENTICATED",
            "invocation":"NOT_RUN",
            "returned_as_public":True,
            "side_effects":True,
            "trusted_adapter_attestation":True,
        }
        for key,value in poisons.items():
            with self.subTest(key=key):
                p=copy.deepcopy(original)
                p[key]=value
                r=m.classify(TARGET,REQUIRED,PUBLIC,p)
                self.assertEqual(r["status"],"BLOCKED")
                self.assertEqual(r["promotion"],"DENIED")
        for bad in (None,{},["not_a_receipt"],{**original,"unknown":"privileged"}):
            self.assertEqual(m.classify(TARGET,REQUIRED,PUBLIC,bad)["status"],"BLOCKED")

    def test_never_edits_existing_registry_or_method_lists(self):
        import json
        registry_path=HERE.parent/".foundry/truenas-target-tracks.json"
        registry=json.loads(registry_path.read_text(encoding="utf-8"))
        before=registry_path.read_bytes()
        old=next(x for x in registry["targets"] if x["version"]==TARGET)
        self.assertIn(m.DISCOVERY,old["profile_contract"]["required_public_methods"])
        m.classify(TARGET,REQUIRED,PUBLIC,source_only_receipt())
        self.assertEqual(before,registry_path.read_bytes())


if __name__=="__main__":
    unittest.main()
