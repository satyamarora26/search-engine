# Search Evaluation

The search engine includes a small, judged benchmark in
`data/search_evaluation.json`. Each benchmark query contains the document IDs
that a human considers relevant. The judgments are deliberately separate from
the ranking implementation so BM25 and TF-IDF are measured against the same
expectations.

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

The benchmark is intentionally small while the project is being learned. Once
Wikipedia crawling provides a larger corpus, we should expand the judgment
file with representative queries and more relevant-document labels before
tuning the analyzer or ranking parameters.
