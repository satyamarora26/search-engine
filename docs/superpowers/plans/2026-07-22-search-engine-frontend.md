# Search Engine Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a responsive React + Vite interface for searching documents, launching Wikipedia crawls, monitoring jobs, and browsing the document library.

**Architecture:** Create a self-contained TypeScript application in `frontend/`. A typed API client owns all FastAPI calls and normalized errors; pages own workflow state; focused components render the hybrid workspace, crawl workflow, and library. Vite proxies relative `/api` requests to the existing FastAPI process on port 8000.

**Tech Stack:** React, TypeScript, Vite, Lucide React icons, Vitest, Testing Library, CSS custom properties, and the existing FastAPI/PostgreSQL/Redis/Celery backend.

## Global Constraints

- Use the approved hybrid workspace and editorial index visual direction.
- Use warm paper balanced by white surfaces, graphite text, deep blue actions, muted green success states, and muted red failures.
- Use serif display moments and IBM Plex Sans-style sans typography for controls and metadata.
- Keep panels compact with borders and an 8px radius.
- Do not add a marketing hero, gradients, decorative blobs, or oversized empty space.
- Do not add backend endpoints unless the frontend exposes a genuine missing contract.
- Store only device-local UI state in browser storage; documents and jobs remain backend-owned.
- Store the last submitted crawl job id in `localStorage` for the workspace status panel.
- Keep all user-facing text readable at desktop and mobile widths with no overlap or clipping.
- Use lucide icons inside icon buttons and provide accessible labels/tooltips for unfamiliar icons.
- Commit each completed task with a focused message and push it to `origin main`.

---

### Task 1: Scaffold The React + Vite Frontend

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles/global.css`
- Create: `frontend/src/test/setup.ts`

**Interfaces:**
- Consumes: Node.js 22+, npm, and the approved frontend design spec.
- Produces: `npm run dev`, `npm run build`, and `npm test` scripts with a compiling React entrypoint.

- [ ] **Step 1: Scaffold the Vite application**

Run from the repository root:

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install lucide-react
npm install --save-dev vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

The generated application is the only frontend root. Do not create a second
package or copy the backend into it.

- [ ] **Step 2: Configure the API proxy and test environment**

Set `frontend/vite.config.ts` to proxy API requests without hard-coding a
production URL:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
});
```

Set the test setup to import `@testing-library/jest-dom` and update
`frontend/package.json` scripts to:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest"
  }
}
```

- [ ] **Step 3: Replace the starter screen with a minimal application root**

Use `frontend/src/main.tsx` to import `./styles/global.css` and render `<App />`.
Use `frontend/src/App.tsx` to render a temporary accessible heading:

```tsx
export default function App() {
  return <main><h1>Index</h1></main>;
}
```

The starter counter, logos, and generic Vite copy must not remain.

- [ ] **Step 4: Add the initial editorial tokens**

Define these CSS variables in `frontend/src/styles/global.css`:

```css
:root {
  --paper: #f4efe7;
  --surface: #fffdf9;
  --surface-muted: #eee8df;
  --ink: #24231f;
  --ink-muted: #716c64;
  --line: #ded4c7;
  --blue: #244f75;
  --blue-strong: #163b5e;
  --green: #5c7830;
  --green-soft: #e3efd0;
  --red: #a34d43;
  --red-soft: #f6e3df;
  --radius: 8px;
  --shadow-soft: 0 10px 28px rgb(52 43 32 / 8%);
}
```

Add the global box-sizing rule, readable system fallbacks, visible focus ring,
and a `prefers-reduced-motion` rule before any page styling is added.

- [ ] **Step 5: Build and commit the scaffold**

Run:

```bash
cd frontend
npm run build
npm test -- --run
```

Expected: Vite build succeeds and the test runner exits with no test files
failing. Commit and push:

```bash
git add frontend
git commit -m "feat: scaffold React search frontend"
git push origin main
```

### Task 2: Create The Typed Backend API Client

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/client.test.ts`

**Interfaces:**
- Consumes: Existing endpoints under `/api/v1`.
- Produces: Typed functions `searchDocuments`, `getJobStatus`, `submitWikipediaCrawl`, `listWikipediaCrawlItems`, `listDocuments`, and `getDocument`.

