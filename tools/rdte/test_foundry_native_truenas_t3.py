"""Exact immutable T3 pool-oracle source; no Agent Dispatch runtime."""
from pathlib import Path
import subprocess,unittest,json
ROOT=Path(__file__).parent/"vendor/truenas-kvm"
class NativeT3SourceContract(unittest.TestCase):
 def test_pool_probe_pinned_public_sha(self):
  p=ROOT/"scripts/truenas_middleware_pool_probe.py"
  self.assertEqual(subprocess.check_output(["git","hash-object",str(p)],text=True).strip(),"51a2c43937062f8a30bd7c5dd0d2eaff49e1e285")
 def test_pool_probe_uses_native_middleware(self):
  s=(ROOT/"scripts/truenas_middleware_pool_probe.py").read_text()
  self.assertIn("truenas_middleware_ddp_probe",s)
  self.assertIn("pool",s)
 def test_t3_baseline_immutable(self):
  m=json.loads((ROOT/"SOURCE-PROVENANCE.json").read_text())
  self.assertEqual(m["source_commit"],"8744304c3c0a332460b1c5db97a2fb1e9562b222")
  self.assertEqual(m["supported_rung"],"t2")
if __name__=="__main__": unittest.main()
