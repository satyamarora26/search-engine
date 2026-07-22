import { ArrowRight, Clock3, LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'

import { getJobStatus } from '../api/client'
import type { JobStatusResponse } from '../api/types'
import { readLastCrawlJobId } from '../state/localPreferences'
import { HealthBadge } from './HealthBadge'

const POLL_DELAY_MS = 1500

export function CrawlStatusPanel() {
  const [jobId] = useState(readLastCrawlJobId)
  const [job, setJob] = useState<JobStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId) return

    let cancelled = false
    let timeout: number | undefined

    const poll = async () => {
      try {
        const nextJob = await getJobStatus(jobId)
        if (cancelled) return
        setJob(nextJob)
        setError(null)
        if (!nextJob.ready) timeout = window.setTimeout(poll, POLL_DELAY_MS)
      } catch (requestError) {
        if (cancelled) return
        setError(requestError instanceof Error ? requestError.message : 'Could not read crawl status.')
      }
    }

    void poll()
    return () => {
      cancelled = true
      if (timeout) window.clearTimeout(timeout)
    }
  }, [jobId])

  if (!jobId) {
    return (
      <div className="status-empty">
        <Clock3 size={18} aria-hidden="true" />
        <div><strong>No crawl activity yet</strong><p>Start a Wikipedia crawl to see its progress here.</p></div>
      </div>
    )
  }

  if (error) {
    return <div className="inline-error" role="alert"><strong>Status unavailable.</strong><span>{error}</span></div>
  }

  if (!job) {
    return <div className="status-loading" aria-live="polite"><LoaderCircle className="spin" size={18} aria-hidden="true" /> Loading crawl status...</div>
  }

  const isFailed = job.status === 'FAILURE'
  const tone = isFailed ? 'failed' : job.ready ? 'healthy' : 'pending'
  const percentage = job.progress.percentage ?? 0

  return (
    <div className="crawl-status-content">
      <div className="status-heading">
        <HealthBadge label={isFailed ? 'Failed' : job.ready ? 'Complete' : 'In progress'} tone={tone} />
        <span className="status-job-id">{job.job_id.slice(0, 8)}</span>
      </div>
      <p className="status-message">{job.progress.message ?? 'Preparing crawl...'}</p>
      <div className="progress-track" aria-label={`${percentage}% complete`} role="progressbar" aria-valuemax={100} aria-valuemin={0} aria-valuenow={percentage}>
        <span style={{ width: `${percentage}%` }} />
      </div>
      <div className="status-meta"><span>{job.progress.current} of {job.progress.total ?? '—'} units</span><span>{percentage}%</span></div>
      <a className="text-link" href="/crawls">Open crawl details <ArrowRight size={14} aria-hidden="true" /></a>
    </div>
  )
}
