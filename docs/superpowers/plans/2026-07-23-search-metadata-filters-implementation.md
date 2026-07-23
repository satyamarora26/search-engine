# Search Metadata Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add source-domain and document-ingestion-date filters to the existing BM25/TF-IDF search flow, API, and workspace UI while preserving ranking, exact-phrase, pagination, and explanation behavior.

**Architecture:** The versioned in-memory search snapshot will carry `source_host` and nullable `created_at` metadata on each `IndexedDocument`. `InvertedIndex` will select eligible document IDs before ranking; BM25 and TF-IDF will score only those candidates while continuing to use the current full-index statistics, so adding a filter narrows the candidate set without silently changing the ranking formulas. The API will validate and echo filters, and the React workspace will keep one active filter object through submission, pagination, retry, and score-explanation interactions.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, React 19, TypeScript, Vitest, Testing Library, Vite, lucide-react, PostgreSQL-backed document models with an in-memory versioned search snapshot.

## Global Constraints

- Use the existing `Document.url` and `Document.created_at`; do not add database columns or migrations.
- Interpret date filters as inclusive UTC calendar dates from the existing ingestion timestamp, not Wikipedia publication dates.
- Combine source, lower-date, and upper-date filters with AND.
- Preserve current BM25, TF-IDF, analyzer, scope, exact-phrase, pagination, retry, and explanation behavior when filters are absent.
- Blank source input is treated as no source filter; a reversed date range returns HTTP 422 with `created_from must be on or before created_to.`.
- Missing URLs are excluded only when a source filter is active; missing timestamps are excluded only when a date filter is active.
- Use TDD: write focused failing tests, run them, implement the smallest change, rerun focused tests, then run the broader suite.
- Keep the frontend compact and accessible: labelled controls, a `wikipedia.org` suggestion, icon buttons only where a familiar icon exists, and responsive styles without introducing a new UI dependency.
- Commit every completed implementation task with a focused message and push `main` after the commit.

## File Map

Backend search files:

- Create `app/search/filters.py` for source normalization, URL-host derivation, UTC date extraction, and metadata matching rules.
- Modify `app/search/types.py` to add optional snapshot metadata to `IndexedDocument`.
- Modify `app/search/inverted_index.py` to retain document metadata and expose eligible candidate IDs/postings.
- Modify `app/search/bm25.py` and `app/search/tfidf.py` to score an optional candidate ID set.
- Modify `app/search/engine.py` to accept filters, select candidates before ranking, and paginate the filtered ranked list.
- Modify `app/services/search_index.py` to derive metadata during snapshot conversion and pass/echo filter values.
- Modify `app/schemas/search.py` and `app/api/v1/search.py` for the public request and response contract.

Frontend files:

- Modify `frontend/src/api/types.ts` and `frontend/src/api/client.ts` for filter state, request parameters, and echoed response metadata.
- Modify `frontend/src/components/SearchForm.tsx` for source/date controls and local clear behavior.
- Modify `frontend/src/pages/WorkspacePage.tsx` to own the active filter context and preserve it across actions.
- Modify `frontend/src/components/SearchResults.tsx` and `frontend/src/styles/global.css` for applied-filter summaries and responsive filter layout.
- Modify `frontend/src/pages/WorkspacePage.test.tsx` for filter submission, clearing, persistence, and summary coverage.

Tests and documentation:

- Modify `tests/unit/search/test_inverted_index.py`, `tests/unit/search/test_engine.py`, and `tests/unit/search/test_search_index_service.py` for metadata propagation and filtered ranking behavior.
- Modify `tests/integration/test_search_api.py` for query validation, filtering, pagination, and response echoing.
- Modify `docs/advanced-search.md` with source/date query examples and semantics.

---

### Task 1: Add snapshot metadata and pre-ranking candidate filtering

**Files:**
- Create: `app/search/filters.py`
- Modify: `app/search/types.py`
- Modify: `app/search/inverted_index.py`
- Modify: `app/search/bm25.py`
- Modify: `app/search/tfidf.py`
- Modify: `app/search/engine.py`
- Test: `tests/unit/search/test_inverted_index.py`
- Test: `tests/unit/search/test_engine.py`

