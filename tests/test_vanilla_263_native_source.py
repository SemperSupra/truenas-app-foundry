"""Native vanilla 26.3 / Java25 tuple red gates. Real source render in GHA."""
import json
import pathlib
import unittest
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import validate_minecraft_world_control as m

PIN=json.loads(m.VANILLA_PIN.read_text())
VALUES=m.VANILLA_VALUES.read_text()
PROFILE=json.loads((ROOT/".foundry/truenas-compatibility/25.04.2.6-materialization.json").read_text())
SHA="5a2ab74ae179c11e2dbbce67f307cdcf2c1257b3abb0f654d3a310b3d8ea57da"

class NativeVanillaTests(unittest.TestCase):
    def test_upstream_digest_and_source_identity_are_exact(self):
        self.assertEqual(PIN["ref"],"559b9fe85212c800bc6770f152a65211df137a44")
        self.assertEqual(PIN["catalog_version"],"1.15.30")
        self.assertEqual(PIN["library_version"],"2.3.4")
        self.assertEqual(PIN["image"],
            "ghcr.io/itzg/minecraft-server:2026.10.0-java25@sha256:"+SHA)
    def test_only_current_backend_and_selector(self):
        self.assertIn("image_selector: j25_image",VALUES)
        self.assertIn("type: VANILLA",VALUES)
        self.assertIn("version: 26.3",VALUES)
        self.assertIn("online_mode: true",VALUES)
        self.assertIn("enable_rcon: false",VALUES)
        self.assertIn("path: /opt/tests/collage-vanilla-263-world",VALUES)
        self.assertIn("value: lantern-rdte",VALUES)
        self.assertNotIn("type: PAPER",VALUES)
        self.assertNotIn("version: 1.21.11",VALUES)
    def test_required_host_target_is_exact(self):
        self.assertEqual(PROFILE["truenas_version"],"25.04.2.6")
        self.assertEqual(PROFILE["middleware"]["commit"],
            "244b717370fe35fb9eefc3096acfbc25f12b57b6")
    def test_cannot_reuse_vanilla_pin_with_default_paper_values(self):
        with self.assertRaisesRegex(m.ValidationError,"unadmitted vanilla"):
            m.validate(pin_path=m.VANILLA_PIN)
    def test_cannot_mutate_vanilla_version_before_render(self):
        with self.assertRaisesRegex(m.ValidationError,"unadmitted vanilla"):
            m.validate(pin_path=m.VANILLA_PIN,values_path=m.VANILLA_VALUES,
                expected_type="VANILLA",expected_version="1.21.11",
                expected_selector="j25_image",
                expected_world_path="/opt/tests/collage-vanilla-263-world")
    def test_cannot_feed_wrong_image_selector(self):
        with self.assertRaisesRegex(m.ValidationError,"unadmitted vanilla"):
            m.validate(pin_path=m.VANILLA_PIN,values_path=m.VANILLA_VALUES,
                expected_type="VANILLA",expected_version="26.3",
                expected_selector="image",
                expected_world_path="/opt/tests/collage-vanilla-263-world")

if __name__=="__main__":
    unittest.main()
