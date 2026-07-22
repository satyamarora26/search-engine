# Search Explainability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add an inline BM25 score explanation to each search result using the existing /api/v1/search/explain endpoint.

**Architecture:** WorkspacePage owns the active query, explanation cache, loading state, errors, and expanded document id. SearchResults forwards explanation state and callbacks to SearchResultRow, while a focused SearchExplanation component renders loading, error, empty, and successful term-contribution states. The API client and backend contract remain unchanged.

**Tech Stack:** React, TypeScript, Vitest, React Testing Library, lucide-react, the existing typed API client, and Vite CSS.

## Global Constraints

- Explanations are available only for BM25 results because the current backend explanation API supports BM25 only.
- Do not change BM25 scoring, tokenization, ranking order, or the backend response contract.
- Reuse the existing typed explainSearch(query, documentId) client function and SearchExplainResponse type.
- Keep network orchestration in WorkspacePage; result components render state and emit user actions.
- Changing the query, ranking, or result page must clear explanation state so stale explanations cannot appear in a new search context.
- Keep loading, retryable error, and empty-term states visible without removing the underlying search result.
- Use existing frontend dependencies and styles; do not add a new UI library.
- Every task ends with focused tests passing and an intentional git commit.

## File Map

- Create: frontend/src/components/SearchExplanation.tsx - render one explanation's loading, error, empty, and success states.
- Modify: frontend/src/components/SearchResultRow.tsx - add the BM25 explanation action and mount the explanation presenter.
- Modify: frontend/src/components/SearchResults.tsx - pass explanation state and callbacks to each row.
- Modify: frontend/src/pages/WorkspacePage.tsx - load, cache, retry, expand, and clear explanations in the active search context.
- Modify: frontend/src/pages/WorkspacePage.test.tsx - verify the Workspace interaction contract with mocked typed API calls.
- Modify: frontend/src/styles/global.css - add compact explanation layout, table, status, and action styles.
- Do not modify: frontend/src/api/client.ts or backend files; explainSearch and its API contract already exist.

---

### Task 1: Add failing Workspace explanation tests

**Files:**
- Modify: frontend/src/pages/WorkspacePage.test.tsx

**Interfaces:**
- Consumes: existing SearchResponse, SearchExplainResponse, searchDocuments, and explainSearch types/functions.
- Produces: executable tests defining the row action, explanation rendering, cache, TF-IDF, retry, and context-reset behavior for Tasks 2 and 3.

- [ ] Step 1: Extend the API mock and fixtures.

Add SearchExplainResponse to the type import, mock explainSearch in the existing client mock factory, import it beside searchDocuments, and define this fixture after resultResponse:

~~~tsx
const explanationResponse: SearchExplainResponse = {
  query: 'information retrieval',
  ranking: 'bm25',
  document_id: 7,
  final_score: 1.09,
  terms: [
    { term: 'information', term_frequency: 2, document_frequency: 4, idf: 0.81, contribution: 0.62 },
    { term: 'retrieval', term_frequency: 1, document_frequency: 3, idf: 0.94, contribution: 0.47 },
  ],
}
~~~

- [ ] Step 2: Write the failing BM25 explanation test.

~~~tsx
it('loads and renders a BM25 score explanation', async () => {
  vi.mocked(searchDocuments).mockResolvedValue(resultResponse)
  vi.mocked(explainSearch).mockResolvedValue(explanationResponse)
  const user = userEvent.setup()
  render(<WorkspacePage />)

  await user.type(screen.getByLabelText('Search documents'), 'information retrieval')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  await screen.findByText('Information retrieval')
  await user.click(screen.getByRole('button', { name: 'Explain score' }))

  expect(explainSearch).toHaveBeenCalledWith('information retrieval', 7)
  expect(await screen.findByText('Score explanation')).toBeVisible()
  expect(screen.getByText('Final score')).toBeVisible()
  expect(screen.getByText('0.62')).toBeVisible()
})
~~~

- [ ] Step 3: Write the failing cache and TF-IDF tests.