**Interfaces:**
- `IndexedDocument` gains `source_host: str | None = None` and `created_at: datetime | None = None` after `url`.
- `normalize_source(value: str | None) -> str | None` trims whitespace, lowercases, removes trailing dots, and maps blank input to `None`.
- `derive_source_host(url: str | None) -> str | None` returns a lowercase hostname without a port or trailing dot and returns `None` for missing or malformed URLs.
- `created_at_utc_date(value: datetime | None) -> date | None` returns the UTC calendar date for aware timestamps and the date component for naive legacy timestamps.
- `matches_metadata(document_source: str | None, document_created_at: datetime | None, source: str | None, created_from: date | None, created_to: date | None) -> bool` applies the exact-host-or-dot-subdomain rule and inclusive date bounds.
- `InvertedIndex.filter_document_ids(source: str | None = None, created_from: date | None = None, created_to: date | None = None) -> set[int]` returns all indexed IDs when no filters are active and only eligible IDs otherwise.
- `InvertedIndex.get_postings(term, scope="all", document_ids: Collection[int] | None = None) -> list[Posting]` omits postings outside the candidate set.
- `Bm25Ranker.score(..., scope="all", document_ids: Collection[int] | None = None)` and `TfidfRanker.score(..., scope="all", document_ids: Collection[int] | None = None)` score only supplied candidates while using the existing index-wide document frequency, document count, and average length calculations.
- `SearchEngine.search(...)` and `search_page(...)` gain optional `source`, `created_from`, and `created_to` parameters. `search_page` computes candidates before calling either ranker, passes `document_ids=candidate_ids`, and uses `len(candidate_ids)` as the ranker limit.

- [ ] **Step 1: Write failing metadata helper and index tests**

Add tests that establish the contract before implementation:

```python
from datetime import UTC, date, datetime

from app.search.filters import (
    created_at_utc_date,
    derive_source_host,
    matches_metadata,
    normalize_source,
)
from app.search.analyzer import SimpleAnalyzer
from app.search.inverted_index import InvertedIndex
from app.search.types import IndexedDocument


def build_index_with_metadata() -> InvertedIndex:
    index = InvertedIndex(analyzer=SimpleAnalyzer(stopwords=set()))
    documents = [
        IndexedDocument(
            id=1,
            title="Wikipedia Search",
            content="search",
            url="https://wikipedia.org/wiki/Search",
            created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(
            id=2,
            title="Wikipedia Subdomain Search",
            content="search",
            url="https://en.wikipedia.org/wiki/Search",
            created_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(
            id=3,
            title="Partial Suffix Search",
            content="search",
            url="https://notwikipedia.org/search",
            created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(id=4, title="Legacy Search", content="search"),
    ]
    for document in documents:
        index.add_document(document)
    return index


def test_metadata_helpers_normalize_hosts_and_utc_dates():
    assert normalize_source("  Wikipedia.ORG... ") == "wikipedia.org"
    assert derive_source_host("https://EN.wikipedia.org:443/wiki/Search") == "en.wikipedia.org"
    assert derive_source_host("not a url") is None
    assert created_at_utc_date(datetime(2026, 7, 23, 0, 30, tzinfo=UTC)) == date(2026, 7, 23)
    assert created_at_utc_date(datetime(2026, 7, 23, 0, 30, tzinfo=UTC).replace(tzinfo=None)) == date(2026, 7, 23)


def test_index_filters_exact_hosts_subdomains_and_inclusive_dates():
    index = build_index_with_metadata()

    assert index.filter_document_ids(source="wikipedia.org") == {1, 2}
    assert index.filter_document_ids(created_from=date(2026, 7, 20), created_to=date(2026, 7, 20)) == {1}
    assert index.filter_document_ids(source="wikipedia.org", created_from=date(2026, 7, 20), created_to=date(2026, 7, 23)) == {1, 2}


def test_metadata_filters_exclude_documents_missing_required_metadata():
    index = build_index_with_metadata()

    assert index.filter_document_ids(source="wikipedia.org") == {1, 2}
    assert index.filter_document_ids(created_from=date(2026, 7, 20)) == {1, 2, 3}


def test_source_matching_does_not_accept_partial_domain_suffixes():
    assert matches_metadata("notwikipedia.org", None, "wikipedia.org", None, None) is False
```

