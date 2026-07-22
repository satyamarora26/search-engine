import { LoaderCircle, RotateCcw } from 'lucide-react'

import type { JobStatusResponse } from '../api/types'
import { HealthBadge } from './HealthBadge'

type JobProgressProps = {
  error?: string | null
  isLoading?: boolean
  job: JobStatusResponse | null
  onReset: () => void
}

function count(result: Record<string, unknown> | null, key: string): number {
  const value = result?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export function JobProgress({ error, isLoading = false, job, onReset }: JobProgressProps) {
  if (error) {
    return <div className="inline-error" role="alert"><strong>Status unavailable.</strong><span>{error}</span></div>
  }

  if (isLoading || !job) {
    return <div className="crawl-loading" aria-live="polite"><LoaderCircle className="spin" size={18} aria-hidden="true" /> Loading crawl status...</div>
  }

  const isFailed = job.status === 'FAILURE' || !job.successful && job.ready
  const tone = isFailed ? 'failed' : job.ready ? 'healthy' : 'pending'
  const label = isFailed ? 'Failed' : job.ready ? 'Complete' : 'In progress'
  const rawPercentage = job.progress.percentage ?? (
    job.progress.total ? job.progress.current / job.progress.total * 100 : 0
  )
  const percentage = Math.max(0, Math.min(100, rawPercentage))

  return (
    <div className="job-progress">
      <div className="job-progress-heading">
        <div>
          <p className="panel-eyebrow">Job {job.job_id.slice(0, 8)}</p>
          <h2 className="job-progress-title">{job.progress.message ?? 'Preparing crawl...'}</h2>
        </div>
        <HealthBadge label={label} tone={tone} />
      </div>

      <div
        className="progress-track crawl-progress-track"
        role="progressbar"
        aria-label={`${percentage}% complete`}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={percentage}
      >
        <span style={{ width: `${percentage}%` }} />
      </div>
      <div className="job-progress-meta">
        <span>{job.progress.current} of {job.progress.total ?? '—'} units</span>
        <span>{percentage}%</span>
      </div>

      {job.ready && (
        <>
          {isFailed && <p className="crawl-failure" role="alert">{job.error ?? 'The crawl did not complete.'}</p>}
          <div className="crawl-counts" aria-label="Crawl result counts">
            <span><strong>{count(job.result, 'discovered_count')}</strong> discovered</span>
            <span><strong>{count(job.result, 'fetched_count')}</strong> fetched</span>
            <span><strong>{count(job.result, 'imported_count')}</strong> imported</span>
            <span><strong>{count(job.result, 'duplicate_skipped_count')}</strong> skipped</span>
            <span><strong>{count(job.result, 'failed_count')}</strong> failed</span>
          </div>
          <button className="button button-quiet" type="button" onClick={onReset}>
            <RotateCcw size={15} aria-hidden="true" />
            Submit another crawl
          </button>
        </>
      )}
    </div>
  )
}