~~~tsx
it('reuses a loaded explanation when it is reopened', async () => {
  vi.mocked(searchDocuments).mockResolvedValue(resultResponse)
  vi.mocked(explainSearch).mockResolvedValue(explanationResponse)
  const user = userEvent.setup()
  render(<WorkspacePage />)

  await user.type(screen.getByLabelText('Search documents'), 'information retrieval')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  await screen.findByText('Information retrieval')
  await user.click(screen.getByRole('button', { name: 'Explain score' }))
  await screen.findByText('Score explanation')
  await user.click(screen.getByRole('button', { name: 'Hide score explanation' }))
  await user.click(screen.getByRole('button', { name: 'Explain score' }))

  expect(explainSearch).toHaveBeenCalledTimes(1)
  expect(await screen.findByText('Score explanation')).toBeVisible()
})

it('does not show score explanation for TF-IDF results', async () => {
  vi.mocked(searchDocuments).mockResolvedValue({ ...resultResponse, ranking: 'tfidf' })
  const user = userEvent.setup()
  render(<WorkspacePage />)

  await user.type(screen.getByLabelText('Search documents'), 'ranking')
  await user.selectOptions(screen.getByLabelText('Ranking'), 'tfidf')
  await user.click(screen.getByRole('button', { name: 'Search' }))

  await screen.findByText('Information retrieval')
  expect(screen.queryByRole('button', { name: 'Explain score' })).not.toBeInTheDocument()
})
~~~

- [ ] Step 4: Write the failing retry and context-reset tests.

