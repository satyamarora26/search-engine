"""Benchmark the live FastAPI -> Celery -> PostgreSQL -> Redis flow."""

import argparse
import time
from uuid import uuid4

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCUMENTS = 500
DEFAULT_TIMEOUT_SECONDS = 60.0


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure live bulk ingestion through the local services."
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="FastAPI base URL.",
    )
    parser.add_argument(
        "--documents",
        type=parse_positive_int,
        default=DEFAULT_DOCUMENTS,
        help="Documents to submit in one bulk job.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Maximum seconds to wait for the Celery job.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    marker = uuid4().hex
    payload = {
        "documents": [
            {
                "title": f"Live throughput document {index}",
                "content": (
                    f"live throughput async celery document {index} {marker}"
                ),
                "url": f"https://throughput.example/{marker}/{index}",
            }
            for index in range(args.documents)
        ]
    }

    with httpx.Client(base_url=args.base_url, timeout=15.0) as client:
        started = time.perf_counter()
        accepted = client.post("/api/v1/documents/bulk", json=payload)
        accepted.raise_for_status()
        job = accepted.json()

        while True:
            status_response = client.get(job["status_url"])
            status_response.raise_for_status()
            status = status_response.json()
            if status["status"] in {"SUCCESS", "FAILURE"}:
                break
            if time.perf_counter() - started > args.timeout:
                raise RuntimeError(f"Celery job timed out: {status}")
            time.sleep(0.05)

        elapsed_seconds = time.perf_counter() - started
        search = client.get(
            "/api/v1/search",
            params={"q": marker, "limit": 10},
        )
        search.raise_for_status()

    result = status.get("result") or {}
    print("Live ingestion benchmark")
    print(f"Status: {status['status']}")
    print(f"Documents: {args.documents}")
    print(f"Elapsed: {elapsed_seconds:.3f}s")
    print(f"Documents/minute: {args.documents / elapsed_seconds * 60:.1f}")
    print(f"Imported: {result.get('imported_count')}")
    print(f"Failed: {result.get('failed_count')}")
    print(f"Search matches: {search.json()['total_results']}")
    return 0 if status["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
