export type SearchRanking = 'bm25' | 'tfidf'
export type JobStatus = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE'

export interface SearchResult {
  document_id: number
  title: string
  url: string | null
  score: number
  snippet: string
  matched_terms: string[]
}

export interface SearchResponse {
  query: string
  ranking: SearchRanking
  total_results: number
  index_version: string
  results: SearchResult[]
}

export interface SearchExplainTerm {
  term: string
  term_frequency: number
  document_frequency: number
  idf: number
  contribution: number
}

export interface SearchExplainResponse {
  query: string
  ranking: 'bm25'
  document_id: number
  final_score: number
  terms: SearchExplainTerm[]
}

export interface JobProgress {
  current: number
  total: number | null
  percentage: number | null
  message: string | null
}

export interface AcceptedJob {
  job_id: string
  status: string
  status_url: string
}

export interface JobStatusResponse {
  job_id: string
  job_type: string
  status: JobStatus
  ready: boolean
  successful: boolean
  progress: JobProgress
  result: Record<string, unknown> | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface WikipediaCrawlItem {
  position: number
  wikipedia_page_id: number
  title: string
  url: string
  fetch_status: string
  ingestion_status: string | null
  document_id: number | null
  error: string | null
}

export interface WikipediaCrawlItemListResponse {
  job_id: string
  total_results: number
  limit: number
  offset: number
  items: WikipediaCrawlItem[]
}

export interface Document {
  id: number
  title: string
  url: string | null
  content: string
  status: string
  created_at: string
  updated_at: string
}

export interface DocumentListResponse {
  total_results: number
  limit: number
  offset: number
  documents: Document[]
}
