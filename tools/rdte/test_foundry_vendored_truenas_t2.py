"""Provenance and run-selector tests for source-verbatim public TrueNAS KVM T2."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).parent/"vendor/truenas-kvm"
MANIFEST = ROOT/"SOURCE-PROVENANCE.json"

class VendoredSourceExactness(unittest.TestCase):
    def test_all_source_blobs_match_pinned_origin(self):
        m=json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(m["source_commit"],"8744304c3c0a332460b1c5db97a2fb1e9562b222")
        self.assertEqual(m["supported_rung"],"t2")
        self.assertTrue(m["no_product_F0_F5_claim"])
        self.assertEqual(len(m["files"]),6)
        for path, expected in m["files"].items():
            with self.subTest(path=path):
                got=subprocess.check_output(["git","hash-object",str(ROOT/path)],text=True).strip()
                self.assertEqual(got,expected)

    def test_t2_client_and_release_profile_are_exact(self):
        targets=json.loads((ROOT/"config/truenas-rdte-targets.json").read_text())
        t=next(v for v in targets["targets"] if v["version"]=="25.04.2.6")
        self.assertEqual(t["iso_name"],"TrueNAS-SCALE-25.04.2.6.iso")
        self.assertEqual(t["sha256_url"],t["iso_url"]+".sha256")
        self.assertEqual(t["system_version"],"TrueNAS-25.04.2.6")
        self.assertEqual(t["installer_rpc_path"],"/")
        self.assertEqual(t["installer_rpc_guest_port"],80)

if __name__=="__main__":
    unittest.main()
