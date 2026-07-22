import { FileText, LoaderCircle, MoreHorizontal } from 'lucide-react'

import type { Document } from '../api/types'

type DocumentListProps = {
  error?: string | null
  isLoading?: boolean
  documents: Document[] | null
  selectedDocumentId: number | null
  onRetry: () => void
  onSelect: (documentId: number) => void
}

export function DocumentList({
  error,
  isLoading = false,
  documents,
  selectedDocumentId,
  onRetry,
  onSelect,
}: DocumentListProps) {
  if (isLoading) {
    return <div className="document-list-state" aria-live="polite"><LoaderCircle className="spin" size={18} aria-hidden="true" /> Loading documents...</div>
  }

  if (error) {
    return (
      <div className="inline-error document-list-error" role="alert">
        <strong>Library unavailable.</strong>
        <span>{error}</span>
        <button className="button button-quiet" type="button" onClick={onRetry}>Retry library</button>
      </div>
    )
  }

  if (!documents || documents.length === 0) {
    return (
      <div className="document-list-state document-list-empty">
        <FileText size={20} aria-hidden="true" />
        <div><strong>No documents in the index yet.</strong><p>Run a Wikipedia crawl to add searchable pages.</p></div>
      </div>
    )
  }

  return (
    <div className="document-list" aria-label="Stored documents">
      {documents.map((document) => (
        <button
          className={`document-list-row ${selectedDocumentId === document.id ? 'document-list-row-selected' : ''}`.trim()}
          key={document.id}
          type="button"
          aria-pressed={selectedDocumentId === document.id}
          style={{ minWidth: 0, overflowWrap: 'anywhere' }}
          onClick={() => onSelect(document.id)}
        >
          <FileText className="document-list-icon" size={18} aria-hidden="true" />
          <span className="document-list-copy">
            <strong>{document.title}</strong>
            <span className="document-list-url">{document.url ?? 'No source URL'}</span>
          </span>
          <MoreHorizontal className="document-list-more" size={17} aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
