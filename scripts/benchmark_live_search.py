"""Benchmark the live FastAPI search endpoint."""

import argparse
import statistics
import time

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_QUERY = "throughput"
DEFAULT_REQUESTS = 100


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure live HTTP search latency."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument(
        "--requests",
        type=parse_positive_int,
        default=DEFAULT_REQUESTS,
    )
    parser.add_argument(
        "--limit",
        type=parse_positive_int,
        default=10,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    latencies: list[float] = []

    with httpx.Client(base_url=args.base_url, timeout=10.0) as client:
        warmup = client.get(
            "/api/v1/search",
            params={"q": args.query, "limit": args.limit},
        )
        warmup.raise_for_status()
        result_count = warmup.json()["total_results"]

        for _ in range(args.requests):
            started = time.perf_counter()
            response = client.get(
                "/api/v1/search",
                params={"q": args.query, "limit": args.limit},
            )
            response.raise_for_status()
            latencies.append((time.perf_counter() - started) * 1000)

    print("Live search benchmark")
    print(f"Query: {args.query}")
    print(f"Matching documents: {result_count}")
    print(f"Requests: {args.requests}")
    print(f"p50: {statistics.median(latencies):.3f}ms")
    print(f"p95: {percentile(latencies, 0.95):.3f}ms")
    print(f"Max: {max(latencies):.3f}ms")
    return 0


def percentile(values: list[float], percentile_value: float) -> float:
    rank = max(1, int(len(values) * percentile_value + 0.999999))
    return sorted(values)[rank - 1]


if __name__ == "__main__":
    raise SystemExit(main())