~~~tsx
it('retries a failed score explanation', async () => {
  vi.mocked(searchDocuments).mockResolvedValue(resultResponse)
  vi.mocked(explainSearch)
    .mockRejectedValueOnce(new Error('Explanation service unavailable.'))
    .mockResolvedValueOnce(explanationResponse)
  const user = userEvent.setup()
  render(<WorkspacePage />)

  await user.type(screen.getByLabelText('Search documents'), 'information retrieval')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  await screen.findByText('Information retrieval')
  await user.click(screen.getByRole('button', { name: 'Explain score' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Explanation service unavailable.')
  await user.click(screen.getByRole('button', { name: 'Retry score explanation' }))

  expect(await screen.findByText('Score explanation')).toBeVisible()
  expect(explainSearch).toHaveBeenCalledTimes(2)
})

it('clears an explanation when a new search replaces the result context', async () => {
  const nextResponse = {
    ...resultResponse,
    query: 'ranking',
    results: [{ ...resultResponse.results[0], document_id: 8, title: 'Ranking' }],
  }
  vi.mocked(searchDocuments)
    .mockResolvedValueOnce(resultResponse)
    .mockResolvedValueOnce(nextResponse)
  vi.mocked(explainSearch).mockResolvedValue(explanationResponse)
  const user = userEvent.setup()
  render(<WorkspacePage />)

  await user.type(screen.getByLabelText('Search documents'), 'information retrieval')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  await screen.findByText('Information retrieval')
  await user.click(screen.getByRole('button', { name: 'Explain score' }))
  await screen.findByText('Score explanation')

  const queryInput = screen.getByLabelText('Search documents')
  await user.clear(queryInput)
  await user.type(queryInput, 'ranking')
  await user.click(screen.getByRole('button', { name: 'Search' }))

  expect(await screen.findByText('Ranking')).toBeVisible()
  expect(screen.queryByText('Score explanation')).not.toBeInTheDocument()
})
~~~

- [ ] Step 5: Run the focused tests and verify RED.

Run:

~~~bash
npm test -- --run src/pages/WorkspacePage.test.tsx
~~~

Expected: the existing six tests pass, while the new explanation tests fail because result rows do not expose Explain score and Workspace does not render explanation state.

- [ ] Step 6: Commit the failing-test contract.

~~~bash
git add frontend/src/pages/WorkspacePage.test.tsx
git commit -m "test: define search explanation interactions"
~~~

---

### Task 2: Build the explanation presenter and result-row action

**Files:**
- Create: frontend/src/components/SearchExplanation.tsx
- Create: frontend/src/components/SearchExplanation.test.tsx
- Modify: frontend/src/components/SearchResultRow.tsx
- Modify: frontend/src/styles/global.css

**Interfaces:**
- Consumes: SearchExplainResponse, a per-document explanation state, and callbacks from WorkspacePage.
- Produces: SearchResultRow props that render a BM25-only action and inline explanation panel without making network requests.

- [ ] Step 1: Add the explanation state and presenter.

Create frontend/src/components/SearchExplanation.tsx with:

~~~tsx
import { AlertCircle, LoaderCircle, RotateCcw } from 'lucide-react'
import type { SearchExplainResponse } from '../api/types'

export type SearchExplanationState = {
  error: Error | null
  isLoading: boolean
  response: SearchExplainResponse | null
}

type SearchExplanationProps = SearchExplanationState & { onRetry: () => void }
~~~

Export SearchExplanation({ error, isLoading, onRetry, response }) and render a role=status loading message, a role=alert error with Retry score explanation, an empty message when there is no response, or a success panel containing Score explanation, Final score, and a table with Term, TF, DF, IDF, and Contribution columns. Format decimal fields to two places and TF/DF as integers.

- [ ] Step 2: Extend SearchResultRow without adding API calls.

Use this prop shape:

~~~tsx
type SearchResultRowProps = {
  position: number
  result: SearchResult
  explanation?: SearchExplanationState
  isExplanationExpanded?: boolean
  showExplanation?: boolean
  onRetryExplanation?: () => void
  onToggleExplanation?: () => void
}
~~~

Give the new props safe defaults so existing SearchResults callers continue to compile until Task 3 wires page state. When showExplanation is true, render a button labelled Explain score or Hide score explanation with matching aria-expanded and aria-controls. Mount SearchExplanation only while the row is expanded. Preserve the existing result title, source, snippet, score, and matched-term chips.

- [ ] Step 3: Add isolated presenter tests.

Create frontend/src/components/SearchExplanation.test.tsx and cover the four presenter states:

~~~tsx
it('renders BM25 term contributions', () => {
  render(<SearchExplanation response={explanationResponse} error={null} isLoading={false} onRetry={vi.fn()} />)
  expect(screen.getByText('Score explanation')).toBeVisible()
  expect(screen.getByRole('columnheader', { name: 'Contribution' })).toBeVisible()
})

it('renders loading, empty, and retryable error states', () => {
  const onRetry = vi.fn()
  const { rerender } = render(<SearchExplanation response={null} error={null} isLoading={true} onRetry={onRetry} />)
  expect(screen.getByRole('status')).toHaveTextContent('Loading score explanation')

  rerender(<SearchExplanation response={null} error={null} isLoading={false} onRetry={onRetry} />)
  expect(screen.getByText('No term contributions available.')).toBeVisible()

  rerender(<SearchExplanation response={null} error={new Error('Explanation unavailable.')} isLoading={false} onRetry={onRetry} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Explanation unavailable.')
  screen.getByRole('button', { name: 'Retry score explanation' }).click()
  expect(onRetry).toHaveBeenCalledOnce()
})
~~~

- [ ] Step 4: Add focused explanation styles.

Add styles next to the current result styles in global.css for .result-explanation-action, .result-explanation, .explanation-summary, .explanation-table, .explanation-state, and their table cells. Use existing --line, --ink, --ink-muted, --blue, and button tokens. Add a mobile rule with horizontal table overflow protection.

- [ ] Step 5: Run the isolated presenter tests and build.

~~~bash
npm test -- --run src/components/SearchExplanation.test.tsx
npm run build
~~~

Expected: all presenter tests pass and the application compiles. The new Workspace interaction tests remain red until Task 3 wires page state.

- [ ] Step 6: Commit the presentational layer.

~~~bash
git add frontend/src/components/SearchExplanation.tsx frontend/src/components/SearchExplanation.test.tsx frontend/src/components/SearchResultRow.tsx frontend/src/styles/global.css
git commit -m "feat: add inline score explanation UI"
~~~

---

### Task 3: Wire Workspace loading, caching, and reset behavior

**Files:**
- Modify: frontend/src/pages/WorkspacePage.tsx
- Modify: frontend/src/components/SearchResults.tsx

**Interfaces:**
- Consumes: explainSearch(query, documentId): Promise<SearchExplainResponse>, SearchExplanationState, and row callbacks from Task 2.
- Produces: cached, retryable, context-safe explanation behavior for the running Workspace.

- [ ] Step 1: Add page-owned explanation state.

Import useRef and explainSearch, then add:

~~~tsx
const EMPTY_EXPLANATION: SearchExplanationState = {
  error: null,
  isLoading: false,
  response: null,
}

const [explanations, setExplanations] = useState<Record<number, SearchExplanationState>>({})
const [expandedExplanationId, setExpandedExplanationId] = useState<number | null>(null)
const explanationContextRef = useRef(0)
~~~

The ref prevents a request from an older query from repopulating the cache after the user starts a new query.

- [ ] Step 2: Clear state whenever runSearch starts.

At the beginning of runSearch, increment explanationContextRef.current, clear explanations, and set expandedExplanationId to null. This covers new searches, option changes, retries, and pagination because they all use runSearch.

- [ ] Step 3: Implement the loader and retry path.

Add a function with this behavior:

~~~tsx
async function loadExplanation(documentId: number) {
  const context = explanationContextRef.current
  setExplanations((current) => ({
    ...current,
    [documentId]: {
      error: null,
      isLoading: true,
      response: current[documentId]?.response ?? null,
    },
  }))

  try {
    const response = await explainSearch(query, documentId)
    if (context !== explanationContextRef.current) return
    setExplanations((current) => ({
      ...current,
      [documentId]: { error: null, isLoading: false, response },
    }))
  } catch (requestError) {
    if (context !== explanationContextRef.current) return
    setExplanations((current) => ({
      ...current,
      [documentId]: {
        error: requestError instanceof Error ? requestError : new Error('Explanation could not be loaded.'),
        isLoading: false,
        response: current[documentId]?.response ?? null,
      },
    }))
  }
}
~~~

Use active query state and keep errors scoped to one document. Retry clears that document's error and calls the same loader.

- [ ] Step 4: Implement cache-aware toggling.

~~~tsx
function toggleExplanation(documentId: number) {
  if (expandedExplanationId === documentId) {
    setExpandedExplanationId(null)
    return
  }

  setExpandedExplanationId(documentId)
  const state = explanations[documentId]
  if (!state?.response && !state?.isLoading) void loadExplanation(documentId)
}
~~~

Do not issue a second request when a response is cached or the same document is already loading.

- [ ] Step 5: Pass explanation props to SearchResults.

~~~tsx
explanations={explanations}
expandedExplanationId={expandedExplanationId}
onRetryExplanation={(documentId) => void loadExplanation(documentId)}
onToggleExplanation={toggleExplanation}
showExplanations={ranking === 'bm25'}
~~~

- [ ] Step 6: Run the focused tests and make production code GREEN.

~~~bash
npm test -- --run src/pages/WorkspacePage.test.tsx
~~~

Expected: all Workspace tests pass, including explanation loading, caching, TF-IDF hiding, retry, and context reset. Fix implementation code rather than weakening interaction assertions.

- [ ] Step 7: Commit the behavior layer.

~~~bash
git add frontend/src/pages/WorkspacePage.tsx frontend/src/components/SearchResults.tsx
git commit -m "feat: connect search score explanations"
~~~

---

### Task 4: Full verification and live smoke check

**Files:**
- No source changes expected. Modify tests or styles only if verification finds a real defect.

**Interfaces:**
- Consumes: complete frontend and backend suites plus the running local FastAPI service.
- Produces: a verified explainability feature ready to push.

- [ ] Step 1: Run frontend verification.

From frontend/:

~~~bash
npm test -- --run
npm run build
npm run lint
~~~

Expected: all tests pass, the TypeScript/Vite build succeeds, and Oxlint exits successfully.

- [ ] Step 2: Run backend verification.

From the repository root:

~~~bash
pytest -q
~~~

Expected: the existing backend suite remains green because no backend code or API contract changed.

- [ ] Step 3: Smoke-test the live endpoint and UI.

~~~bash
curl -fsS 'http://127.0.0.1:8000/api/v1/search/explain?q=Live%20Celery%20Snapshot&document_id=60'
~~~

Expected: JSON contains ranking bm25, document_id 60, final_score, and a terms array. Refresh http://127.0.0.1:5173/, search for the same phrase, and use Explain score to confirm the inline panel appears.

- [ ] Step 4: Check the final diff and push.

~~~bash
git diff --check
git status --short
git log -5 --oneline
git push origin main
~~~

Expected: no whitespace errors, only intended files changed, and feature commits are available on satyamarora26/search-engine main.

## Self-Review Checklist

- Spec coverage: Tasks 1 through 3 cover the inline action, BM25-only rule, loading state, success table, cache reuse, retry behavior, empty state, and context clearing.
- Placeholder scan: No unresolved placeholder instructions appear in the plan.
- Type consistency: SearchExplanationState is created in Task 2 and consumed by SearchResults and WorkspacePage in Task 3. Existing SearchExplainResponse and explainSearch signatures remain unchanged.
- Scope: Only frontend presentation, Workspace state, tests, and styles are modified; backend and API client work are explicitly excluded.