- [ ] **Step 1: Define response contracts**

Add these TypeScript shapes to `frontend/src/api/types.ts`:

```ts
export type SearchRanking = "bm25" | "tfidf";
export type JobStatus = "PENDING" | "STARTED" | "SUCCESS" | "FAILURE";

export interface SearchResult {
  document_id: number;
  title: string;
  url: string | null;
  score: number;
  snippet: string;
  matched_terms: string[];
}

export interface SearchResponse {
  query: string;
  ranking: SearchRanking;
  total_results: number;
  index_version: string;
  results: SearchResult[];
}

export interface JobStatusResponse {
  job_id: string;
  job_type: string;
  status: JobStatus;
  ready: boolean;
  successful: boolean;
  progress: { current: number; total: number | null; percentage: number | null; message: string | null };
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface WikipediaCrawlItem {
  position: number;
  wikipedia_page_id: number;
  title: string;
  url: string;
  fetch_status: string;
  ingestion_status: string | null;
  document_id: number | null;
  error: string | null;
}

export interface Document {
  id: number;
  title: string;
  url: string | null;
  content: string;
  status: string;
  created_at: string;
  updated_at: string;
}
```

Also define the accepted-job response, crawl-item list response, and document
list response from the existing Pydantic schemas.

- [ ] **Step 2: Implement normalized request errors**

Implement this behavior in `frontend/src/api/client.ts`:

```ts
export class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly detail?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = typeof payload?.detail === "string" ? payload.detail : `Request failed with ${response.status}`;
    throw new ApiError(response.status, message, payload?.detail);
  }
  return payload as T;
}
```

Preserve response status and structured `detail` so pages can render `409`,
`422`, `503`, and `404` states distinctly.

- [ ] **Step 3: Add endpoint functions**

Implement these exact functions:

```ts
export function searchDocuments(query: string, ranking: SearchRanking, limit = 10): Promise<SearchResponse>;
export function getJobStatus(jobId: string): Promise<JobStatusResponse>;
export function submitWikipediaCrawl(input: { category: string; max_articles: number; max_depth: number }): Promise<AcceptedJob>;
export function listWikipediaCrawlItems(jobId: string, limit = 100, offset = 0): Promise<WikipediaCrawlItemListResponse>;
export function listDocuments(limit = 20, offset = 0): Promise<DocumentListResponse>;
export function getDocument(documentId: number): Promise<Document>;
```

Use `URLSearchParams` for query parameters and never concatenate unescaped
user input into endpoint URLs.

- [ ] **Step 4: Test request construction and errors**

In `frontend/src/api/client.test.ts`, mock `globalThis.fetch` and verify:

```ts
it("requests BM25 search with encoded query parameters", async () => {
  await searchDocuments("information retrieval", "bm25");
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/search?q=information+retrieval&ranking=bm25&limit=10",
    expect.any(Object),
  );
});

it("preserves a conflict response as ApiError", async () => {
  await expect(submitWikipediaCrawl({ category: "Featured articles", max_articles: 4, max_depth: 0 }))
    .rejects.toMatchObject({ status: 409 });
});
```

- [ ] **Step 5: Run and commit the API client**

Run `cd frontend && npm test -- --run`. Expected: API client tests pass. Commit:

```bash
git add frontend/src/api
git commit -m "feat: add typed frontend API client"
git push origin main
```

### Task 3: Build The Application Shell And Navigation

