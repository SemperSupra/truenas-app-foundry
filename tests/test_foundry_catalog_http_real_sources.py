"""Live HTTP loopback over three independently sourced exact-revision apps.

Requires two Git checkouts passed through environment. No system mutation.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import foundry_catalog_real_three_source as proof
import foundry_catalog_read_http as http_catalog


@unittest.skipUnless(os.environ.get("FOUNDRY_OFFICIAL_CHECKOUT") and
                     os.environ.get("FOUNDRY_EXTERNAL_CHECKOUT"),
                     "requires pinned upstream checkouts")
class RealSourceHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = proof.prove(
            Path(os.environ["FOUNDRY_OFFICIAL_CHECKOUT"]),
            Path(os.environ["FOUNDRY_EXTERNAL_CHECKOUT"]),
            json.loads((ROOT / "fixtures/catalog-source-registrations/codefuturist-jellyfin.json").read_text()),
        )
        cls.rows = result["apps"]
        cls.token = "read_only_integration_" + "x" * 44
        cls.server = http_catalog.ReadGateway(cls.rows, cls.token)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def request(self, path, auth=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Authorization": "Bearer " + self.token} if auth else {}
        conn.request("GET", path, headers=headers)
        reply = conn.getresponse()
        result = reply.status, json.loads(reply.read())
        conn.close()
        return result

    def test_real_three_provider_service(self):
        status, payload = self.request("/v0/catalog/apps")
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len({x["provider_id"] for x in payload["apps"]}), 3)
        self.assertEqual(
            len([x for x in payload["apps"] if x["package_id"].endswith("/jellyfin")]), 2
        )
        self.assertTrue(all(x["admission"] == "DISCOVERED_ONLY" for x in payload["apps"]))

    def test_real_source_resolve_is_read_only_and_publisher_exact(self):
        for row in self.rows:
            path = "/v0/catalog/resolve?" + urlencode({
                "package_id": row["package_id"], "version": row["version"],
                "revision": row["source_revision"],
                "digest": row["source_tree_sha256"],
            })
            status, resolved = self.request(path)
            self.assertEqual(status, 200)
            self.assertFalse(resolved["mutation_eligible"])
            self.assertEqual(resolved["app"]["provider_id"], row["provider_id"])

    def test_requires_token_and_never_returns_source_data_unauthenticated(self):
        code, payload = self.request("/v0/catalog/apps", auth=False)
        self.assertEqual(code, 401)
        self.assertEqual(payload, {"error": "unauthorized"})


if __name__ == "__main__":
    unittest.main()
