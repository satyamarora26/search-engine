import { ArrowRight, CircleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  ApiError,
  getJobStatus,
  listMediumCrawlItems,
  listWikipediaCrawlItems,
  submitMediumCrawl,
  submitWikipediaCrawl,
} from '../api/client'
import type { CrawlItem, JobStatusResponse } from '../api/types'
import { readLastCrawlJobId, writeLastCrawlJobId } from '../state/localPreferences'
import { CrawlItemsTable } from '../components/CrawlItemsTable'
import { JobProgress } from '../components/JobProgress'
import { Panel } from '../components/Panel'
import { CrawlForm, type CrawlFormValues, type CrawlSource } from '../components/WikipediaCrawlForm'

const POLL_DELAY_MS = 1500

type CrawlError = Error | ApiError

function sourceFromJob(job: JobStatusResponse): CrawlSource {
  return job.job_type === 'medium_crawl' ? 'medium' : 'wikipedia'
}

function normalizeWikipediaItems(items: Awaited<ReturnType<typeof listWikipediaCrawlItems>>['items']): CrawlItem[] {
  return items.map((item) => ({
    position: item.position,
    source_item_id: String(item.wikipedia_page_id),
    title: item.title,
    url: item.url,
    fetch_status: item.fetch_status,
    ingestion_status: item.ingestion_status,
    document_id: item.document_id,
    error: item.error,
  }))
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The crawl request could not be completed.'
}

function activeJobIdFromError(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  if (typeof error.detail !== 'object' || error.detail === null) return null
  const activeJobId = 'active_job_id' in error.detail ? error.detail.active_job_id : null
  return typeof activeJobId === 'string' ? activeJobId : null
}

export function CrawlsPage() {
  const [activeJobId, setActiveJobId] = useState<string | null>(readLastCrawlJobId)
  const [acceptedJobId, setAcceptedJobId] = useState<string | null>(null)
  const [job, setJob] = useState<JobStatusResponse | null>(null)
  const [items, setItems] = useState<CrawlItem[] | null>(null)
  const [itemTotal, setItemTotal] = useState<number | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isLoadingStatus, setIsLoadingStatus] = useState(Boolean(activeJobId))
  const [isLoadingItems, setIsLoadingItems] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [itemsError, setItemsError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<CrawlError | null>(null)

  useEffect(() => {
    if (!activeJobId) return

    let cancelled = false
    let timeout: number | undefined
    setIsLoadingStatus(true)

    const poll = async () => {
      try {
        const nextJob = await getJobStatus(activeJobId)
        if (cancelled) return
        setJob(nextJob)
        setStatusError(null)
        setIsLoadingStatus(false)
        if (!nextJob.ready) timeout = window.setTimeout(poll, POLL_DELAY_MS)
      } catch (error) {
        if (cancelled) return
        setIsLoadingStatus(false)
        setStatusError(errorMessage(error))
      }
    }

    void poll()
    return () => {
      cancelled = true
      if (timeout) window.clearTimeout(timeout)
    }
  }, [activeJobId])

  useEffect(() => {
    if (!activeJobId || !job?.ready) return

    let cancelled = false
    setIsLoadingItems(true)
    setItemsError(null)
    const currentSource = sourceFromJob(job)

    const itemRequest = currentSource === 'medium'
      ? listMediumCrawlItems(activeJobId)
      : listWikipediaCrawlItems(activeJobId).then((response) => ({
        ...response,
        items: normalizeWikipediaItems(response.items),
      }))

    itemRequest
      .then((response) => {
        if (cancelled) return
        setItems(response.items)
        setItemTotal(response.total_results)
        setIsLoadingItems(false)
      })
      .catch((error) => {
        if (cancelled) return
        setIsLoadingItems(false)
        setItemsError(errorMessage(error))
      })

    return () => {
      cancelled = true
    }
  }, [activeJobId, job])

  async function handleSubmit(values: CrawlFormValues) {
    setIsSubmitting(true)
    setSubmitError(null)
    setStatusError(null)
    setItemsError(null)
    setJob(null)
    setItems(null)
    setItemTotal(null)
    setAcceptedJobId(null)

    try {
      const accepted = values.source === 'medium'
        ? await submitMediumCrawl({
          publication_url: values.publication_url,
          max_articles: values.max_articles,
          max_depth: values.max_depth,
        })
        : await submitWikipediaCrawl({
          category: values.category,
          max_articles: values.max_articles,
          max_depth: values.max_depth,
        })
      writeLastCrawlJobId(accepted.job_id)
      setAcceptedJobId(accepted.job_id)
      setActiveJobId(accepted.job_id)
    } catch (error) {
      setSubmitError(error instanceof Error ? error : new Error(errorMessage(error)))
    } finally {
      setIsSubmitting(false)
    }
  }

  function resetCrawl() {
    setAcceptedJobId(null)
    setJob(null)
    setItems(null)
    setItemTotal(null)
    setSubmitError(null)
    setStatusError(null)
    setItemsError(null)
    setActiveJobId(null)
  }

  const duplicateJobId = submitError ? activeJobIdFromError(submitError) : null

  return (
    <>
      <section className="page-intro" aria-labelledby="crawls-title">
        <p className="page-eyebrow">Multi-source ingestion</p>
        <h1 id="crawls-title">Bring new knowledge in.</h1>
        <p className="page-copy">Start a bounded crawl and watch every page move through discovery, fetching, and indexing.</p>
      </section>

      <div className="crawls-grid">
        <div className="crawls-primary">
          <Panel eyebrow="New ingestion job" title="Start a crawl">
            <CrawlForm isSubmitting={isSubmitting} onSubmit={handleSubmit} />
          </Panel>

          {submitError && (
            <div className="inline-error crawl-request-error" role="alert">
              <CircleAlert size={17} aria-hidden="true" />
              <div>
                <strong>{errorMessage(submitError)}</strong>
                {duplicateJobId && <span className="crawl-duplicate-job">Active job: {duplicateJobId}</span>}
              </div>
              {duplicateJobId ? (
                <a className="text-link" href="/crawls">Open current crawl <ArrowRight size={14} aria-hidden="true" /></a>
              ) : (
                <button className="button button-quiet" type="button" onClick={() => setSubmitError(null)}>Submit another crawl</button>
              )}
            </div>
          )}

          {(acceptedJobId || activeJobId) && (
            <Panel className="crawl-progress-panel" eyebrow="Crawl monitor" title="Current run">
              {acceptedJobId && <p className="crawl-accepted" role="status">Crawl accepted <span>Job {acceptedJobId.slice(0, 8)}</span></p>}
              <JobProgress error={statusError} isLoading={isLoadingStatus} job={job} onReset={resetCrawl} />
            </Panel>
          )}

          {job?.ready && (
            <Panel className="crawl-items-panel" eyebrow="Item outcomes" title="What the worker found">
              <CrawlItemsTable error={itemsError} isLoading={isLoadingItems} items={items} total={itemTotal} />
            </Panel>
          )}
        </div>

        <aside className="crawls-secondary">
          <Panel className="crawl-notes-panel" eyebrow="How it works" title="A bounded pipeline">
            <ol className="crawl-steps">
              <li><strong>Discover</strong><span>Find bounded source items through the source adapter.</span></li>
              <li><strong>Fetch</strong><span>Retrieve article content with retry-safe workers.</span></li>
              <li><strong>Index</strong><span>Clean documents enter the shared search corpus.</span></li>
            </ol>
          </Panel>
          <p className="crawl-footnote">Only one index-changing job runs at a time. Existing crawl activity stays attached to this browser.</p>
        </aside>
      </div>
    </>
  )
}