The fixture indexes four documents: `wikipedia.org` on 2026-07-20, `en.wikipedia.org` on 2026-07-23, `notwikipedia.org` on 2026-07-20, and one document with no source/timestamp. The source-only result `{1, 2}` proves the missing URL is excluded, while the date-only result `{1, 2, 3}` proves the missing timestamp is excluded without affecting documents that have no URL.

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `pytest tests/unit/search/test_inverted_index.py tests/unit/search/test_engine.py -q`

Expected: FAIL because the helper module, metadata fields, index filter method, and filter-aware search signatures do not exist yet.

- [ ] **Step 3: Implement metadata helpers and index candidate selection**

Add `app/search/filters.py` with `urllib.parse.urlsplit`, `datetime.UTC`, and `date`/`datetime` types. Catch `ValueError` from malformed URLs. Implement source matching as `host == source or host.endswith("." + source)` so `notwikipedia.org` cannot match `wikipedia.org`. Store metadata in `InvertedIndex._document_metadata` keyed by document ID, update it in `add_document`, and remove it in `remove_document`. Add an optional `document_ids` filter to `get_postings` without changing the returned posting sort order.

- [ ] **Step 4: Implement candidate-aware BM25, TF-IDF, and engine search**

In each ranker, accept `document_ids: Collection[int] | None`. Treat an empty supplied collection as no hits, filter postings through `get_postings(..., document_ids=document_ids)`, and keep all score-statistic calls pointed at the existing full index. In `SearchEngine.search_page`, normalize the source, get candidate IDs before ranking, return an empty `SearchPage` when that set is empty, rank with a candidate-sized limit, apply exact phrase filtering, and slice for offset/limit. Keep no-filter calls behaviorally identical.

- [ ] **Step 5: Add engine tests for both rankers and filtered pagination**

Extend the engine fixture with metadata and add tests like:

```python
from datetime import UTC, date, datetime


def build_engine_with_metadata() -> tuple[SearchEngine, InvertedIndex, SimpleAnalyzer]:
    analyzer = SimpleAnalyzer(stopwords=set())
    index = InvertedIndex(analyzer=analyzer)
    engine = SearchEngine(analyzer=analyzer, index=index)
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
    ):
        engine.index_document(document)
    return engine, index, analyzer


def test_search_filters_candidates_before_bm25_and_paginates_filtered_results():
    engine, _, _ = build_engine_with_metadata()

    page = engine.search_page("search", source="wikipedia.org", limit=1, offset=1)

    assert page.total_results == 2
    assert [hit.document_id for hit in page.hits] == [2]


def test_search_filters_candidates_for_tfidf_and_combines_date_bounds():
    engine, _, _ = build_engine_with_metadata()

    hits = engine.search(
        "search",
        ranking="tfidf",
        created_from=date(2026, 7, 23),
        created_to=date(2026, 7, 23),
    )

    assert [hit.document_id for hit in hits] == [2]
```

Run: `pytest tests/unit/search/test_inverted_index.py tests/unit/search/test_engine.py -q`

Expected: PASS, including all existing no-filter ranker and phrase tests.

- [ ] **Step 6: Commit the search-core change**

Run:

```bash
git add app/search/filters.py app/search/types.py app/search/inverted_index.py app/search/bm25.py app/search/tfidf.py app/search/engine.py tests/unit/search/test_inverted_index.py tests/unit/search/test_engine.py
git commit -m "feat: filter indexed candidates by metadata"
git push origin main
```

Expected: a focused commit is created and `main` is pushed successfully.

### Task 2: Carry PostgreSQL metadata through the service and expose the API contract

**Files:**
- Modify: `app/services/search_index.py`
- Modify: `app/schemas/search.py`
- Modify: `app/api/v1/search.py`
- Test: `tests/unit/search/test_search_index_service.py`
- Test: `tests/integration/test_search_api.py`

**Interfaces:**
- `_to_indexed_document(document: Any) -> IndexedDocument` derives `source_host` from `url`, preserves explicit snapshot metadata, and copies `created_at` when the input object has it.
- `SearchIndexService.search(query, ranking="bm25", limit=10, offset=0, scope="all", exact_phrase=False, source=None, created_from=None, created_to=None) -> SearchResponse` forwards filters to `SearchEngine.search_page` and echoes normalized filter values.
- `SearchResponse` adds nullable `source: str | None`, `created_from: date | None`, and `created_to: date | None` fields.
- `GET /api/v1/search` accepts `source: str | None`, `created_from: date | None`, and `created_to: date | None`; it rejects a reversed range with HTTP 422 and the exact message `created_from must be on or before created_to.`.

