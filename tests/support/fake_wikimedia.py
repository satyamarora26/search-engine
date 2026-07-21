from __future__ import annotations

import argparse
from collections import Counter
from contextlib import AbstractContextManager
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit


FIRST_CATEGORY_PAGE = {
    "continue": {"cmcontinue": "page|second", "continue": "-||"},
    "query": {
        "categorymembers": [
            {"pageid": 101, "ns": 0, "title": "Unique search article"},
            {"pageid": 102, "ns": 0, "title": "Existing search article"},
        ]
    },
}

SECOND_CATEGORY_PAGE = {
    "batchcomplete": True,
    "query": {
        "categorymembers": [
            {"pageid": 103, "ns": 0, "title": "Retry search article"},
            {"pageid": 104, "ns": 0, "title": "Missing search article"},
        ]
    },
}


class FakeWikimediaServer(AbstractContextManager["FakeWikimediaServer"]):
    """Small deterministic Action API and Core REST test boundary."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        search_token: str = "uniquewikipediacrawlterm",
    ) -> None:
        self.host = host
        self.port = port
        self.search_token = search_token
        self.request_log: list[dict[str, Any]] = []
        self._attempts: Counter[str] = Counter()
        self._lock = Lock()
        self.redirect_count = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def start(self) -> "FakeWikimediaServer":
        if self._server is not None:
            return self
        self._server = ThreadingHTTPServer(
            (self.host, self.port),
            _FakeWikimediaHandler,
        )
        self._server.fake_wikimedia = self  # type: ignore[attr-defined]
        self._thread = Thread(
            target=self._server.serve_forever,
            name="fake-wikimedia",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None

    def __enter__(self) -> "FakeWikimediaServer":
        return self.start()

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()

    @property
    def authority(self) -> str:
        if self._server is None:
            raise RuntimeError("fake Wikimedia server is not running")
        return f"{self.host}:{self._server.server_address[1]}"

    @property
    def action_api_url(self) -> str:
        return f"http://{self.authority}/w/api.php"

    @property
    def rest_api_url(self) -> str:
        return f"http://{self.authority}/w/rest.php/v1"

    def record_request(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.request_log.append(record)

    def record_attempt(self, title: str) -> int:
        with self._lock:
            self._attempts[title] += 1
            return self._attempts[title]

    def record_redirect(self) -> None:
        with self._lock:
            self.redirect_count += 1

    def attempts_for(self, title: str) -> int:
        with self._lock:
            return self._attempts[title]

    def article_html(self, title: str) -> str:
        token = self.search_token if title == "Unique search article" else title
        return f"""<!doctype html>
<html><body>
  <section data-mw-section-id="0">
    <p>{title} is a deterministic Wikipedia crawler fixture with {token}.
    This long paragraph provides stable searchable prose for the integration
    test and demonstrates that HTML is extracted before indexing.</p>
  </section>
  <section data-mw-section-id="1">
    <h2>Search behavior</h2>
    <p>BM25 ranking uses this imported article content while the fake boundary
    records every request for redirect, retry, host, and user-agent checks.</p>
  </section>
</body></html>"""


class _FakeWikimediaHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        fake = self.server.fake_wikimedia  # type: ignore[attr-defined]
        parsed = urlsplit(self.path)
        user_agent = self.headers.get("User-Agent")
        fake.record_request(
            {
                "host": self.headers.get("Host"),
                "path": parsed.path,
                "query": parsed.query,
                "user_agent": user_agent,
                "method": "GET",
            }
        )
        if not user_agent:
            self._send_bytes(400, b"missing User-Agent", "text/plain")
            return

        if parsed.path == "/w/api.php":
            self._handle_action_api(fake, parse_qs(parsed.query))
            return
        if parsed.path.startswith("/w/rest.php/v1/page/"):
            self._handle_rest_api(fake, parsed)
            return
        self._send_bytes(404, b"unknown fake Wikimedia path", "text/plain")

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _handle_action_api(
        self,
        fake: FakeWikimediaServer,
        query: dict[str, list[str]],
    ) -> None:
        continuation = query.get("cmcontinue", [None])[0]
        payload = (
            SECOND_CATEGORY_PAGE
            if continuation == "page|second"
            else FIRST_CATEGORY_PAGE
        )
        self._send_json(payload)

    def _handle_rest_api(
        self,
        fake: FakeWikimediaServer,
        parsed: Any,
    ) -> None:
        path_title = parsed.path.removeprefix("/w/rest.php/v1/page/")
        encoded_title = path_title.removesuffix("/html")
        title = unquote(encoded_title).replace("_", " ")
        attempt = fake.record_attempt(title)
        query = parse_qs(parsed.query)

        if title == "Unique search article" and query.get("resolved") != ["1"]:
            fake.record_redirect()
            self.send_response(302)
            self.send_header("Location", "?resolved=1")
            self.end_headers()
            return
        if title == "Retry search article" and attempt == 1:
            self.send_response(503)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        if title == "Missing search article":
            self._send_bytes(404, b"missing", "text/plain")
            return
        if title in {
            "Unique search article",
            "Existing search article",
            "Retry search article",
        }:
            self._send_html(fake.article_html(title))
            return
        self._send_bytes(404, b"unknown fake article", "text/plain")

    def _send_json(self, payload: dict[str, Any]) -> None:
        self._send_bytes(
            200,
            json.dumps(payload).encode("utf-8"),
            "application/json",
        )

    def _send_html(self, html: str) -> None:
        self._send_bytes(200, html.encode("utf-8"), "text/html")

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = FakeWikimediaServer(host=args.host, port=args.port).start()
    print(
        f"fake Wikimedia server listening on {server.action_api_url} and "
        f"{server.rest_api_url}",
        flush=True,
    )
    try:
        while True:
            server._thread.join(timeout=60)  # type: ignore[union-attr]
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
