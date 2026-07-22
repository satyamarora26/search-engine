const LAST_CRAWL_JOB_KEY = 'search-engine:last-crawl-job'

export function readLastCrawlJobId(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(LAST_CRAWL_JOB_KEY)
}

export function writeLastCrawlJobId(jobId: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(LAST_CRAWL_JOB_KEY, jobId)
}
