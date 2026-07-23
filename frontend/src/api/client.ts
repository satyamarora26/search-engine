import type {
  AcceptedJob,
  Document,
  DocumentListResponse,
  HealthResponse,
  JobStatusResponse,
  SearchExplainResponse,
  SearchRanking,
  SearchResponse,
  SearchScope,
  WikipediaCrawlItemListResponse,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(
    status: number,
    message: string,
    detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function requestJson<T>(
  input: RequestInfo,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  const payload: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    const detail = readDetail(payload)
    const message =
      typeof detail === 'string'
        ? detail
        : `Request failed with status ${response.status}.`
    throw new ApiError(response.status, message, detail)
  }

  return payload as T
}

function readDetail(payload: unknown): unknown {
  if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
    return payload.detail
  }
  return undefined
}

export function searchDocuments(
  query: string,
  ranking: SearchRanking,
  limit = 10,
  options: {
    offset?: number
    scope?: SearchScope
    exact_phrase?: boolean
    source?: string
    created_from?: string
    created_to?: string
  } = {},
): Promise<SearchResponse> {
  const params = new URLSearchParams({
    q: query,
    ranking,
    limit: String(limit),
  })
  if (options.offset) {
    params.set('offset', String(options.offset))
  }
  if (options.scope && options.scope !== 'all') {
    params.set('scope', options.scope)
  }
  if (options.exact_phrase) {
    params.set('exact_phrase', 'true')
  }
  const source = options.source?.trim()
  if (source) {
    params.set('source', source)
  }
  const createdFrom = options.created_from?.trim()
  if (createdFrom) {
    params.set('created_from', createdFrom)
  }
  const createdTo = options.created_to?.trim()
  if (createdTo) {
    params.set('created_to', createdTo)
  }
  return requestJson<SearchResponse>(`/api/v1/search?${params}`)
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/api/v1/health')
}

export function explainSearch(
  query: string,
  documentId: number,
): Promise<SearchExplainResponse> {
  const params = new URLSearchParams({
    q: query,
    document_id: String(documentId),
  })
  return requestJson<SearchExplainResponse>(`/api/v1/search/explain?${params}`)
}

export function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  return requestJson<JobStatusResponse>(`/api/v1/jobs/${encodeURIComponent(jobId)}`)
}

export function submitWikipediaCrawl(input: {
  category: string
  max_articles: number
  max_depth: number
}): Promise<AcceptedJob> {
  return requestJson<AcceptedJob>('/api/v1/crawls/wikipedia', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function listWikipediaCrawlItems(
  jobId: string,
  limit = 100,
  offset = 0,
): Promise<WikipediaCrawlItemListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  return requestJson<WikipediaCrawlItemListResponse>(
    `/api/v1/crawls/wikipedia/${encodeURIComponent(jobId)}/items?${params}`,
  )
}

export function listDocuments(
  limit = 20,
  offset = 0,
): Promise<DocumentListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  return requestJson<DocumentListResponse>(`/api/v1/documents?${params}`)
}

export function getDocument(documentId: number): Promise<Document> {
  return requestJson<Document>(`/api/v1/documents/${documentId}`)
}
