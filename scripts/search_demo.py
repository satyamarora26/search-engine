import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.search.corpus import load_documents_from_json
from app.search.engine import SearchEngine
from app.search.types import IndexedDocument, SearchHit

DEFAULT_CORPUS_PATH = PROJECT_ROOT / "data" / "sample_corpus.json"


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search the local sample corpus.")
    parser.add_argument("--query", required=True, help="Search query text.")
    parser.add_argument(
        "--ranking",
        choices=("bm25", "tfidf"),
        default="bm25",
        help="Ranking algorithm to use.",
    )
    parser.add_argument(
        "--limit",
        type=parse_positive_int,
        default=5,
        help="Maximum number of results to show.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS_PATH,
        help="Path to a JSON corpus file.",
    )
    return parser


def build_engine(documents: list[IndexedDocument]) -> SearchEngine:
    engine = SearchEngine()
    for document in documents:
        engine.index_document(document)
    return engine


def format_results(
    query: str,
    ranking: str,
    hits: list[SearchHit],
    documents_by_id: dict[int, IndexedDocument],
) -> str:
    lines = [
        f"Query: {query}",
        f"Ranking: {ranking}",
        f"Results: {len(hits)}",
        "",
    ]

    if not hits:
        lines.append("No results found.")
        return "\n".join(lines)

    for position, hit in enumerate(hits, start=1):
        document = documents_by_id[hit.document_id]
        lines.append(f"{position}. {document.title}")
        lines.append(f"   Score: {hit.score:.3f}")
        lines.append(f"   Matched terms: {', '.join(hit.matched_terms)}")
        if document.url:
            lines.append(f"   URL: {document.url}")
        lines.append("")

    return "\n".join(lines).rstrip()


def main() -> int:
    args = build_parser().parse_args()

    documents = load_documents_from_json(args.corpus)
    documents_by_id = {document.id: document for document in documents}
    engine = build_engine(documents)
    hits = engine.search(args.query, ranking=args.ranking, limit=args.limit)

    print(format_results(args.query, args.ranking, hits, documents_by_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
