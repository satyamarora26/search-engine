import { ArrowRight, CircleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  ApiError,
  getJobStatus,
  listWikipediaCrawlItems,
  submitWikipediaCrawl,
} from '../api/client'
import type { JobStatusResponse, WikipediaCrawlItem } from '../api/types'
import { readLastCrawlJobId, writeLastCrawlJobId } from '../state/localPreferences'
import { CrawlItemsTable } from '../components/CrawlItemsTable'
import { JobProgress } from '../components/JobProgress'
import { Panel } from '../components/Panel'
import { WikipediaCrawlForm, type CrawlFormValues } from '../components/WikipediaCrawlForm'

const POLL_DELAY_MS = 1500

type CrawlError = Error | ApiError

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
  const [items, setItems] = useState<WikipediaCrawlItem[] | null>(null)
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

    listWikipediaCrawlItems(activeJobId)
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
      const accepted = await submitWikipediaCrawl(values)
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
        <p className="page-eyebrow">Wikipedia ingestion</p>
        <h1 id="crawls-title">Bring new knowledge in.</h1>
        <p className="page-copy">Start a bounded crawl and watch every page move through discovery, fetching, and indexing.</p>
      </section>

      <div className="crawls-grid">
        <div className="crawls-primary">
          <Panel eyebrow="New ingestion job" title="Start a Wikipedia crawl">
            <WikipediaCrawlForm isSubmitting={isSubmitting} onSubmit={handleSubmit} />
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
            <Panel className="crawl-items-panel" eyebrow="Page outcomes" title="What the worker found">
              <CrawlItemsTable error={itemsError} isLoading={isLoadingItems} items={items} total={itemTotal} />
            </Panel>
          )}
        </div>

        <aside className="crawls-secondary">
          <Panel className="crawl-notes-panel" eyebrow="How it works" title="A bounded pipeline">
            <ol className="crawl-steps">
              <li><strong>Discover</strong><span>Walk categories up to the depth you set.</span></li>
              <li><strong>Fetch</strong><span>Retrieve article content with retry-safe workers.</span></li>
              <li><strong>Index</strong><span>Clean pages enter the shared search corpus.</span></li>
            </ol>
          </Panel>
          <p className="crawl-footnote">Only one index-changing job runs at a time. Existing crawl activity stays attached to this browser.</p>
        </aside>
      </div>
    </>
  )
}
