"""Public bootstrap-source negative oracles; no source executing at test import."""
from pathlib import Path
import unittest

SCRIPT = Path(__file__).with_name("direct_truenas_t0.sh")

class DirectNativeGuestBootstrapContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s=SCRIPT.read_text(encoding="utf-8")

    def test_vendor_media_exact_pinned_sidecar(self):
        for x in ("25.04.2.6", "TrueNAS-SCALE-25.04.2.6.iso",
                  'SHA_URL="${ISO_URL}.sha256"', '"$OBSERVED_SHA" == "$EXPECTED_SHA"'):
            self.assertIn(x,self.s)
        self.assertNotIn("latest.iso",self.s)

    def test_no_agent_dispatch_runtime_or_secrets(self):
        self.assertNotIn("agent-dispatch.service",self.s)
        self.assertNotIn("gh auth",self.s)
        self.assertNotIn("GITHUB_TOKEN",self.s)
        self.assertNotIn("ssh ",self.s)

    def test_bounded_guest_clean_exit(self):
        for x in ("-enable-kvm", "-smp", "-m", "24G", "seq 1 220",
                  "trap receipt EXIT", 'sudo -n kill "$QEMU_PID"',
                  'sudo -n rm -rf -- "$STATE_DIR"',
                  'zero_residue', "native_app_f0_f5_accepted"):
            self.assertIn(x,self.s)

    def test_serial_is_vendor_grub_and_not_mock(self):
        for x in ("xorriso -boot_image any keep", "console=ttyS0,115200",
                  "truenas-installer|TrueNAS Installer|Install/Upgrade",
                  'CLASSIFICATION="SUPPORTED"'):
            self.assertIn(x,self.s)
        self.assertNotIn("echo TrueNAS",self.s)

if __name__=="__main__":
    unittest.main()
