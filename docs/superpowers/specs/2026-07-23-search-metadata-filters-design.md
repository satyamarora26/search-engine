# Search Metadata Filters Design

## Status

Approved design for the next search-engine milestone.

## Goal

Allow users to narrow search results by source domain and document ingestion
date while preserving the current BM25, TF-IDF, scope, exact-phrase, and
pagination behavior.

## Product Scope

The search form adds three optional filters:

- source/domain, such as `wikipedia.org`;
- created from date;
- created to date.

The date meaning is the document's existing ingestion timestamp, `created_at`.
Publication-date extraction from Wikipedia is a later crawler enhancement and
is outside this milestone.

## Architecture Decision

Metadata filtering happens inside the versioned search snapshot before ranking.
Each `IndexedDocument` carries optional `source_host` and `created_at` values.
The source host is derived from the document URL during snapshot conversion;
the ingestion timestamp is copied from the PostgreSQL document when available.

The search engine filters candidate documents first, then computes BM25 or
TF-IDF scores, totals, and pagination over the filtered set. This keeps the
index as the single source of search behavior and avoids coupling API routes to
database queries during ranking.

No new PostgreSQL columns are required. Source is already derivable from `url`
and the date filter uses the existing `created_at` column.

## API Contract

The existing search endpoint gains these optional parameters:

```text
GET /api/v1/search?q=python&source=wikipedia.org
GET /api/v1/search?q=python&created_from=2026-07-01&created_to=2026-07-23
```

Parameters:

- `source: str | None`: normalized lowercase domain or hostname filter.
- `created_from: date | None`: inclusive lower bound on the UTC date portion
  of `created_at`.
- `created_to: date | None`: inclusive upper bound on the UTC date portion of
  `created_at`.

Source matching succeeds when the normalized document host equals the filter
or ends with `.` plus the filter. Therefore `wikipedia.org` matches both
`wikipedia.org` and `en.wikipedia.org`, but does not match
`notwikipedia.org`.

All supplied filters combine with AND. Documents without a URL are excluded
when a source filter is active. Documents without an ingestion timestamp are
excluded when a date filter is active. An invalid range where
`created_from > created_to` returns HTTP 422. A valid filter with no matches
returns the normal empty search response with HTTP 200.

The response echoes the applied filters:

```json
{
  "source": "wikipedia.org",
  "created_from": "2026-07-01",
  "created_to": "2026-07-23"
}
```

When filters are absent, the default search behavior and response semantics
remain unchanged except for the additional nullable metadata fields.

## Data Flow

```text
PostgreSQL Document(url, created_at)
              |
              v
_to_indexed_document derives source_host and copies created_at
              |
              v
SearchEngine filters candidate ids by metadata
              |
              v
BM25 or TF-IDF scores filtered candidates
              |
              v
SearchResponse returns filtered totals, page, and applied filters
```

JSON corpus documents and other legacy inputs may not have `created_at`; their
date metadata remains null. Their source host can still be derived when a URL
exists. A metadata filter only excludes documents missing the metadata needed
for that filter.

## Frontend Behavior

The existing search form receives a compact filter group containing:

- a labelled source/domain text input with `wikipedia.org` as a suggestion;
- labelled `Created from` and `Created to` date inputs;
- a `Clear filters` action.

Submitting a search sends filters together with ranking, scope, exact phrase,
limit, and offset. A new search resets offset to zero but keeps the selected
filters. Pagination, retry, and BM25 explanation requests preserve the active
filter context. Clearing filters resets the controls locally; the next search
uses an unfiltered request.

Search results show the filtered total and a compact applied-filter summary.
Existing result rows, score explanations, ranking controls, and pagination
remain available.

## Error Handling

- Blank source input is treated as no source filter.
- Invalid date ranges are rejected by the API with a stable 422 message.
- Invalid or missing document URLs do not break indexing; source filtering
  simply excludes those documents.
- Invalid or missing timestamps do not break indexing; date filtering simply
  excludes those documents.
- Search failures retain the existing retryable error behavior.
- A filter change never displays stale results as the new filtered result; the
  existing loading state is shown while the new request runs.

## Testing Contract

Backend tests will cover:

1. source-host derivation and subdomain matching;
2. inclusive lower and upper ingestion-date boundaries;
3. combined source and date filters;
4. documents missing URL or timestamp;
5. filtered BM25 and TF-IDF totals, ordering, and pagination;
6. API validation and echoed filter metadata;
7. unchanged no-filter behavior.

Frontend tests will cover:

1. submitting source and date filters;
2. clear-filters behavior;
3. preserving filters across pagination and retry;
4. rendering the filtered total and applied-filter summary;
5. existing ranking, exact phrase, explanation, and crawl-status behavior.

## Non-Goals

- Adding database columns or a metadata migration.
- Extracting Wikipedia publication dates.
- Adding authentication, saved searches, or filter presets.
- Adding arbitrary full-text metadata fields.
- Replacing BM25, TF-IDF, or the current analyzer.
