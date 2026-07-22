# Advanced Search V1

The search endpoint now supports product-facing controls without changing the
default search behavior.

```text
GET /api/v1/search?q=python+search
GET /api/v1/search?q=python+search&scope=content&exact_phrase=true
GET /api/v1/search?q=search&limit=10&offset=10
```

## Controls

- `limit`: number of results to return, from 1 through 50.
- `offset`: number of matching results to skip, starting at 0.
- `scope`: `all`, `title`, or `content`. The default is `all`.
- `exact_phrase`: when `true`, analyzed query terms must occur contiguously
  in the selected scope.

The response includes `total_results`, `limit`, `offset`, `scope`, and
`exact_phrase`, allowing a future frontend to build pagination controls and
advanced-search toggles without guessing the server state.

The default `all` scope keeps the existing title boost and ranking behavior.
Title and content scopes use separate term frequencies, document frequencies,
and document-length statistics, so a title-only search is ranked using title
data rather than filtering full-document scores after the fact.

Source and date filters are intentionally deferred until document metadata is
carried into the versioned search snapshot. That keeps this first product
slice honest and gives the next feature a clear storage/indexing boundary.
