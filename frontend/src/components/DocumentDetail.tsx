import { ExternalLink, LoaderCircle, RotateCcw } from 'lucide-react'

import type { Document } from '../api/types'
import { HealthBadge } from './HealthBadge'

type DocumentDetailProps = {
  document: Document | null
  error?: string | null
  isLoading?: boolean
  onRetry: () => void
  selectedDocumentId: number | null
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function DocumentDetail({
  document,
  error,
  isLoading = false,
  onRetry,
  selectedDocumentId,
}: DocumentDetailProps) {
  if (selectedDocumentId === null) {
    return <div className="document-detail-empty">Select a document to inspect its source and content.</div>
  }

  if (isLoading) {
    return <div className="document-detail-state" aria-live="polite"><LoaderCircle className="spin" size={18} aria-hidden="true" /> Loading document...</div>
  }

  if (error) {
    return (
      <div className="document-detail-state document-detail-error" role="alert">
        <strong>Document unavailable.</strong>
        <span>{error}</span>
        <button className="button button-quiet" type="button" onClick={onRetry}>
          <RotateCcw size={15} aria-hidden="true" />
          Retry document
        </button>
      </div>
    )
  }

  if (!document) return null

  return (
    <article className="document-detail">
      <div className="document-detail-heading">
        <div>
          <p className="panel-eyebrow">Document {document.id}</p>
          <h2>{document.title}</h2>
        </div>
        <HealthBadge label={document.status} />
      </div>

      {document.url && (
        <a className="document-detail-source" href={document.url} target="_blank" rel="noreferrer">
          <ExternalLink size={14} aria-hidden="true" />
          <span>Open source</span>
        </a>
      )}

      <div className="document-detail-meta">
        <span>Added {formatTimestamp(document.created_at)}</span>
        <span>Updated {formatTimestamp(document.updated_at)}</span>
      </div>

      <div className="document-content">
        <p>{document.content}</p>
      </div>
    </article>
  )
}
