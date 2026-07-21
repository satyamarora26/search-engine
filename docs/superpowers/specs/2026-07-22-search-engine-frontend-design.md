# Search Engine Frontend Design

Date: 2026-07-22

## Goal

Build a polished React + Vite frontend for the existing FastAPI search engine.
The frontend should make the current backend usable as a personal knowledge
search product while keeping crawler operations visible and understandable.
The first milestone is a local, responsive interface; the backend remains the
source of truth and does not change as part of the initial frontend build.

## Product Direction

The selected direction is a **hybrid workspace** with an **editorial index**
visual language.

Search is the primary action, while crawler health and recent indexing activity
remain visible without dominating the screen. The product should feel like a
research notebook backed by reliable search infrastructure.

## Visual System

- Warm paper background balanced by white surfaces.
- Graphite text for long-form readability.
- Deep blue for primary actions, links, and selected navigation.
- Muted green for healthy, ready, and successful states.
- Muted red only for failures and destructive actions.
- Serif display moments for page titles and result titles.
- IBM Plex Sans-style sans typography for controls, metadata, and dense data.
- Compact panels with borders and an 8px radius.
- No marketing hero, gradients, decorative blobs, or oversized empty space.

The interface must remain readable at mobile widths. Text, controls, and result
metadata must wrap without clipping or overlapping.

## Information Architecture

The application has one shell with a responsive left navigation rail:

```text
Workspace       Search and index health
Crawls          Wikipedia crawl submission and job history
Library         Stored document browsing
```

On narrow screens the rail becomes a compact top navigation control. The active
route remains visible, and navigation does not depend on hover.

### Workspace

The first screen contains:

- A page header with product identity, active index health, and document count.
- A large search form with query input, ranking selector, and submit action.
- Search result rows showing title, source URL, snippet, score, and matched terms.
- A crawler status panel showing the most recent useful job state.
- Empty, loading, error, and no-results states.

Search calls `GET /api/v1/search` with `q`, `ranking`, and `limit`. The ranking
selector supports the backend's `bm25` and `tfidf` values. Result source URLs
open in a new browser tab with safe rel attributes.

### Crawls

The crawl screen contains:

- Category input defaulted to `Featured articles`.
- `max_articles` numeric control from 1 through 500.
- `max_depth` numeric control from 0 through 2.
- Submit button with disabled and submitting states.
- Active job progress with phase, current count, total, and percentage.
- Paginated item outcomes for imported, duplicate, and failed pages.
- Safe error display without raw HTML or payload contents.

Submission calls `POST /api/v1/crawls/wikipedia`. The accepted job is then
polled through `GET /api/v1/jobs/{job_id}` until `SUCCESS` or `FAILURE`. Once
terminal, the page loads
`GET /api/v1/crawls/wikipedia/{job_id}/items`.

### Library

The library screen uses the existing document endpoints:

- `GET /api/v1/documents` for paginated documents.
- `GET /api/v1/documents/{document_id}` for the selected document.
- Existing document title, source URL, status, and content preview.

Document creation and editing are not part of the first frontend pass unless
the implementation reveals a clear low-risk extension. The first pass focuses
on making search and crawler workflows complete.

## Component Boundaries

The frontend will be organized around focused modules:

```text
frontend/
  src/
    api/             typed fetch functions and response contracts
    components/      shell, navigation, result rows, status panels, forms
    pages/           workspace, crawls, library
    state/           route and request state helpers
    styles/          tokens, global styles, responsive rules
```

The API client owns URL construction, JSON parsing, and normalized errors.
Components do not construct endpoint URLs directly. Pages own workflow state
and pass typed data into presentational components.

## State And Error Handling

Every remote workflow has explicit states:

- `idle`: no request has started.
- `loading`: request is in progress and controls communicate that state.
- `success`: data is rendered with a refresh or next action where useful.
- `empty`: the request succeeded but has no data.
- `error`: a concise human-readable message is shown with a retry action.

Expected HTTP behavior:

- `409`: show the active job reference and link to its status.
- `422`: show field-level validation feedback where possible.
- `503`: show service-unavailable guidance and preserve the user's form input.
- `404`: show a not-found state for a missing document or job.

Polling stops on terminal job status, component unmount, or request failure.
It does not run continuously when the user is idle. Search requests are
explicitly submitted rather than firing on every keystroke.

## Local Development

The frontend will use Vite's development proxy so browser requests can remain
relative:

```text
Browser -> frontend dev server -> /api -> FastAPI on port 8000
```

The initial local commands will be:

```bash
cd frontend
npm install
npm run dev
```

The frontend must document the required FastAPI, PostgreSQL, Redis, and Celery
processes separately. No API secrets or database credentials belong in the
frontend bundle.

## Verification

The first implementation must verify:

- Production build succeeds.
- Workspace search renders loading, empty, error, and result states.
- BM25 and TF-IDF selection changes the request parameter.
- Crawl submission validates bounds and shows accepted job state.
- Crawl polling reaches terminal success and displays item outcomes.
- `409`, `422`, `503`, and failed-job states are visible and recoverable.
- Library pagination renders documents without layout overflow.
- Desktop and mobile layouts have no clipped or overlapping text.
- Keyboard focus is visible for navigation, forms, and actions.

The initial frontend test suite can use a mocked API client for component and
workflow tests. The existing backend integration suite remains the contract
test for the actual API and crawler behavior.

## Out Of Scope

- Authentication and multi-user permissions.
- Server-side rendering or deployment configuration.
- Replacing the BM25 implementation.
- New backend endpoints unless the frontend exposes a genuine missing contract.
- File uploads, PDF extraction, analytics dashboards, or scheduled crawling.
