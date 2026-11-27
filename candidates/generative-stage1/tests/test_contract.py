"""Public V1 metadata tests. All data is synthetic / public-domain code."""
import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "tools"))
from validate_generative_stage1 import EXPECTED, validate_definition, validate_compose


class SourceContract(unittest.TestCase):
    def test_all_four_source_proposals(self):
        for name, port in EXPECTED.items():
            with self.subTest(name=name):
                obj = validate_definition(name)
                self.assertEqual(obj["upstream"]["container_port"], port)
                self.assertIsNone(obj["artifact"]["image_digest"])

    def test_no_unknown_candidate(self):
        with self.assertRaises(ValueError):
            validate_definition("future-unknown-app")

    def test_reject_wrong_port_and_public_interface(self):
        for name, port in EXPECTED.items():
            valid = {"services":{"app":{
                "user":"10001:10001","read_only":True,"cap_drop":["ALL"],
                "security_opt":["no-new-privileges:true"],
                "ports":[{"host_ip":"127.0.0.1","target":port}],
                "volumes":[{"type":"volume","source":"models","read_only":True},
                           {"type":"volume","source":"outputs","read_only":False}]
            }}}
            validate_compose(name, valid)
            exposed = copy.deepcopy(valid)
            exposed["services"]["app"]["ports"][0]["host_ip"] = "0.0.0.0"
            with self.assertRaises(ValueError):
                validate_compose(name, exposed)
            root_mount = copy.deepcopy(valid)
            root_mount["services"]["app"]["volumes"][0]["type"] = "bind"
            with self.assertRaises(ValueError):
                validate_compose(name, root_mount)
            privileged = copy.deepcopy(valid)
            privileged["services"]["app"]["privileged"] = True
            with self.assertRaises(ValueError):
                validate_compose(name, privileged)


if __name__ == "__main__":
    unittest.main()
