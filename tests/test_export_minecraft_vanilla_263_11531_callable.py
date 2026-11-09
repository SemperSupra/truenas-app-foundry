"""Source-only callable workflow boundary for exact versioned Foundry export."""
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class CallableExportContractTests(unittest.TestCase):
    def setUp(self):
        self.source=(ROOT/".github/workflows/export-minecraft-vanilla-263-11531-t6-control.yml").read_text()
    def test_strict_reusable_producer_and_hash(self):
        y=self.source
        self.assertIn("workflow_call:",y)
        self.assertIn("foundry_ref:",y)
        self.assertIn("target_version:",y)
        self.assertIn('[[ "$ref" =~ ^[0-9a-f]{40}$ ]]',y)
        self.assertIn('test "$target" = \'25.04.2.6\'',y)
        self.assertIn("repository: SemperSupra/truenas-app-foundry",y)
        self.assertIn("ref: ${{ steps.src.outputs.ref }}",y)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_REF"',y)
        self.assertIn('test "$ref" = "${{ steps.src.outputs.ref }}"',y)
    def test_exact_download_artifact_contract(self):
        y=self.source
        self.assertIn("native-11531-control/control.json",y)
        self.assertIn("minecraft-vanilla263-truenas-250426-11531-signed-source-candidate",y)
        self.assertIn("if-no-files-found: error",y)
        self.assertIn("render-parity.json",y)
        self.assertIn("SOURCE_RENDER_CANONICAL_COMPOSE_IDENTICAL",y)
        self.assertIn("c[\"physical_truenas_apply\"]==\"HOLD\"",y)
    def test_no_direct_native_guest_authority(self):
        y=self.source
        self.assertNotIn("workflow_dispatch: [{",y)
        self.assertNotIn("gh workflow run",y)
        self.assertNotIn("--physical-apply",y)
        self.assertNotIn("DOCKER_HOST",y)
        self.assertNotIn("secrets.",y)

if __name__=="__main__":unittest.main()
