from datetime import UTC, date, datetime

from app.search.analyzer import SimpleAnalyzer
from app.search.filters import (
    created_at_utc_date,
    derive_source_host,
    matches_metadata,
    normalize_source,
)
from app.search.inverted_index import InvertedIndex
from app.search.types import IndexedDocument, Posting


def build_index() -> InvertedIndex:
    index = InvertedIndex(analyzer=SimpleAnalyzer(stopwords=set()))
    index.add_document(
        IndexedDocument(id=1, title="Python Search", content="python search search")
    )
    index.add_document(
        IndexedDocument(id=2, title="Java Search", content="java search engine")
    )
    return index


def build_metadata_index() -> InvertedIndex:
    index = InvertedIndex(analyzer=SimpleAnalyzer(stopwords=set()))
    for document in (
        IndexedDocument(
            id=1,
            title="Wikipedia Search",
            content="search",
            source_host="wikipedia.org",
            created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(
            id=2,
            title="Wikipedia Subdomain Search",
            content="search",
            source_host="en.wikipedia.org",
            created_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(
            id=3,
            title="Partial Suffix Search",
            content="search",
            source_host="notwikipedia.org",
            created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(
            id=4,
            title="Missing URL Search",
            content="search",
            created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(
            id=5,
            title="Missing Date Search",
            content="search",
            source_host="example.com",
        ),
    ):
        index.add_document(document)
    return index


def test_term_postings_include_matching_document_ids():
    index = build_index()

    postings = index.get_postings("python")

    assert postings == [Posting(document_id=1, term_frequency=3)]


def test_term_postings_can_be_limited_to_candidate_document_ids():
    index = build_index()

    postings = index.get_postings("search", document_ids={2})

    assert postings == [Posting(document_id=2, term_frequency=3)]


def test_term_frequency_is_counted_per_document():
    index = build_index()

    assert index.term_frequency(1, "search") == 4
    assert index.term_frequency(2, "search") == 3
    assert index.term_frequency(2, "python") == 0


def test_document_length_is_stored():
    index = build_index()

    assert index.document_length(1) == 7
    assert index.document_length(2) == 7


def test_index_tracks_title_and_content_scopes():
    index = build_index()

    assert index.document_count(scope="title") == 2
    assert index.document_count(scope="content") == 2
    assert index.term_frequency(1, "python", scope="title") == 1
    assert index.term_frequency(1, "python", scope="content") == 1
    assert index.term_frequency(2, "java", scope="title") == 1
    assert index.term_frequency(2, "java", scope="content") == 1


def test_index_can_detect_contiguous_phrases_in_a_scope():
    index = build_index()

    assert index.contains_phrase(1, ["python", "search"], scope="content")
    assert not index.contains_phrase(2, ["python", "search"], scope="content")


def test_average_document_length_is_computed():
    index = build_index()

    assert index.average_document_length() == 7.0


def test_removing_document_removes_its_postings():
    index = build_index()

    index.remove_document(1)

    assert index.get_postings("python") == []
    assert index.get_postings("search") == [Posting(document_id=2, term_frequency=3)]
    assert index.document_count() == 1


def test_metadata_helpers_normalize_hosts_and_utc_dates():
    assert normalize_source("  Wikipedia.ORG... ") == "wikipedia.org"
    assert derive_source_host("https://EN.wikipedia.org:443/wiki/Search") == "en.wikipedia.org"
    assert derive_source_host("not a url") is None
    assert created_at_utc_date(datetime(2026, 7, 23, 0, 30, tzinfo=UTC)) == date(2026, 7, 23)
    assert created_at_utc_date(datetime(2026, 7, 23, 0, 30)) == date(2026, 7, 23)


def test_metadata_filters_match_subdomains_and_inclusive_dates():
    index = build_metadata_index()

    assert index.filter_document_ids(source="wikipedia.org") == {1, 2}
    assert index.filter_document_ids(source="example.com") == {5}
    assert index.filter_document_ids(
        created_from=date(2026, 7, 20),
        created_to=date(2026, 7, 20),
    ) == {1, 3, 4}
    assert index.filter_document_ids(
        source="wikipedia.org",
        created_from=date(2026, 7, 20),
        created_to=date(2026, 7, 23),
    ) == {1, 2}


def test_metadata_filters_exclude_only_documents_missing_active_metadata():
    index = build_metadata_index()

    assert index.filter_document_ids(source="wikipedia.org") == {1, 2}
    assert index.filter_document_ids(created_from=date(2026, 7, 20)) == {1, 2, 3, 4}


def test_source_matching_does_not_accept_partial_domain_suffixes():
    assert matches_metadata("notwikipedia.org", None, "wikipedia.org", None, None) is False
