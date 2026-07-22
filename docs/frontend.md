# Search Engine Frontend

The frontend is a React + TypeScript app built with Vite. It provides the
search workspace, Wikipedia crawl controls, and document library for the
existing FastAPI service.

## Local Development

Start the backend dependencies from the repository root:

```bash
docker compose up -d postgres redis
alembic upgrade head
celery -A app.workers.celery_app.celery_app worker --loglevel=info
uvicorn app.main:app --reload
```

In a second terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Vite serves the app at `http://localhost:5173` by default. Requests beginning
with `/api` are proxied to FastAPI at `http://127.0.0.1:8000`, so the browser
does not need a separate API base URL or frontend copy of backend credentials.

## Routes

- `/` or `/workspace`: search with BM25 or TF-IDF and inspect index context.
- `/crawls`: submit a bounded Wikipedia crawl, monitor its job, and review
  page outcomes.
- `/library`: paginate stored documents and inspect a selected document.

The last submitted crawl job id is stored only in this browser's
`localStorage`. It lets the workspace and crawl view reconnect to the most
recent job without adding a recent-jobs endpoint. Documents, job results, and
search data remain owned by the backend.

## Verification

Run the frontend checks from `frontend/`:

```bash
npm test -- --run
npm run build
```

The frontend tests mock the typed API client, so they do not require
PostgreSQL, Redis, Celery, or a running FastAPI process.