- [ ] **Step 1: Write failing service metadata propagation tests**

Add a model-like test object with `url` and a timezone-aware `created_at`, then assert the service filters and echoes metadata:

```python
from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.services.search_index import SearchIndexService


def test_service_derives_source_host_and_copies_created_at_for_model_inputs():
    service = SearchIndexService([
        SimpleNamespace(
            id=1,
            title="Wikipedia Search",
            content="python search",
            url="https://en.wikipedia.org/wiki/Python",
            created_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        )
    ])

    response = service.search("python", source="WIKIPEDIA.org", created_from=date(2026, 7, 23))

    assert response.source == "wikipedia.org"
    assert response.created_from == date(2026, 7, 23)
    assert response.total_results == 1
```

Also add a direct `IndexedDocument` case with an explicit `source_host` and `created_at` to ensure snapshot inputs retain metadata.

- [ ] **Step 2: Run the service test and verify it fails**

Run: `pytest tests/unit/search/test_search_index_service.py -q`

Expected: FAIL because the service does not yet accept filter arguments or populate response metadata.

- [ ] **Step 3: Implement service conversion and response propagation**

Use `dataclasses.replace` for an existing `IndexedDocument` so its explicit metadata is retained while a missing `source_host` is derived from its URL. For ORM-like inputs, read `getattr(document, "created_at", None)` and derive the source host from the URL. Forward normalized source and date values to `SearchEngine.search_page`; populate all three response filter fields on every response, including an unfiltered response with `None` values.

- [ ] **Step 4: Write failing API filter tests**

Add an API fixture with matching, subdomain, partial-suffix, missing-URL, missing-timestamp, and out-of-range documents. Cover source/date AND behavior, inclusive boundaries, filtered pagination, empty 200 responses, echoed filters, and invalid ranges:

```python
from fastapi.testclient import TestClient

from datetime import UTC, datetime

from app.main import create_app
from app.search.types import IndexedDocument
from app.services.search import SearchService
from app.services.search_index_sync import get_synchronized_search_index_service


def build_metadata_client() -> TestClient:
    app = create_app()
    search_index = SearchService([
        IndexedDocument(
            id=1,
            title="Wikipedia Search",
            content="search",
            url="https://wikipedia.org/wiki/Search",
            created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(
            id=2,
            title="Wikipedia Subdomain Search",
            content="search",
            url="https://en.wikipedia.org/wiki/Search",
            created_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(
            id=3,
            title="Partial Suffix Search",
            content="search",
            url="https://notwikipedia.org/search",
            created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        ),
        IndexedDocument(id=4, title="Legacy Search", content="search"),
    ])
    app.dependency_overrides[
        get_synchronized_search_index_service
    ] = lambda: search_index
    return TestClient(app)


def test_search_api_filters_and_echoes_source_and_created_dates():
    client = build_metadata_client()

    response = client.get("/api/v1/search", params={
        "q": "search",
        "source": "WIKIPEDIA.ORG",
        "created_from": "2026-07-20",
        "created_to": "2026-07-23",
        "limit": 1,
        "offset": 1,
    })

    assert response.status_code == 200
    assert response.json()["source"] == "wikipedia.org"
    assert response.json()["created_from"] == "2026-07-20"
    assert response.json()["created_to"] == "2026-07-23"
    assert response.json()["total_results"] == 2
    assert response.json()["results"][0]["document_id"] == 2


def test_search_api_returns_empty_200_for_a_valid_filter_with_no_matches():
    client = build_metadata_client()

    response = client.get("/api/v1/search", params={
        "q": "search",
        "source": "docs.example.com",
    })

    assert response.status_code == 200
    assert response.json()["total_results"] == 0
    assert response.json()["results"] == []


def test_search_api_rejects_reversed_created_date_range():
    client = build_client()

    response = client.get("/api/v1/search", params={
        "q": "search",
        "created_from": "2026-07-24",
        "created_to": "2026-07-23",
    })

    assert response.status_code == 422
    assert response.json()["detail"] == "created_from must be on or before created_to."
```

