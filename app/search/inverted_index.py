from collections import Counter, defaultdict

from app.search.analyzer import BaseAnalyzer
from app.search.types import IndexedDocument, Posting


class InvertedIndex:
    def __init__(self, analyzer: BaseAnalyzer) -> None:
        self.analyzer = analyzer
        self._term_document_frequencies: dict[str, dict[int, int]] = defaultdict(dict)
        self._document_term_counts: dict[int, Counter[str]] = {}
        self._document_lengths: dict[int, int] = {}

    def add_document(self, document: IndexedDocument) -> None:
        self.remove_document(document.id)

        combined_text = f"{document.title} {document.title} {document.content}"
        terms = self.analyzer.analyze(combined_text)
        term_counts = Counter(terms)

        self._document_term_counts[document.id] = term_counts
        self._document_lengths[document.id] = len(terms)

        for term, frequency in term_counts.items():
            self._term_document_frequencies[term][document.id] = frequency

    def remove_document(self, document_id: int) -> None:
        term_counts = self._document_term_counts.pop(document_id, None)
        self._document_lengths.pop(document_id, None)

        if term_counts is None:
            return

        for term in term_counts:
            document_frequencies = self._term_document_frequencies.get(term)
            if document_frequencies is None:
                continue
            document_frequencies.pop(document_id, None)
            if not document_frequencies:
                self._term_document_frequencies.pop(term, None)

    def get_postings(self, term: str) -> list[Posting]:
        document_frequencies = self._term_document_frequencies.get(term, {})
        return [
            Posting(document_id=document_id, term_frequency=frequency)
            for document_id, frequency in sorted(document_frequencies.items())
        ]

    def document_frequency(self, term: str) -> int:
        return len(self._term_document_frequencies.get(term, {}))

    def term_frequency(self, document_id: int, term: str) -> int:
        return self._document_term_counts.get(document_id, Counter()).get(term, 0)

    def document_length(self, document_id: int) -> int:
        return self._document_lengths.get(document_id, 0)

    def average_document_length(self) -> float:
        if not self._document_lengths:
            return 0.0
        return sum(self._document_lengths.values()) / len(self._document_lengths)

    def document_count(self) -> int:
        return len(self._document_lengths)

    def unique_term_count(self) -> int:
        return len(self._term_document_frequencies)
