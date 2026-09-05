# Search Evaluation

The search engine includes a 50-query, manually judged benchmark in
`data/search_evaluation.json`. It uses the six-document teaching corpus. Each
query contains the document IDs that a human considers relevant. The judgments
are deliberately separate from the ranking implementation so BM25 and TF-IDF
are measured against the same expectations.

Run the comparison with:

```bash
python scripts/evaluate_search.py
```

Use a different cutoff or inspect every query's retrieved IDs with:

```bash
python scripts/evaluate_search.py --k 2 --details
```

## Metrics

- **Precision@K**: how many of the first K results are relevant. A value of
  `1.0` means every displayed result was relevant.
- **Recall@K**: how many of all known relevant documents appeared in the first
  K results. A value of `1.0` means the top K included every judged relevant
  document.
- **MRR**: mean reciprocal rank. For each query, the first relevant result at
  position 1 contributes `1.0`, position 2 contributes `0.5`, and a query with
  no relevant result contributes `0.0`.

The 50-query set is a stronger regression check than the original 8-query set,
but it is still a small sample-corpus benchmark. It should not be presented as
production search quality. The next quality milestone is a larger judgment set
over a stable real-article corpus, with representative queries and multiple
relevant-document labels before tuning the analyzer or ranking parameters.
