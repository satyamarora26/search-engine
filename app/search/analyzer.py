import re

from nltk.stem import PorterStemmer

DEFAULT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}


class BaseAnalyzer:
    def analyze(self, text: str) -> list[str]:
        raise NotImplementedError


class SimpleAnalyzer(BaseAnalyzer):
    def __init__(self, stopwords: set[str] | None = None) -> None:
        self.stopwords = stopwords if stopwords is not None else DEFAULT_STOPWORDS

    def analyze(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []

        normalized = text.lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        terms = normalized.split()
        return [term for term in terms if term not in self.stopwords]


class AdvancedAnalyzer(SimpleAnalyzer):
    def __init__(self, stopwords: set[str] | None = None) -> None:
        super().__init__(stopwords=stopwords)
        self.stemmer = PorterStemmer()

    def analyze(self, text: str) -> list[str]:
        terms = super().analyze(text)
        return [self.stemmer.stem(term) for term in terms]
