# Advanced Search V1

The search endpoint now supports product-facing controls without changing the
default search behavior.

```text
GET /api/v1/search?q=python+search
GET /api/v1/search?q=python+search&scope=content&exact_phrase=true
GET /api/v1/search?q=search&limit=10&offset=10
GET /api/v1/search?q=python&source=wikipedia.org
GET /api/v1/search?q=python&created_from=2026-07-01&created_to=2026-07-23
```

## Controls

- `limit`: number of results to return, from 1 through 50.
- `offset`: number of matching results to skip, starting at 0.
- `scope`: `all`, `title`, or `content`. The default is `all`.
- `exact_phrase`: when `true`, analyzed query terms must occur contiguously
  in the selected scope.
- `source`: a normalized domain or hostname. A host matches the exact source
  or a dot-separated subdomain, so `wikipedia.org` also matches
  `en.wikipedia.org` but not `notwikipedia.org`.
- `created_from`: inclusive lower bound for the document ingestion date.
- `created_to`: inclusive upper bound for the document ingestion date.

The date filters use the UTC calendar date from the indexed document's
`created_at` timestamp. They describe when the document entered the index, not
when a Wikipedia article was published. Source and date filters combine with
AND. A document missing a URL is excluded only when `source` is active; a
document missing `created_at` is excluded only when either date filter is
active. A valid filter with no matches returns `200` with an empty result list.
If both dates are supplied, `created_from` must be on or before `created_to`,
otherwise the API returns `422`.

The response includes `total_results`, `limit`, `offset`, `scope`,
`exact_phrase`, and nullable `source`, `created_from`, and `created_to` fields,
allowing the frontend to display the server's applied filter state without
guessing.

The default `all` scope keeps the existing title boost and ranking behavior.
Title and content scopes use separate term frequencies, document frequencies,
and document-length statistics, so a title-only search is ranked using title
data rather than filtering full-document scores after the fact.

Metadata filtering happens inside the versioned search snapshot before BM25 or
TF-IDF scores are calculated. The ranking statistics remain those of the
snapshot, while totals and pagination are computed over the eligible
candidate documents.
