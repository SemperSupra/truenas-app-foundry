import copy
import importlib.util
import pathlib
import unittest


TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location(
    "export_garm_t6_control", TOOLS / "export_garm_t6_control.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class GarmT6ControlTests(unittest.TestCase):
    def sample_compose(self):
        base_service = {
            "image": "ghcr.io/sempersupra/garm-appliance@sha256:" + "1" * 64,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges=true"],
            "volumes": [
                {
                    "type": "bind",
                    "source": "/opt/tests/mnt/garm/config",
                    "target": "/etc/garm",
                }
            ],
        }
        return {
            "services": {
                "garm": copy.deepcopy(base_service),
                "garm-config-seed": copy.deepcopy(base_service),
            },
            "configs": {
                "garm-initial-config": {"content": "fixture-bootstrap"},
                "garm-tls-certificate": {"content": "fixture-cert"},
                "garm-tls-private-key": {"content": "fixture-key"},
            },
        }

    def test_lowering_binds_disposable_nested_storage_and_redacts_secret_configs(self):
        result = mod.lower_for_nested(self.sample_compose())
        for name in ("garm", "garm-config-seed"):
            volume = result["services"][name]["volumes"][0]
            self.assertEqual(volume["source"], "/mnt/rdtepool/garm-t6/config")
            self.assertEqual(volume["target"], "/etc/garm")
        for name in ("garm-tls-certificate", "garm-tls-private-key"):
            self.assertTrue(
                result["configs"][name]["content"].startswith(
                    "__EPHEMERAL_NESTED_TLS__:"
                )
            )
        self.assertEqual(
            result["configs"]["garm-initial-config"]["content"],
            "__EPHEMERAL_NESTED_GARM_CONFIG__",
        )

    def test_lowering_rejects_unexpected_service_inventory(self):
        compose = self.sample_compose()
        compose["services"]["foreign"] = copy.deepcopy(compose["services"]["garm"])
        with self.assertRaises(mod.ValidationError):
            mod.lower_for_nested(compose)

    def test_lowering_rejects_missing_tls_configs(self):
        compose = self.sample_compose()
        compose["configs"].pop("garm-tls-private-key")
        with self.assertRaises(mod.ValidationError):
            mod.lower_for_nested(compose)

    def test_lowering_rejects_missing_bootstrap_config(self):
        compose = self.sample_compose()
        compose["configs"].pop("garm-initial-config")
        with self.assertRaises(mod.ValidationError):
            mod.lower_for_nested(compose)


if __name__ == "__main__":
    unittest.main()
