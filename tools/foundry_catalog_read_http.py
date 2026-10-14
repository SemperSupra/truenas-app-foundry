#!/usr/bin/env python3
"""Loopback-only read-only reference HTTP adapter for the Foundry Catalog contract.

This is a reusable PUBLIC-SAFE adapter, NOT a released TrueNAS product, web UI,
TLS terminator, source fetcher, credential issuer, target planner or mutator.
Serves precomputed/pinned local indexes with a private bearer token file.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import stat
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import foundry_catalog_federation as federation

SCHEMA = "truenas-foundry-catalog-query/v0"
PATHS = {
    "/v0/catalog/apps": ("list", set()),
    "/v0/catalog/show": ("show", {"package_id"}),
    "/v0/catalog/resolve": ("resolve", {"package_id", "version", "revision", "digest"}),
}


class ReadGatewayError(ValueError):
    pass


def load_bearer(path: Path) -> str:
    if path.is_symlink():
        raise ReadGatewayError("secret must not be a symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ReadGatewayError("secret must be an owner-only regular file")
    secret = path.read_bytes().removesuffix(b"\n")
    if not (32 <= len(secret) <= 256 and secret.isascii() and
            all(33 <= char <= 126 for char in secret)):
        raise ReadGatewayError("secret must be 32-256 printable ASCII bytes")
    return secret.decode("ascii")


class ReadGateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, rows: list[dict], bearer: str, bind: str = "127.0.0.1", port: int = 0):
        if bind != "127.0.0.1":
            raise ReadGatewayError("reference server may listen only on loopback")
        if not isinstance(bearer, str) or len(bearer) < 32:
            raise ReadGatewayError("a sufficiently long bearer is required")
        self.rows = tuple(dict(row) for row in rows)
        self.bearer = bearer
        super().__init__((bind, port), ReadHandler)


class ReadHandler(BaseHTTPRequestHandler):
    # Close each response: avoid request-body/keepalive ambiguity.
    protocol_version = "HTTP/1.0"
    server_version = "FoundryCatalogRead/0"

    def log_message(self, format, *args):
        # Avoid logging client-controlled query parameters or authorization data.
        return

    def respond(self, status: int, payload: dict, *, challenge: bool = False) -> None:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        if challenge:
            self.send_header("WWW-Authenticate", 'Bearer realm="Foundry Catalog"')
        self.end_headers()
        self.wfile.write(data)

    def authorized(self) -> bool:
        headers = self.headers.get_all("Authorization", [])
        return len(headers) == 1 and hmac.compare_digest(
            headers[0], "Bearer " + self.server.bearer
        )

    def do_GET(self):
        if not self.authorized():
            self.respond(401, {"error": "unauthorized"}, challenge=True)
            return
        if self.headers.get("Content-Length") not in (None, "0"):
            self.respond(400, {"error": "GET request body not supported"})
            return
        if len(self.path) > 4096:
            self.respond(400, {"error": "request path too large"})
            return
        try:
            parsed = urlsplit(self.path)
            if parsed.fragment or parsed.path not in PATHS:
                self.respond(404, {"error": "not found"})
                return
            operation, allowed = PATHS[parsed.path]
            pairs = parse_qsl(parsed.query, keep_blank_values=True,
                              strict_parsing=True, max_num_fields=4)
            params = dict(pairs)
            if len(params) != len(pairs) or set(params) != allowed:
                raise ReadGatewayError("unexpected, missing or repeated query parameters")
            if any(len(k) > 64 or not v or len(v) > 512 for k, v in pairs):
                raise ReadGatewayError("invalid query parameter")
            result = federation.query(self.server.rows, operation, **params)
        except (ValueError, federation.CatalogIdentityError) as exc:
            self.respond(400, {"error": "invalid or ambiguous source selection"})
            return
        self.respond(200, result)

    def reject_write(self):
        self.respond(405, {"error": "read-only endpoint"})

    do_POST = reject_write
    do_PUT = reject_write
    do_PATCH = reject_write
    do_DELETE = reject_write
    do_OPTIONS = reject_write
    do_HEAD = reject_write


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ReadGatewayError("port must be 1-65535")
        rows = federation.load_catalogs(args.source)
        token = load_bearer(args.token_file)
        with ReadGateway(rows, token, port=args.port) as server:
            print(json.dumps({"status": "READ_ONLY", "bind": "127.0.0.1",
                              "port": args.port, "sources": len(rows)}, sort_keys=True),
                  flush=True)
            server.serve_forever()
        return 0
    except (ReadGatewayError, federation.CatalogIdentityError, OSError,
            UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