**Files:**
- Create: `frontend/src/state/routes.ts`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/SideNav.tsx`
- Create: `frontend/src/components/HealthBadge.tsx`
- Create: `frontend/src/components/Panel.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles/global.css`
- Test: `frontend/src/components/AppShell.test.tsx`

**Interfaces:**
- Consumes: Typed API contracts and editorial CSS tokens.
- Produces: Responsive shell with `workspace`, `crawls`, and `library` routes.

- [ ] **Step 1: Define route state without adding a router dependency**

Implement:

```ts
export type AppRoute = "workspace" | "crawls" | "library";
export function routeFromPath(pathname: string): AppRoute;
export function pathForRoute(route: AppRoute): string;
export function navigateTo(route: AppRoute): void;
```

Use `history.pushState` and a `popstate` listener. Unknown paths resolve to
`workspace`.

- [ ] **Step 2: Build the shell components**

`AppShell` must render the brand, navigation links, active route, a health badge,
and a `<main>` landmark. `SideNav` must use icon-plus-text links with these
Lucide icons: `Search`, `Globe2`, and `Library`. The mobile layout must replace
the desktop rail with a compact labeled navigation row.

- [ ] **Step 3: Add route-level loading placeholders**

`App.tsx` should switch on `AppRoute` and render temporary page headings until
Tasks 4 through 6 replace them. Keep the shell stable while routes change.

- [ ] **Step 4: Test navigation and accessibility landmarks**

Verify that the active link changes after click, browser back restores the prior
route, and the rendered document contains one `main` landmark and one level-one
heading. Verify the mobile navigation remains keyboard reachable.

- [ ] **Step 5: Run and commit the shell**

Run `cd frontend && npm test -- --run`. Commit:

```bash
git add frontend/src/App.tsx frontend/src/state frontend/src/components frontend/src/styles/global.css
git commit -m "feat: add responsive frontend shell"
git push origin main
```

### Task 4: Implement The Hybrid Workspace Search

**Files:**
- Create: `frontend/src/pages/WorkspacePage.tsx`
- Create: `frontend/src/components/SearchForm.tsx`
- Create: `frontend/src/components/SearchResultRow.tsx`
- Create: `frontend/src/components/SearchResults.tsx`
- Create: `frontend/src/components/CrawlStatusPanel.tsx`
- Create: `frontend/src/state/localPreferences.ts`
- Create: `frontend/src/pages/WorkspacePage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `searchDocuments`, `getJobStatus`, `SearchResponse`, `JobStatusResponse`.
- Produces: Search-first hybrid workspace and last-crawl status persistence.

- [ ] **Step 1: Implement local last-job preference helpers**

Add:

```ts
const LAST_CRAWL_JOB_KEY = "search-engine:last-crawl-job";
export function readLastCrawlJobId(): string | null;
export function writeLastCrawlJobId(jobId: string): void;
```

Guard browser storage access so server-like test environments return `null`
instead of throwing.

- [ ] **Step 2: Build the search form**

Use a labeled text input, ranking `<select>`, and icon-plus-text submit button.
Submit only when the trimmed query is nonblank. Preserve the query and ranking
when a request fails. Show a compact loading state while the request is active.

- [ ] **Step 3: Render result rows and result states**

Each row must show the title, source link, snippet, BM25/TF-IDF score, and
matched-term chips. Implement distinct components for loading, no query, no
results, and request error. Result links use `target="_blank"`
`rel="noreferrer"`.

- [ ] **Step 4: Build the crawler status panel**

On mount, read the last crawl job id. If present, poll `getJobStatus` every 1500
milliseconds only while status is `PENDING` or `STARTED`; stop on terminal state,
unmount, or error. Show phase message, current/total progress, percentage when
available, and a link to the Crawls route.

- [ ] **Step 5: Compose the hybrid desktop/mobile layout**

Place the search form and result list in the primary column. Place index health
and crawler status in the secondary column on desktop. Stack columns below
`760px`. Use CSS grid with stable minimum widths so result rows do not resize
when badges appear.

- [ ] **Step 6: Test the workspace workflow**

Add tests that verify:

