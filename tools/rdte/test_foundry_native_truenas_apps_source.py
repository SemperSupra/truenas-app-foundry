"""Exact source-qualified legacy platform Apps T4/T5 probes; no guest run here."""
from pathlib import Path
import subprocess,unittest
ROOT=Path(__file__).parent/"vendor/truenas-kvm"
SOURCES={
  "scripts/truenas_middleware_pool_probe.py":"51a2c43937062f8a30bd7c5dd0d2eaff49e1e285",
  "scripts/truenas_middleware_app_probe.py":"9f70f41b72888f0fed3e4a734353bfd448a6610d",
  "scripts/truenas_middleware_app_lifecycle_probe.py":"53dd7f391c7a10a236eec2b5981d90e14590d3a8",
}
class NativeAppSource(unittest.TestCase):
 def test_all_sources_match_reference_blobs(self):
  for p,h in SOURCES.items():
   with self.subTest(path=p):
    self.assertEqual(subprocess.check_output(["git","hash-object",str(ROOT/p)],text=True).strip(),h)
 def test_native_api_calls_and_exact_pinned_image(self):
  t=(ROOT/"scripts/truenas_middleware_app_probe.py").read_text()
  l=(ROOT/"scripts/truenas_middleware_app_lifecycle_probe.py").read_text()
  for s in ("app.create","app.query","app.stop","app.start","app.update","app.redeploy","app.delete","app.config"):
   with self.subTest(method=s):
    self.assertIn(s,t+l)
  self.assertIn("sha256:",t)
  self.assertIn("sha256:",l)
 def test_rungs_reuse_native_probe_from_existing_source(self):
  s=(ROOT/"scripts/gha_kvm_truenas_rdte.sh").read_text()
  for x in ("truenas_middleware_pool_probe.py","truenas_middleware_app_probe.py","truenas_middleware_app_lifecycle_probe.py"):
   self.assertIn(x,s)
  for x in ('"t4"','"t5"','--target-version'):
   self.assertIn(x,s)
if __name__=="__main__":unittest.main()
