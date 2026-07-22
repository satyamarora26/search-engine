from collections import Counter, defaultdict
from collections.abc import Sequence

from app.search.analyzer import BaseAnalyzer
from app.search.types import IndexedDocument, Posting, SearchScope

SCOPES: tuple[SearchScope, ...] = ("all", "title", "content")


class InvertedIndex:
    def __init__(self, analyzer: BaseAnalyzer) -> None:
        self.analyzer = analyzer
        self._term_document_frequencies = {
            scope: defaultdict(dict) for scope in SCOPES
        }
        self._document_term_counts = {scope: {} for scope in SCOPES}
        self._document_terms = {scope: {} for scope in SCOPES}
        self._document_lengths = {scope: {} for scope in SCOPES}

    def add_document(self, document: IndexedDocument) -> None:
        self.remove_document(document.id)

        scoped_terms = {
            "all": self.analyzer.analyze(
                f"{document.title} {document.title} {document.content}"
            ),
            "title": self.analyzer.analyze(document.title),
            "content": self.analyzer.analyze(document.content),
        }
        for scope, terms in scoped_terms.items():
            term_counts = Counter(terms)
            self._document_term_counts[scope][document.id] = term_counts
            self._document_terms[scope][document.id] = terms
            self._document_lengths[scope][document.id] = len(terms)

            for term, frequency in term_counts.items():
                self._term_document_frequencies[scope][term][document.id] = (
                    frequency
                )

    def remove_document(self, document_id: int) -> None:
        if document_id not in self._document_term_counts["all"]:
            return

        for scope in SCOPES:
            term_counts = self._document_term_counts[scope].pop(document_id)
            self._document_terms[scope].pop(document_id, None)
            self._document_lengths[scope].pop(document_id, None)

            for term in term_counts:
                document_frequencies = self._term_document_frequencies[scope].get(
                    term
                )
                if document_frequencies is None:
                    continue
                document_frequencies.pop(document_id, None)
                if not document_frequencies:
                    self._term_document_frequencies[scope].pop(term, None)

    def get_postings(
        self,
        term: str,
        scope: SearchScope = "all",
    ) -> list[Posting]:
        document_frequencies = self._term_document_frequencies[
            _validate_scope(scope)
        ].get(term, {})
        return [
            Posting(document_id=document_id, term_frequency=frequency)
            for document_id, frequency in sorted(document_frequencies.items())
        ]

    def document_frequency(
        self,
        term: str,
        scope: SearchScope = "all",
    ) -> int:
        return len(
            self._term_document_frequencies[_validate_scope(scope)].get(term, {})
        )

    def term_frequency(
        self,
        document_id: int,
        term: str,
        scope: SearchScope = "all",
    ) -> int:
        return self._document_term_counts[_validate_scope(scope)].get(
            document_id,
            Counter(),
        ).get(term, 0)

    def document_length(
        self,
        document_id: int,
        scope: SearchScope = "all",
    ) -> int:
        return self._document_lengths[_validate_scope(scope)].get(document_id, 0)

    def average_document_length(self, scope: SearchScope = "all") -> float:
        lengths = self._document_lengths[_validate_scope(scope)].values()
        if not lengths:
            return 0.0
        return sum(lengths) / len(lengths)

    def document_count(self, scope: SearchScope = "all") -> int:
        return len(self._document_lengths[_validate_scope(scope)])

    def unique_term_count(self, scope: SearchScope = "all") -> int:
        return len(self._term_document_frequencies[_validate_scope(scope)])

    def contains_phrase(
        self,
        document_id: int,
        phrase_terms: Sequence[str],
        scope: SearchScope = "all",
    ) -> bool:
        if not phrase_terms:
            return False
        validated_scope = _validate_scope(scope)
        if validated_scope == "all":
            return self._contains_phrase(
                document_id,
                phrase_terms,
                scope="title",
            ) or self._contains_phrase(document_id, phrase_terms, scope="content")
        return self._contains_phrase(document_id, phrase_terms, scope=validated_scope)

    def _contains_phrase(
        self,
        document_id: int,
        phrase_terms: Sequence[str],
        *,
        scope: SearchScope,
    ) -> bool:
        terms = self._document_terms[scope].get(document_id, [])
        phrase = list(phrase_terms)
        phrase_length = len(phrase)
        return any(
            terms[position : position + phrase_length] == phrase
            for position in range(len(terms) - phrase_length + 1)
        )


def _validate_scope(scope: SearchScope) -> SearchScope:
    if scope not in SCOPES:
        raise ValueError(
            f"Unsupported search scope '{scope}'. Expected 'all', 'title', or 'content'."
        )
    return scope