```ts
it("submits a BM25 search and renders the returned result", async () => {
  vi.mocked(searchDocuments).mockResolvedValue({
    query: "information retrieval",
    ranking: "bm25",
    total_results: 1,
    index_version: "redis-test",
    results: [{
      document_id: 7,
      title: "Information retrieval",
      url: "https://example.com/ir",
      score: 1.09,
      snippet: "A concise explanation of indexing and ranking.",
      matched_terms: ["information", "retrieval"],
    }],
  });
  const user = userEvent.setup();
  render(<WorkspacePage />);
  await user.type(screen.getByLabelText("Search documents"), "information retrieval");
  await user.click(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByText("Information retrieval")).toBeVisible();
});

it("switches to TF-IDF in the request", async () => {
  const user = userEvent.setup();
  render(<WorkspacePage />);
  await user.type(screen.getByLabelText("Search documents"), "ranking");
  await user.selectOptions(screen.getByLabelText("Ranking"), "tfidf");
  await user.click(screen.getByRole("button", { name: "Search" }));
  expect(searchDocuments).toHaveBeenCalledWith("ranking", "tfidf", 10);
});

it("shows a retryable conflict or service error", async () => {
  vi.mocked(searchDocuments).mockRejectedValue(new ApiError(503, "Search service unavailable"));
  const user = userEvent.setup();
  render(<WorkspacePage />);
  await user.type(screen.getByLabelText("Search documents"), "ranking");
  await user.click(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Search service unavailable");
  expect(screen.getByRole("button", { name: "Retry search" })).toBeVisible();
});

it("polls the remembered crawl job only while active", async () => {
  vi.useFakeTimers();
  vi.mocked(getJobStatus)
    .mockResolvedValueOnce({ status: "STARTED", progress: { current: 1, total: 4, percentage: 25, message: "Fetching" } })
    .mockResolvedValueOnce({ status: "SUCCESS", progress: { current: 4, total: 4, percentage: 100, message: "Complete" } });
  render(<WorkspacePage />);
  await vi.advanceTimersByTimeAsync(3000);
  expect(getJobStatus).toHaveBeenCalledTimes(2);
  vi.useRealTimers();
});
```

- [ ] **Step 7: Run and commit the workspace**

Run `cd frontend && npm test -- --run`. Commit:

```bash
git add frontend/src/App.tsx frontend/src/pages/WorkspacePage.tsx frontend/src/components frontend/src/state frontend/src/styles
git commit -m "feat: add hybrid search workspace"
git push origin main
```

### Task 5: Implement Wikipedia Crawl Submission And Monitoring

**Files:**
- Create: `frontend/src/pages/CrawlsPage.tsx`
- Create: `frontend/src/components/WikipediaCrawlForm.tsx`
- Create: `frontend/src/components/JobProgress.tsx`
- Create: `frontend/src/components/CrawlItemsTable.tsx`
- Create: `frontend/src/pages/CrawlsPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `submitWikipediaCrawl`, `getJobStatus`, `listWikipediaCrawlItems`, and local job preference helpers.
- Produces: Complete crawl submission, progress, terminal result, and per-page outcome workflow.

- [ ] **Step 1: Add bounded form validation**

Start with:

```ts
const DEFAULT_CRAWL_FORM = {
  category: "Featured articles",
  max_articles: 100,
  max_depth: 0,
};
```

Validate trimmed category, `1 <= max_articles <= 500`, and `0 <= max_depth <= 2`
before calling the API. Keep invalid values in the form and attach errors to
their labels.

- [ ] **Step 2: Implement accepted-job and polling state**

After `submitWikipediaCrawl` returns, store its `job_id` with
`writeLastCrawlJobId`, show the accepted state, and poll `getJobStatus` every
1500ms until `SUCCESS` or `FAILURE`. The submit control remains disabled while
the request is active. A `409` error shows the active job id and links to the
current crawl view.

- [ ] **Step 3: Render progress and terminal outcome**

`JobProgress` must render `progress.message`, `current`, `total`, and
`percentage`. When the job is terminal, render the result counts from
`job.result` with safe fallbacks for missing values. A failed job renders its
safe `error` and a retryable “Submit another crawl” action.

- [ ] **Step 4: Render the crawl items table**

After terminal success or failure, load the item endpoint. Render position,
title, page id, fetch status, ingestion status, document id, and error. Use
status badges with text, not color alone. On narrow screens switch each row to
a stacked article outcome block rather than creating horizontal overflow.

- [ ] **Step 5: Test crawl states**

Add tests for bounded validation, accepted response, active polling, exact
result counts, duplicate status, fetch failure status, `409`, `422`, and `503`.
Use fake timers to prove polling stops after terminal `SUCCESS` and `FAILURE`.

- [ ] **Step 6: Run and commit the crawl workflow**

Run `cd frontend && npm test -- --run`. Commit:

```bash
git add frontend/src/App.tsx frontend/src/pages/CrawlsPage.tsx frontend/src/components frontend/src/state frontend/src/api frontend/src/pages/CrawlsPage.test.tsx
git commit -m "feat: add Wikipedia crawl controls"
git push origin main
```

### Task 6: Implement The Document Library

**Files:**
- Create: `frontend/src/pages/LibraryPage.tsx`
- Create: `frontend/src/components/DocumentList.tsx`
- Create: `frontend/src/components/DocumentDetail.tsx`
- Create: `frontend/src/pages/LibraryPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `listDocuments` and `getDocument`.
- Produces: Paginated document browsing with a selected document preview.

