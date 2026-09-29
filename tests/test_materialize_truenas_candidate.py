import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "materialize_truenas_candidate",
    ROOT / "tools" / "materialize_truenas_candidate.py",
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class MaterializeTrueNASCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.upstream = self.root / "upstream"
        self.repo.mkdir()
        self.upstream.mkdir()

        self.library = (
            self.upstream
            / "ix-dev"
            / "community"
            / "oracle"
            / "templates"
            / "library"
            / "base_v9_9_9"
        )
        self.library.mkdir(parents=True)
        (self.library / "alpha.py").write_text("alpha\n", encoding="utf-8")
        (self.library / "beta.py").write_text("beta\n", encoding="utf-8")
        self.library_hash = m.truenas_directory_hash(self.library)

        self.source = self.repo / "candidates" / "demo" / "ix-dev" / "community" / "demo"
        (self.source / "templates").mkdir(parents=True)
        (self.source / "app.yaml").write_text(
            "name: demo\n"
            "lib_version: 9.9.9\n"
            f"lib_version_hash: {self.library_hash}\n",
            encoding="utf-8",
        )
        (self.source / "templates" / "docker-compose.yaml").write_text(
            "{{ demo }}\n", encoding="utf-8"
        )

        self.manifest = self.repo / "candidates" / "demo" / "candidate.json"
        self.manifest.write_text(
            (
                "{\n"
                '  "schema_version": 1,\n'
                '  "candidate": "demo",\n'
                '  "source_path": "candidates/demo/ix-dev/community/demo",\n'
                '  "source_materializer": {\n'
                '    "repository": "https://example.invalid/truenas/apps.git",\n'
                f'    "commit": "{"a" * 40}",\n'
                '    "train": "community",\n'
                '    "lib_version": "9.9.9",\n'
                f'    "lib_hash": "{self.library_hash}"\n'
                "  }\n"
                "}\n"
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolves_library_by_actual_hash(self):
        source, actual = m.resolve_library(
            self.upstream,
            train="community",
            version="9.9.9",
            expected_hash=self.library_hash,
            destination=self.root / "not-created",
        )
        self.assertEqual(source, self.library.resolve())
        self.assertEqual(actual, self.library_hash)

    def test_build_desired_injects_exact_library(self):
        built = m.build_desired(
            self.repo, self.manifest, self.upstream, self.root / "build"
        )
        injected = (
            built["desired"]
            / "templates"
            / "library"
            / "base_v9_9_9"
        )
        self.assertTrue(injected.is_dir())
        self.assertEqual(m.truenas_directory_hash(injected), self.library_hash)
        self.assertEqual(built["library_hash"], self.library_hash)

    def test_source_candidate_with_vendored_library_is_rejected(self):
        leaked = self.source / "templates" / "library" / "base_v9_9_9"
        leaked.mkdir(parents=True)
        (leaked / "bad.py").write_text("generated\n", encoding="utf-8")
        with self.assertRaisesRegex(m.MaterializationError, "must stay lean"):
            m.build_desired(
                self.repo, self.manifest, self.upstream, self.root / "build"
            )

    def test_action_is_create_noop_or_drift_refuse(self):
        built = m.build_desired(
            self.repo, self.manifest, self.upstream, self.root / "build"
        )
        desired = built["desired"]
        fp = built["desired_fingerprint"]
        destination = self.root / "destination"

        action, observed = m.determine_action(destination, fp)
        self.assertEqual((action, observed), ("CREATE", ""))

        shutil.copytree(desired, destination)
        action, observed = m.determine_action(destination, fp)
        self.assertEqual(action, "NOOP")
        self.assertEqual(observed, fp)

        (destination / "app.yaml").write_text("drift\n", encoding="utf-8")
        action, _ = m.determine_action(destination, fp)
        self.assertEqual(action, "DRIFT_REFUSE")

    def test_symlink_is_not_counted_as_true_file_for_library_hash(self):
        target = self.library / "alpha.py"
        link = self.library / "alpha-link.py"
        try:
            link.symlink_to(target.name)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertEqual(m.truenas_directory_hash(self.library), self.library_hash)


if __name__ == "__main__":
    unittest.main()