- [ ] **Step 5: Run API tests and verify they fail**

Run: `pytest tests/integration/test_search_api.py -q`

Expected: FAIL because the route, service, and response schema do not accept or echo the new parameters.

- [ ] **Step 6: Implement API query parameters and validation**

Declare the new route parameters with FastAPI/Pydantic `date` parsing, normalize source in the service, validate only `created_from > created_to`, and pass the values through unchanged otherwise. Do not add validation that rejects valid no-match filters. Keep the explanation and rebuild routes unchanged.

- [ ] **Step 7: Run backend search tests and commit the API change**

Run:

```bash
pytest tests/unit/search tests/integration/test_search_api.py -q
```

Expected: PASS for all existing and new tests.

Then run:

```bash
git add app/services/search_index.py app/schemas/search.py app/api/v1/search.py tests/unit/search/test_search_index_service.py tests/integration/test_search_api.py
git commit -m "feat: expose metadata search filters"
git push origin main
```

### Task 3: Add filter request types, API client parameters, and form controls

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/SearchForm.tsx`
- Modify: `frontend/src/styles/global.css`
- Test: `frontend/src/pages/WorkspacePage.test.tsx`

**Interfaces:**
- Add `SearchFilters = { source: string; createdFrom: string; createdTo: string }` for controlled UI state.
- Extend `SearchResponse` with `source: string | null`, `created_from: string | null`, and `created_to: string | null`.
- Extend `searchDocuments` options with `source?: string`, `created_from?: string`, and `created_to?: string`; set only trimmed, non-empty values in `URLSearchParams`.
- `SearchForm.onSubmit` becomes `(query, ranking, scope, exactPhrase, filters: SearchFilters) => void`.
- `SearchForm` receives `initialFilters?: SearchFilters`, keeps source/date fields locally, and clears only those local controls when `Clear filters` is clicked.

- [ ] **Step 1: Update the frontend fixture and add failing interaction tests**

Add nullable filter fields to `resultResponse`, then add tests for labelled controls, request serialization, the source suggestion, and clear behavior:

```tsx
it('submits source and ingestion-date filters', async () => {
  vi.mocked(searchDocuments).mockResolvedValue(resultResponse)
  const user = userEvent.setup()
  render(<WorkspacePage />)

  await user.type(screen.getByLabelText('Search documents'), 'information retrieval')
  await user.type(screen.getByLabelText('Source or domain'), 'wikipedia.org')
  await user.type(screen.getByLabelText('Created from'), '2026-07-01')
  await user.type(screen.getByLabelText('Created to'), '2026-07-23')
  await user.click(screen.getByRole('button', { name: 'Search' }))

  expect(searchDocuments).toHaveBeenCalledWith(
    'information retrieval',
    'bm25',
    10,
    {
      offset: 0,
      scope: 'all',
      exact_phrase: false,
      source: 'wikipedia.org',
      created_from: '2026-07-01',
      created_to: '2026-07-23',
    },
  )
})

