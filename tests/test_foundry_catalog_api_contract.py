"""Ensure the API contract matches the already-tested offline query engine."""
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
api = json.loads((ROOT / "schemas/foundry-catalog-read-api-v0.openapi.json").read_text())
spec = importlib.util.spec_from_file_location(
    "foundry_catalog_federation", ROOT / "tools/foundry_catalog_federation.py"
)
federation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(federation)


def fixture():
    return [{
        "schema": federation.SCHEMA,
        "publisher": "foundry.example",
        "source": "main",
        "uri": "https://example.org/foundry.git",
        "revision": "a" * 40,
        "apps": [{"train": "community", "name": "test", "version": "1.0.0",
                  "path": "fixtures/foundry-rdte-probe",
                  "source_tree_sha256": "sha256:" + "b" * 64}]
    }]


class ReadOnlyApiContractTests(unittest.TestCase):
    def test_http_contract_has_no_mutators(self):
        self.assertEqual(api["openapi"], "3.1.0")
        self.assertEqual(api["security"], [{"bearerAuth": []}])
        self.assertEqual(set(api["paths"]), {
            "/v0/catalog/apps", "/v0/catalog/show", "/v0/catalog/resolve"
        })
        for endpoint in api["paths"].values():
            self.assertEqual(set(endpoint), {"get"})
            self.assertEqual(
                endpoint["get"]["responses"]["200"]["content"]["application/json"]["schema"].keys(),
                {"$ref"})

    def test_all_returned_fields_have_a_declared_read_schema(self):
        rows = federation.federate(fixture())
        selection = {"package_id": rows[0]["package_id"], "version": rows[0]["version"],
                     "revision": rows[0]["source_revision"],
                     "digest": rows[0]["source_tree_sha256"]}
        source_fields = set(api["components"]["schemas"]["SourceApp"]["properties"])
        for action, schema in [
            (federation.query(rows, "list"), "ListResult"),
            (federation.query(rows, "show", package_id=selection["package_id"]), "ShowResult"),
            (federation.query(rows, "resolve", **selection), "ResolveResult"),
        ]:
            defined = api["components"]["schemas"][schema]
            self.assertEqual(set(action), set(defined["properties"]))
            self.assertEqual(set(action), set(defined["required"]))
            apps = action.get("apps", [action["app"]] if "app" in action else [])
            for entry in apps:
                self.assertEqual(set(entry), source_fields)
            if action["operation"] == "resolve":
                self.assertFalse(action["mutation_eligible"])

    def test_http_selection_arguments_match_query_signature(self):
        endpoints = {
            "/v0/catalog/apps": [],
            "/v0/catalog/show": ["package_id"],
            "/v0/catalog/resolve": ["package_id", "version", "revision", "digest"],
        }
        for path, expected in endpoints.items():
            names = [item["name"] for item in api["paths"][path]["get"]["parameters"]]
            self.assertEqual(names, expected)


if __name__ == "__main__":
    unittest.main()
