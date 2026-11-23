#!/usr/bin/env python3
"""Exact-source TrueNAS method visibility classifier; a *read-only* migration oracle.

Source-vs-runtime evidence from real TrueNAS 25.04.2.6 KVM #355 exposed a
profile bug: core.get_methods is @private, so its own *public* inventory omits
it, despite the callable endpoint existing for the authenticated DDP probe.

NEVER promote this classifier output to authority or mutate a site. A caller-
provided invocation claim is not cryptographic attestation, so the supported
result is a CANDIDATE for a separately reviewed trusted-adapter migration.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "truenas-foundry-method-visibility-oracle/v1"
DISCOVERY = "core.get_methods"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
PINNED = {
    "25.04.2.6": {
        "source_repo": "truenas/middleware",
        "source_commit": "244b717370fe35fb9eefc3096acfbc25f12b57b6",
        "source_blob": "1876ace7ab760e5daee8af99c372d19c7b426ecb",
        "source_path": "src/middlewared/middlewared/service/core_service.py",
        "visibility": "PRIVATE_DECORATOR",
        "filter": "PRIVATE_METHODS_OMITTED_FROM_GET_METHODS",
    }
}


def digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value,sort_keys=True,separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def deny(reason: str, target_version: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "BLOCKED",
        "target_version": target_version,
        "reason": reason,
        "promotion": "DENIED",
        "site_mutation": False,
    }


def classify(
    target_version: str,
    required_public_methods: list[str],
    observed_public_methods: list[str],
    discovery_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Validate exact, source-bound method visibility without granting mutation.

    The receipt must originate from an authenticated *trusted adapter* in a
    future release. At this stage it is untrusted, and no result is APPLY_READY.
    """
    pinned = PINNED.get(target_version)
    if pinned is None:
        return deny("target_not_source_verified", target_version)
    if not SHA40.fullmatch(pinned["source_commit"]) or not SHA40.fullmatch(pinned["source_blob"]):
        return deny("pinned_source_digest_invalid", target_version)
    if (
        not isinstance(required_public_methods, list)
        or not isinstance(observed_public_methods, list)
        or not all(isinstance(x,str) and x for x in required_public_methods+observed_public_methods)
        or len(required_public_methods)!=len(set(required_public_methods))
        or len(observed_public_methods)!=len(set(observed_public_methods))
    ):
        return deny("method_inventory_not_distinct_nonempty_strings", target_version)
    legacy=set(required_public_methods)
    public=set(observed_public_methods)
    if DISCOVERY in public:
        return deny("private_method_falsely_advertised_as_public", target_version)
    if DISCOVERY not in legacy:
        return deny("legacy_profile_does_not_have_expected_visibility_bug", target_version)
    missing=sorted((legacy-{DISCOVERY})-public)
    if missing:
        return deny("other_required_public_methods_missing:"+",".join(missing),target_version)
    if not isinstance(discovery_receipt,dict):
        return deny("missing_authenticated_discovery_receipt", target_version)
    expected = {
        "method": DISCOVERY,
        "target_version": target_version,
        "middleware_commit": pinned["source_commit"],
        "source_path": pinned["source_path"],
        "source_blob": pinned["source_blob"],
        "transport": "DDP_AUTHENTICATED",
        "invocation": "SUCCESS",
        "returned_as_public": False,
        "side_effects": False,
        "trusted_adapter_attestation": False,
    }
    if discovery_receipt!=expected:
        return deny("untrusted_or_nonmatching_discovery_evidence", target_version)
    result={
        "schema": SCHEMA,
        "status": "SOURCE_VISIBILITY_CANDIDATE",
        "target_version": target_version,
        "source_binding": dict(pinned),
        "required_public_methods_corrected": sorted(legacy-{DISCOVERY}),
        "required_authenticated_discovery_methods": [DISCOVERY],
        "observed_public_methods_sha256": digest({"methods": sorted(public)}),
        "private_discovery_invocation": "SOURCE_BOUND_CALL_CLAIM_ONLY",
        "trusted_adapter_proof": "NOT_ESTABLISHED",
        "promotion": "DENIED_UNTIL_INDEPENDENT_TRUSTED_ADAPTER_REVIEW",
        "site_mutation": False,
        "old_legacy_profile_must_not_be_silently_modified": True,
    }
    result["receipt_sha256"]=digest(result)
    return result


if __name__=="__main__":
    print(json.dumps({"schema":SCHEMA,"pinned_source":PINNED,
                      "admission":"SOURCE_ORACLE_ONLY_NOT_PRODUCTION"},indent=2,sort_keys=True))