- [ ] **Step 1: Load paginated documents**

Request `listDocuments(20, offset)` on page load and when the offset changes.
Show the current page, previous/next controls, total page-size context, and a
clear empty state. Because the backend response reports the current page size,
disable “Next” when fewer than 20 documents are returned.

- [ ] **Step 2: Add document selection**

Clicking a document loads `getDocument(document.id)` and renders title, source
URL, status, timestamps, and a readable content preview. Preserve the list
selection when the detail request fails and show a retry action.

- [ ] **Step 3: Test library loading and overflow**

Verify list loading, empty state, next/previous controls, selected-document
loading, 404, and service-error states. Add a long-title and long-URL fixture
and assert the document row remains within its container at a 360px viewport.

- [ ] **Step 4: Run and commit the library**

Run `cd frontend && npm test -- --run`. Commit:

```bash
git add frontend/src/App.tsx frontend/src/pages/LibraryPage.tsx frontend/src/components frontend/src/api frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat: add document library view"
git push origin main
```

### Task 7: Responsive Polish, Accessibility, And Documentation

**Files:**
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/SideNav.tsx`
- Modify: `frontend/src/pages/WorkspacePage.tsx`
- Modify: `frontend/src/pages/CrawlsPage.tsx`
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Create: `docs/frontend.md`
- Create: `frontend/src/App.integration.test.tsx`

**Interfaces:**
- Consumes: Completed routes and component states from Tasks 1 through 6.
- Produces: Responsive, keyboard-usable frontend with reproducible local run instructions.

- [ ] **Step 1: Add responsive layout constraints**

Verify the following CSS behavior:

```css
.app-shell { min-height: 100vh; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, 340px); gap: 24px; }
@media (max-width: 760px) {
  .workspace-grid { grid-template-columns: 1fr; }
  .side-nav { position: static; display: flex; overflow-x: auto; }
  .result-row, .crawl-item { min-width: 0; overflow-wrap: anywhere; }
}
```

Use `min-width: 0` on grid children and `overflow-wrap: anywhere` for URLs and
long crawl titles. Do not use viewport-scaled font sizes.

- [ ] **Step 2: Audit accessibility**

Ensure every input has a visible label, every icon-only button has an
`aria-label` and tooltip, status uses text plus color, focus styles are visible,
and error messages use `role="alert"`. Use semantic buttons and links rather
than clickable generic containers.

- [ ] **Step 3: Add a browser-level integration test**

Mock the API client and verify a user can navigate Workspace -> Crawls ->
Library, submit a crawl, see progress, return to Workspace, and see the
remembered job status panel. Do not require PostgreSQL or Redis for frontend
tests.

- [ ] **Step 4: Document local development**

Create `docs/frontend.md` with:

```bash
docker compose up -d postgres redis
alembic upgrade head
celery -A app.workers.celery_app.celery_app worker --loglevel=info
uvicorn app.main:app --reload
cd frontend
npm install
npm run dev
```

Document the Vite URL, the FastAPI proxy, available routes, and the fact that
the last crawl job id is device-local browser state.

- [ ] **Step 5: Run the complete frontend verification**

Run:

```bash
cd frontend
npm test -- --run
npm run build
```

Then manually check the app at desktop and 360px mobile widths with the
backend running. Expected: no console errors, no clipped text, and all three
routes render their loading, empty, success, and error states.

- [ ] **Step 6: Commit and push the finished frontend**

Run `git diff --check` and `git status --short --branch`, then commit:

```bash
git add frontend docs/frontend.md
git commit -m "feat: complete search engine frontend"
git push origin main
```

Verify that `git rev-parse HEAD origin/main` prints the same commit twice and
that the worktree is clean.