it('clears local metadata controls before the next search', async () => {
  vi.mocked(searchDocuments).mockResolvedValue(resultResponse)
  const user = userEvent.setup()
  render(<WorkspacePage />)

  await user.type(screen.getByLabelText('Search documents'), 'ranking')
  await user.type(screen.getByLabelText('Source or domain'), 'wikipedia.org')
  await user.click(screen.getByRole('button', { name: 'Clear filters' }))

  expect(screen.getByLabelText('Source or domain')).toHaveValue('')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  expect(searchDocuments).toHaveBeenLastCalledWith(
    'ranking', 'bm25', 10,
    { offset: 0, scope: 'all', exact_phrase: false },
  )
})
```

- [ ] **Step 2: Run the frontend test and verify it fails**

Run: `cd frontend && npm test -- --run src/pages/WorkspacePage.test.tsx`

Expected: FAIL because the new labels, response fields, and request options are not implemented.

- [ ] **Step 3: Implement API types and query serialization**

Add the `SearchFilters` interface and nullable response fields. In `searchDocuments`, preserve the existing omission rules for offset zero, the `all` scope, and false exact phrase, then add:

```ts
const source = options.source?.trim()
if (source) params.set('source', source)
const createdFrom = options.created_from?.trim()
if (createdFrom) params.set('created_from', createdFrom)
const createdTo = options.created_to?.trim()
if (createdTo) params.set('created_to', createdTo)
```

- [ ] **Step 4: Implement accessible source/date controls and clear action**

Add a labelled text input with `id="search-source"`, `list="source-suggestions"`, and a datalist option `wikipedia.org`; add labelled `type="date"` inputs with stable IDs `created-from` and `created-to`; and add a `type="button"` button named `Clear filters` with a `RotateCcw` icon. On submit, pass `{ source, createdFrom, createdTo }` after trimming only the source field. Keep the existing query validation and ranking/scope/exact-phrase controls.

- [ ] **Step 5: Add responsive filter styles**

Add a compact `.search-filter-grid` with one flexible source field and two date fields, a `.search-filter-field` label/input treatment matching the existing form, and `.search-filter-actions` alignment. At the mobile breakpoint, make the grid one column and keep clear/search controls full width. Reuse existing colors, borders, radii, and typography variables; do not add a card inside the search panel.

- [ ] **Step 6: Run frontend tests, build, lint, and commit the form/client change**

Run:

```bash
cd frontend
npm test -- --run src/pages/WorkspacePage.test.tsx
npm run build
npm run lint
```

Expected: existing tests plus the new interaction tests pass, TypeScript/Vite build succeeds, and Oxlint reports no errors.

Then run:

```bash
cd ..
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/components/SearchForm.tsx frontend/src/styles/global.css frontend/src/pages/WorkspacePage.test.tsx
git commit -m "feat: add metadata filter controls"
git push origin main
```

### Task 4: Preserve filter context in the workspace and show applied filters

**Files:**
- Modify: `frontend/src/pages/WorkspacePage.tsx`
- Modify: `frontend/src/components/SearchResults.tsx`
- Test: `frontend/src/pages/WorkspacePage.test.tsx`

**Interfaces:**
- `WorkspacePage` owns `filters: SearchFilters` alongside query/ranking/scope/exact phrase.
- `runSearch(nextQuery, nextRanking, nextScope, nextExactPhrase, nextFilters, nextOffset)` updates all active search state before requesting and passes non-empty filter values to `searchDocuments`.
- Retry and pagination call `runSearch` with the current `filters`; submitting a new search uses offset `0` and the form's selected filters.
- `SearchResults` renders the response's echoed filter values, including when the filtered response has zero results, without changing result-row or explanation props.

- [ ] **Step 1: Add failing workspace persistence and summary tests**

Extend the existing pagination test so it fills the three controls before the first search and verifies the second request keeps all filters. Extend the retry test to mock a first rejection and a second success and verify the retry carries the same filter options. Add a response-summary assertion:

```tsx
it('renders the echoed applied-filter summary', async () => {
  vi.mocked(searchDocuments).mockResolvedValue({
    ...resultResponse,
    source: 'wikipedia.org',
    created_from: '2026-07-01',
    created_to: '2026-07-23',
  })
  const user = userEvent.setup()
  render(<WorkspacePage />)

  await user.type(screen.getByLabelText('Search documents'), 'ranking')
  await user.click(screen.getByRole('button', { name: 'Search' }))

  expect(await screen.findByText('Source: wikipedia.org')).toBeVisible()
  expect(screen.getByText('Created: 2026-07-01 to 2026-07-23')).toBeVisible()
})
```

- [ ] **Step 2: Run focused frontend tests and verify they fail**

Run: `cd frontend && npm test -- --run src/pages/WorkspacePage.test.tsx`

Expected: FAIL because the workspace does not yet store or pass filters and results do not render the summary.

- [ ] **Step 3: Thread filters through WorkspacePage**

Initialize `filters` to `{ source: '', createdFrom: '', createdTo: '' }`. Add a `toSearchOptions` helper that maps camelCase UI values to snake_case API options and omits empty values. Update `runSearch` to set filters, pass the mapped options to `searchDocuments`, and use the new argument order consistently. Pass `initialFilters={filters}` and the new callback to `SearchForm`; update retry and page-change callbacks to pass `filters`. Keep explanation context invalidation exactly where it is so a new filtered request cannot display an older explanation.

- [ ] **Step 4: Render a compact applied-filter summary**

In `SearchResults`, keep the existing result count and add a `div` with `aria-label="Applied search filters"` only when at least one echoed filter is non-null. Render `Source: <host>`, `Created from: <date>`, `Created to: <date>`, or the combined `Created: <from> to <to>` form for both date bounds. Render the same metadata row before the no-results message when `response` exists so a valid no-match filter is still visible. Use the response echo, not local form state, as the displayed truth.

- [ ] **Step 5: Run all frontend verification and commit the workspace change**

Run:

```bash
cd frontend
npm test -- --run
npm run build
npm run lint
```

Expected: all frontend tests pass, the build succeeds, and lint is clean.

Then run:

```bash
cd ..
git add frontend/src/pages/WorkspacePage.tsx frontend/src/components/SearchResults.tsx frontend/src/pages/WorkspacePage.test.tsx
git commit -m "feat: preserve and explain active search filters"
git push origin main
```

### Task 5: Document and verify the complete feature

**Files:**
- Modify: `docs/advanced-search.md`
- Test: `tests/unit/search/test_engine.py`
- Test: `tests/unit/search/test_search_index_service.py`
- Test: `tests/integration/test_search_api.py`

- [ ] **Step 1: Add documentation examples and guarantees**

Document these requests:

```text
GET /api/v1/search?q=python&source=wikipedia.org
GET /api/v1/search?q=python&created_from=2026-07-01&created_to=2026-07-23
```

Explain that source matches the exact normalized host or a dot-separated subdomain, dates are inclusive UTC ingestion dates, all filters use AND, missing metadata is excluded only for the active filter, and a reversed date range returns 422.

- [ ] **Step 2: Add regression coverage for no-filter behavior and missing metadata**

Assert that an unfiltered `SearchResponse` returns `source is None`, `created_from is None`, and `created_to is None`, and that legacy JSON-corpus searches still return their previous result ordering. Assert that a source-only filter does not exclude a document merely because its timestamp is missing, while a date filter excludes a document whose timestamp is missing.

- [ ] **Step 3: Run the complete backend suite**

Run: `pytest -q`

Expected: all applicable backend tests pass; any pre-existing environment-dependent skips remain skips, with no new failures.

- [ ] **Step 4: Run the complete frontend suite and production checks**

Run:

```bash
cd frontend
npm test -- --run
npm run build
npm run lint
```

Expected: all tests, TypeScript/Vite build, and lint pass.

- [ ] **Step 5: Exercise the running application**

With the existing backend and Vite processes running, search the workspace using `wikipedia.org`, a single date boundary, both date boundaries, and a deliberately unmatched domain. Confirm the request succeeds, the result count and applied-filter summary match the response, pagination keeps filters, clear filters changes the next request, and score explanations still load for BM25 results. If the local processes are stopped, start the backend with `uvicorn app.main:app --host 127.0.0.1 --port 8000` and the frontend with `cd frontend && npm run dev -- --host 127.0.0.1`; report the URLs and any environment-dependent limitation.

- [ ] **Step 6: Commit documentation and final verification**

Run:

```bash
cd ..
git add docs/advanced-search.md tests/unit/search/test_engine.py tests/unit/search/test_search_index_service.py tests/integration/test_search_api.py
git commit -m "docs: document metadata search filters"
git push origin main
git status --short
```

Expected: the documentation commit is pushed to `main`, and `git status --short` is empty.

## Final Acceptance Checklist

- [ ] Source filter matches `wikipedia.org` and `en.wikipedia.org`, but not `notwikipedia.org`.
- [ ] Date bounds are inclusive and evaluated from UTC `created_at` dates.
- [ ] Source and date filters combine with AND, and missing metadata follows the documented exclusion rules.
- [ ] BM25 and TF-IDF totals, ordering, and pagination operate over the filtered candidates.
- [ ] Unfiltered search remains behaviorally compatible and echoes nullable filter fields.
- [ ] API rejects only reversed date ranges for this feature and echoes normalized filters.
- [ ] Frontend submits, clears, preserves, and displays filters across search actions.
- [ ] Existing exact phrase, scope, score explanation, retry, crawl-status, build, lint, and test behavior remains passing.
- [ ] All implementation commits are pushed to personal `main`.
