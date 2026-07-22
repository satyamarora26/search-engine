# Search Explainability Design

## Status

Approved design for the next frontend milestone.

## Goal

Let a user understand why a BM25 result received its score without leaving the
search results page. The feature should expose the ranking data that the
backend already calculates, while keeping the default result list compact.

## Scope

The feature adds an inline explanation control to BM25 results. Selecting the
control requests the explanation for that document and expands a detail area
inside the result row. The detail area shows the final score and the per-term
BM25 values returned by the API:

- term
- term frequency
- document frequency
- inverse document frequency
- score contribution

The control is hidden for TF-IDF results because the current explanation API
supports BM25 only. No ranking behavior or backend response contract changes
are required.

## User Experience

Each BM25 result includes an `Explain score` button. The button is a clear
text-and-icon command because it is an important action rather than an
unfamiliar icon-only control.

When selected:

1. The result shows a loading state while `/api/v1/search/explain` is pending.
2. A successful response expands below the result content.
3. The expanded area displays the final score and a readable term-contribution
   table.
4. Selecting the button again collapses the explanation.
5. Reopening an already loaded explanation uses the cached response and does
   not make another request.

If the request fails, the row shows an inline error and a retry action. The
rest of the result list remains usable. If the API returns no contributing
terms, the expanded area shows a clear empty state instead of an empty table.

Changing the query, ranking, or result page clears the explanation cache and
closes any expanded row. An explanation is never displayed for a result from a
different search context.

## Component Design

`WorkspacePage` owns explanation state because it owns the active query and
ranking context. It passes the relevant state and callbacks through
`SearchResults` to `SearchResultRow`.

The state is keyed by document id and contains:

- loaded explanation responses
- the document id currently loading
- per-document request errors
- the currently expanded document id

`SearchResultRow` remains responsible for presenting one result and its
expanded explanation. It does not call the API directly. This keeps network
orchestration in the page and keeps the row straightforward to test.

The existing typed `explainSearch(query, documentId)` client function and
`SearchExplainResponse` types are reused.

## Request Flow

```text
User selects Explain score
        |
        v
WorkspacePage calls explainSearch(activeQuery, documentId)
        |
        v
GET /api/v1/search/explain?q=...&document_id=...
        |
        v
WorkspacePage caches response by document id
        |
        v
SearchResultRow renders final score and term contributions
```

The request uses the active query and the result's document id. The current
backend endpoint defaults to BM25 and is only available for BM25 explanations.

## Error Handling

- Loading disables the explanation action for that row and communicates the
  state through visible text and a live region.
- A failed request is rendered inside the affected row only.
- Retry repeats the same query/document request.
- A 404 or malformed response is treated as an explanation error and does not
  remove the underlying search result.
- Switching search context clears stale explanation state.

## Testing Contract

Frontend tests will verify:

1. BM25 results show the Explain score action.
2. TF-IDF results do not show the action.
3. Selecting the action calls `explainSearch` with the active query and
   document id.
4. A successful response renders the final score and contribution fields.
5. Reopening a loaded explanation does not call the API a second time.
6. Loading and retryable error states are visible and recover correctly.
7. Changing page or submitting a new search removes stale explanations.

Existing backend tests and the current search explanation API contract remain
the regression boundary. The implementation must keep the full frontend test,
build, lint, and backend test suites green.

## Non-Goals

- Adding explanations for TF-IDF.
- Changing BM25 scoring, tokenization, or ranking order.
- Adding source/date filters or new document metadata.
- Adding a separate analytics dashboard.
- Persisting explanations between browser sessions.
