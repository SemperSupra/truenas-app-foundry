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
                "security_opt": ["no-new-privileges:true"],
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
                "security_opt": ["no-new-privileges:true"],
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
                "security_opt": ["no-new-privileges:true"],
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

    def test_build_keeps_product_invariants_but_materializes_discovery_per_target(self):
        repo = HERE.parent
        versions = ("25.04.1", "25.04.2.6", "25.10.7", "26.0.0-BETA.3")
        baseline = None
        compose_ids = {}
        backends = {}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pub = root / "publication.json"
            comp = root / "compose.json"
            values = root / "values.yaml"
            pub.write_text(json.dumps(publication()), encoding="utf-8")
            comp.write_text(json.dumps(compose()), encoding="utf-8")
            values.write_text("printer_name: FolioRelay\\n", encoding="utf-8")
            for version in versions:
                target = repo / ".foundry" / "truenas-compatibility" / f"{version}-materialization.json"
                out = root / version
                control = MOD.build(pub, comp, values, target, out, "f" * 40)
                rendered = json.loads((out / "compose.json").read_text(encoding="utf-8"))
                self.assertEqual(control["candidate"]["truenas_version"], version)
                invariant = {
                    "control_image": control["candidate"]["control_image"],
                    "cups_image": control["candidate"]["cups_image"],
                    "required_oracles": tuple(control["required_oracles"]),
                    "secrets_captured": control["secrets_captured"],
                }
                if baseline is None:
                    baseline = invariant
                else:
                    self.assertEqual(invariant, baseline)
                compose_ids[version] = control["artifacts"]["compose_canonical_sha256"]
                backends[version] = control["candidate"]["discovery_backend"]

                discovery = rendered["services"]["discovery"]
                if version in MOD.AVAHI_TARGETS:
                    self.assertEqual(discovery["command"], MOD.AVAHI_DISCOVERY_COMMAND)
                    self.assertEqual(discovery["user"], MOD.AVAHI_DISCOVERY_USER)
                    bus = [
                        item for item in discovery["volumes"]
                        if item.get("target") == MOD.DBUS_SOCKET
                    ]
                    self.assertEqual(bus, [{
                        "type": "bind",
                        "source": MOD.DBUS_SOCKET,
                        "target": MOD.DBUS_SOCKET,
                        "read_only": True,
                    }])
                else:
                    self.assertNotIn(MOD.DBUS_SOCKET, json.dumps(discovery, sort_keys=True))
                    self.assertNotIn("-backend", discovery["command"])
                    self.assertNotIn("user", discovery)

        self.assertEqual(
            {version: backends[version] for version in MOD.AVAHI_TARGETS},
            {version: "avahi" for version in MOD.AVAHI_TARGETS},
        )
        self.assertEqual(backends["26.0.0-BETA.3"], "direct")
        self.assertEqual(len({compose_ids[version] for version in MOD.AVAHI_TARGETS}), 1)
        self.assertNotEqual(compose_ids["26.0.0-BETA.3"], compose_ids["25.10.7"])

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

    def test_rejects_capability_readdition_or_missing_no_new_privileges(self):
        target = {"profile_id": "p", "truenas_version": "26.0.0-BETA.3"}
        value = MOD.materialize_target_compose(compose(), target)
        value["services"]["discovery"]["cap_add"] = ["NET_ADMIN"]
        with self.assertRaises(MOD.ControlError):
            MOD.validate(publication(), value, target)

        value = MOD.materialize_target_compose(compose(), target)
        value["services"]["discovery"]["security_opt"] = []
        with self.assertRaises(MOD.ControlError):
            MOD.validate(publication(), value, target)

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

    def test_25x_rejects_wrong_discovery_user(self):
        target = {"profile_id": "p", "truenas_version": "25.10.7"}
        value = MOD.materialize_target_compose(compose(), target)
        value["services"]["discovery"]["user"] = "10001:10001"
        with self.assertRaises(MOD.ControlError):
            MOD.validate(publication(), value, target)

    def test_25x_rejects_any_dbus_mount_beyond_exact_discovery_socket(self):
        target = {"profile_id": "p", "truenas_version": "25.10.7"}
        value = MOD.materialize_target_compose(compose(), target)
        value["services"]["control"]["volumes"].append(
            mount("/run/dbus/other", "/run/dbus/other", True)
        )
        with self.assertRaises(MOD.ControlError):
            MOD.validate(publication(), value, target)


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
