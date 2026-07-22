import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.search.corpus import load_documents_from_json
from app.search.evaluation import (
    DEFAULT_RANKINGS,
    EvaluationSummary,
    SearchEvaluator,
    load_evaluation_queries,
)
from app.search.engine import SearchEngine
from app.search.types import IndexedDocument

DEFAULT_CORPUS_PATH = PROJECT_ROOT / "data" / "sample_corpus.json"
DEFAULT_EVALUATION_PATH = PROJECT_ROOT / "data" / "search_evaluation.json"


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare search ranking quality on a judged corpus."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS_PATH,
        help="Path to a JSON document corpus.",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=DEFAULT_EVALUATION_PATH,
        help="Path to a JSON file with relevance judgments.",
    )
    parser.add_argument(
        "--k",
        type=parse_positive_int,
        default=3,
        help="Number of top results used for each metric.",
    )
    parser.add_argument(
        "--ranking",
        choices=DEFAULT_RANKINGS,
        action="append",
        help="Ranking to evaluate. Repeat to compare a selected set.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print each query's retrieved and relevant document IDs.",
    )
    return parser


def build_engine(documents: list[IndexedDocument]) -> SearchEngine:
    engine = SearchEngine()
    for document in documents:
        engine.index_document(document)
    return engine


def format_report(
    summaries: dict[str, EvaluationSummary],
    *,
    corpus_path: Path,
    queries_path: Path,
    details: bool = False,
) -> str:
    first_summary = next(iter(summaries.values()))
    metric_precision = f"Precision@{first_summary.k}"
    metric_recall = f"Recall@{first_summary.k}"
    lines = [
        "Search evaluation",
        f"Corpus: {corpus_path}",
        f"Judgments: {queries_path}",
        f"Queries: {first_summary.query_count}",
        f"Cutoff: {first_summary.k}",
        "",
        f"{'Ranking':<10} {metric_precision:>13} {metric_recall:>10} {'MRR':>8}",
        f"{'-' * 10} {'-' * 13} {'-' * 10} {'-' * 8}",
    ]

    for ranking, summary in summaries.items():
        label = "TF-IDF" if ranking == "tfidf" else ranking.upper()
        lines.append(
            f"{label:<10} {summary.precision_at_k:>13.3f} "
            f"{summary.recall_at_k:>10.3f} "
            f"{summary.mean_reciprocal_rank:>8.3f}"
        )

    if details:
        lines.extend(["", "Per-query details"])
        for ranking, summary in summaries.items():
            lines.append("")
            ranking_label = "TF-IDF" if ranking == "tfidf" else ranking.upper()
            lines.append("Ranking: " + ranking_label)
            for result in summary.query_results:
                retrieved = ", ".join(
                    str(document_id)
                    for document_id in result.retrieved_document_ids
                ) or "none"
                relevant = ", ".join(
                    str(document_id)
                    for document_id in sorted(result.relevant_document_ids)
                )
                lines.append(
                    f"- {result.query}: retrieved [{retrieved}], "
                    f"relevant [{relevant}], "
                    f"P@{summary.k}={result.precision_at_k:.3f}, "
                    f"RR={result.reciprocal_rank:.3f}"
                )

    return "\n".join(lines)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        documents = load_documents_from_json(args.corpus)
        queries = load_evaluation_queries(args.queries)
        summaries = SearchEvaluator(build_engine(documents)).evaluate_rankings(
            queries,
            rankings=tuple(args.ranking or DEFAULT_RANKINGS),
            k=args.k,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(
        format_report(
            summaries,
            corpus_path=args.corpus,
            queries_path=args.queries,
            details=args.details,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
