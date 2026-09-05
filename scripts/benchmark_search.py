"""Benchmark in-memory indexing and BM25 search on a deterministic corpus."""

import argparse
import math
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.search.corpus import load_documents_from_json
from app.search.engine import SearchEngine
from app.search.types import IndexedDocument

DEFAULT_DOCUMENTS = 20_000
DEFAULT_QUERIES = 500
BENCHMARK_QUERIES = (
    "distributed systems",
    "BM25 ranking",
    "search indexing",
    "caching retrieval",
)


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure deterministic in-memory search performance."
    )
    parser.add_argument(
        "--documents",
        type=parse_positive_int,
        default=DEFAULT_DOCUMENTS,
        help="Number of synthetic documents to index when --corpus is omitted.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        help="Optional JSON corpus; when provided, benchmark its documents.",
    )
    parser.add_argument(
        "--queries",
        type=parse_positive_int,
        default=DEFAULT_QUERIES,
        help="Number of timed search queries.",
    )
    return parser


def build_documents(count: int) -> list[IndexedDocument]:
    return [
        IndexedDocument(
            id=document_id,
            title=f"Distributed systems guide {document_id}",
            content=(
                f"distributed systems search indexing caching document number "
                f"{document_id} with BM25 ranking and retrieval"
            ),
        )
        for document_id in range(count)
    ]


def load_benchmark_documents(
    corpus_path: Path | None,
    document_count: int,
) -> list[IndexedDocument]:
    if corpus_path is not None:
        return load_documents_from_json(corpus_path)
    return build_documents(document_count)


def percentile(values: list[float], percentile_value: float) -> float:
    rank = max(1, math.ceil(len(values) * percentile_value))
    return sorted(values)[rank - 1]


def main() -> int:
    args = build_parser().parse_args()
    documents = load_benchmark_documents(args.corpus, args.documents)

    start = time.perf_counter()
    engine = SearchEngine()
    for document in documents:
        engine.index_document(document)
    build_seconds = time.perf_counter() - start

    for query in BENCHMARK_QUERIES:
        engine.search(query, limit=10)

    latencies: list[float] = []
    for query_number in range(args.queries):
        query = BENCHMARK_QUERIES[query_number % len(BENCHMARK_QUERIES)]
        start = time.perf_counter()
        engine.search(query, limit=10)
        latencies.append((time.perf_counter() - start) * 1000)

    print("Search performance benchmark")
    print(f"Documents: {len(documents)}")
    print(f"Unique terms: {engine.index.unique_term_count()}")
    print(f"Timed queries: {args.queries}")
    print(f"Index build: {build_seconds:.3f}s")
    print(f"Query p50: {statistics.median(latencies):.3f}ms")
    print(f"Query p95: {percentile(latencies, 0.95):.3f}ms")
    print(f"Query max: {max(latencies):.3f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
