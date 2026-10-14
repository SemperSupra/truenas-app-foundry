"""Live loopback HTTP contract qualification, without TrueNAS or external network."""
from __future__ import annotations

import http.client
import importlib.util
import json
import pathlib
import tempfile
import threading
import unittest
from urllib.parse import urlencode

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "foundry_catalog_read_http", ROOT / "tools/foundry_catalog_read_http.py"
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def source(publisher):
    return {
        "schema": mod.federation.SCHEMA,
        "publisher": publisher,
        "source": "catalog",
        "uri": "https://example.org/catalog.git",
        "revision": "a" * 40,
        "apps": [{
            "train": "community", "name": "jellyfin", "version": "1.0.0",
            "path": "ix-dev/community/jellyfin",
            "source_tree_sha256": "sha256:" + "b" * 64,
        }],
    }


class ReadHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = "test_read_only_bearer_" + "x" * 40
        cls.rows = mod.federation.federate([source("official.example"), source("external.example")])
        cls.server = mod.ReadGateway(cls.rows, cls.token)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def request(self, method, uri, *, authorized=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        head = dict(headers or {})
        if authorized:
            head["Authorization"] = "Bearer " + self.token
        conn.request(method, uri, headers=head)
        response = conn.getresponse()
        raw = response.read()
        result = (response.status, json.loads(raw), dict(response.getheaders()))
        conn.close()
        return result

    def test_rejects_unauthorized_requests(self):
        code, result, headers = self.request("GET", "/v0/catalog/apps", authorized=False)
        self.assertEqual(code, 401)
        self.assertEqual(result, {"error": "unauthorized"})
        self.assertIn("WWW-Authenticate", headers)
        self.assertNotIn("apps", result)

    def test_list_show_resolve_share_canonical_read_logic(self):
        code, listed, headers = self.request("GET", "/v0/catalog/apps")
        self.assertEqual(code, 200)
        self.assertEqual(listed, mod.federation.query(self.rows, "list"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        row = listed["apps"][0]
        show_uri = "/v0/catalog/show?" + urlencode({"package_id": row["package_id"]})
        code, shown, _ = self.request("GET", show_uri)
        self.assertEqual(code, 200)
        self.assertEqual(shown, mod.federation.query(
            self.rows, "show", package_id=row["package_id"]
        ))
        resolve_uri = "/v0/catalog/resolve?" + urlencode({
            "package_id": row["package_id"], "version": row["version"],
            "revision": row["source_revision"], "digest": row["source_tree_sha256"]
        })
        code, resolved, _ = self.request("GET", resolve_uri)
        self.assertEqual(code, 200)
        self.assertEqual(resolved["app"], row)
        self.assertFalse(resolved["mutation_eligible"])

    def test_publisher_name_collision_not_merged(self):
        _, payload, _ = self.request("GET", "/v0/catalog/apps")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len({x["provider_id"] for x in payload["apps"]}), 2)

    def test_rejects_repeat_unknown_and_missing_parameters(self):
        for uri in [
            "/v0/catalog/show",
            "/v0/catalog/show?package_id=a&package_id=b",
            "/v0/catalog/show?package_id=a&install=true",
            "/v0/catalog/apps?install=true",
            "/v0/catalog/resolve?package_id=only",
            "/v0/catalog/apps?bad",
        ]:
            with self.subTest(uri=uri):
                self.assertEqual(self.request("GET", uri)[0], 400)

    def test_no_mutating_method_is_available(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                code, result, _ = self.request(method, "/v0/catalog/apps")
                self.assertEqual(code, 405)
                self.assertEqual(result["error"], "read-only endpoint")

    def test_head_cannot_access_data(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request("HEAD", "/v0/catalog/apps", headers={
            "Authorization": "Bearer " + self.token
        })
        response = conn.getresponse()
        self.assertEqual(response.status, 405)
        conn.close()

    def test_no_general_file_or_command_surface(self):
        for uri in ("/etc/passwd", "/v0/exec", "/v0/install", "/v0/catalog/../../secret"):
            self.assertEqual(self.request("GET", uri)[0], 404)

    def test_cannot_bind_reference_server_to_external_interface(self):
        with self.assertRaises(mod.ReadGatewayError):
            mod.ReadGateway(self.rows, self.token, bind="0.0.0.0")


class TokenFileTests(unittest.TestCase):
    def test_owner_only_secret_file(self):
        with tempfile.TemporaryDirectory() as d:
            file = pathlib.Path(d) / "token"
            file.write_text("s" * 42 + "\n")
            file.chmod(0o600)
            self.assertEqual(mod.load_bearer(file), "s" * 42)
            file.chmod(0o644)
            with self.assertRaises(mod.ReadGatewayError):
                mod.load_bearer(file)

    def test_short_secret_file_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            file = pathlib.Path(d) / "token"
            file.write_text("short")
            file.chmod(0o600)
            with self.assertRaises(mod.ReadGatewayError):
                mod.load_bearer(file)

    def test_symlink_secret_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            source = pathlib.Path(d) / "token"
            link = pathlib.Path(d) / "link"
            source.write_text("z" * 42)
            source.chmod(0o600)
            link.symlink_to(source)
            with self.assertRaises(mod.ReadGatewayError):
                mod.load_bearer(link)


if __name__ == "__main__":
    unittest.main()
