import json
import tempfile
import unittest
from pathlib import Path
from importlib.util import module_from_spec, spec_from_file_location

HERE = Path(__file__).resolve().parent
SPEC = spec_from_file_location("foliorelay_t6", HERE / "build_foliorelay_t6_control.py")
MOD = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def digest(ch: str) -> str:
    return "sha256:" + ch * 64


def publication():
    return {
        "schema": MOD.PUBLICATION_SCHEMA,
        "status": "PASS",
        "source_revision": "a" * 40,
        "control": {"digest": digest("1"), "anonymous_pull": True, "signed_keyless": True},
        "cups": {"digest": digest("2"), "anonymous_pull": True, "signed_keyless": True},
    }


def mount(source, target, ro=False):
    return {"type": "bind", "source": source, "target": target, "read_only": ro}


def compose():
    control_image = "ghcr.io/sempersupra/foliorelay-control@" + digest("1")
    cups_image = "ghcr.io/sempersupra/foliorelay-cups@" + digest("2")
    return {
        "services": {
            "control": {
                "image": control_image,
                "read_only": True,
                "cap_drop": ["ALL"],
                "ports": [{"target": 18080, "published": "18080"}],
                "volumes": [
                    mount(MOD.CONTROL_ROOT, MOD.CONTROL_TARGET),
                    mount(MOD.ARTIFACT_ROOT, MOD.ARTIFACT_TARGET),
                    mount(MOD.TOKEN_PATH, MOD.TOKEN_TARGET, True),
                ],
            },
            "cups": {
                "image": cups_image,
                "read_only": True,
                "cap_drop": ["ALL"],
                "ports": [{"target": 8634, "published": "8634"}],
                "tmpfs": [
                    "/etc/cups:rw,size=4m",
                    "/var/cache/cups:rw,size=16m",
                    "/var/log/cups:rw,size=16m",
                ],
                "volumes": [
                    mount(MOD.CONTROL_ROOT, MOD.CUPS_CONTROL_TARGET, True),
                    mount(MOD.ARTIFACT_ROOT, MOD.CUPS_ARTIFACT_TARGET),
                    mount(MOD.CUPS_STATE_ROOT, "/var/lib/cups"),
                    mount(MOD.CUPS_SPOOL_ROOT, "/var/spool/cups"),
                    mount(MOD.TOKEN_PATH, MOD.TOKEN_TARGET, True),
                ],
            },
            "discovery": {
                "image": control_image,
                "read_only": True,
                "cap_drop": ["ALL"],
                "network_mode": "host",
                "volumes": [
                    mount(MOD.CONTROL_ROOT, MOD.CUPS_CONTROL_TARGET, True),
                ],
            },
        }
    }


class FolioRelayT6ControlTests(unittest.TestCase):
    def test_valid_render(self):
        target = {
            "schema_version": 2,
            "profile_id": "truenas-scale-25.04.1-materialization",
            "truenas_version": "25.04.1",
        }
        rendered = MOD.materialize_target_compose(compose(), target)
        facts = MOD.validate(publication(), rendered, target)
        self.assertEqual(facts["truenas_version"], "25.04.1")
        self.assertEqual(facts["discovery_backend"], "avahi")
        self.assertTrue(facts["control_image"].endswith(digest("1")))
        self.assertTrue(facts["cups_image"].endswith(digest("2")))

    def test_build_is_product_invariant_across_admitted_targets(self):
        repo = HERE.parent
        versions = ("25.04.1", "25.04.2.6", "25.10.7", "26.0.0-BETA.3")
        baseline = None
        observed = set()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pub = root / "publication.json"
            comp = root / "compose.json"
            values = root / "values.yaml"
            pub.write_text(json.dumps(publication()), encoding="utf-8")
            comp.write_text(json.dumps(compose()), encoding="utf-8")
            values.write_text("printer_name: FolioRelay\n", encoding="utf-8")
            for version in versions:
                target = repo / ".foundry" / "truenas-compatibility" / f"{version}-materialization.json"
                out = root / version
                control = MOD.build(pub, comp, values, target, out, "f" * 40)
                self.assertEqual(control["candidate"]["truenas_version"], version)
                observed.add(version)
                invariant = {
                    "control_image": control["candidate"]["control_image"],
                    "cups_image": control["candidate"]["cups_image"],
                    "compose_sha256": control["artifacts"]["compose_canonical_sha256"],
                    "required_oracles": tuple(control["required_oracles"]),
                    "secrets_captured": control["secrets_captured"],
                }
                if baseline is None:
                    baseline = invariant
                else:
                    self.assertEqual(invariant, baseline)
        self.assertEqual(observed, set(versions))

    def test_rejects_moving_image(self):
        value = compose()
        value["services"]["cups"]["image"] = "ghcr.io/sempersupra/foliorelay-cups:latest"
        with self.assertRaises(MOD.ControlError):
            MOD.validate(publication(), value, {"profile_id": "p", "truenas_version": "26.0.0-BETA.3"})

    def test_rejects_missing_cups_tmpfs(self):
        value = compose()
        value["services"]["cups"]["tmpfs"] = ["/var/cache/cups", "/var/log/cups"]
        with self.assertRaises(MOD.ControlError):
            MOD.validate(publication(), value, {"profile_id": "p", "truenas_version": "26.0.0-BETA.3"})

    def test_rejects_discovery_without_host_network(self):
        value = compose()
        value["services"]["discovery"]["network_mode"] = "bridge"
        with self.assertRaises(MOD.ControlError):
            MOD.validate(publication(), value, {"profile_id": "p", "truenas_version": "26.0.0-BETA.3"})

    def test_rejects_host_service_coupling(self):
        value = compose()
        value["services"]["discovery"]["volumes"].append(
            mount("/run/dbus", "/run/dbus", True)
        )
        with self.assertRaises(MOD.ControlError):
            MOD.validate(publication(), value, {"profile_id": "p", "truenas_version": "26.0.0-BETA.3"})

    def test_build_emits_exact_control_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pub = root / "publication.json"
            comp = root / "compose.json"
            values = root / "values.yaml"
            target = root / "target.json"
            out = root / "out"
            pub.write_text(json.dumps(publication()), encoding="utf-8")
            comp.write_text(json.dumps(compose()), encoding="utf-8")
            values.write_text("printer_name: FolioRelay\n", encoding="utf-8")
            target.write_text(json.dumps({
                "schema_version": 2,
                "profile_id": "truenas-scale-26.0.0-beta.3-materialization",
                "truenas_version": "26.0.0-BETA.3",
            }), encoding="utf-8")
            control = MOD.build(pub, comp, values, target, out, "f" * 40)
            self.assertEqual(control["schema"], MOD.SCHEMA)
            self.assertIn("dnssd-universal-visible", control["required_oracles"])
            self.assertTrue((out / "control.json").exists())


if __name__ == "__main__":
    unittest.main()
