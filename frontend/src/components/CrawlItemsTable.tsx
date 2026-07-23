import { ExternalLink } from 'lucide-react'

import type { CrawlItem } from '../api/types'
import { HealthBadge } from './HealthBadge'

type CrawlItemsTableProps = {
  error?: string | null
  isLoading?: boolean
  items: CrawlItem[] | null
  total: number | null
}

function statusTone(status: string | null): 'healthy' | 'pending' | 'failed' {
  if (!status) return 'pending'
  const normalized = status.toLowerCase()
  if (normalized === 'failed' || normalized === 'failure') return 'failed'
  if (normalized === 'pending' || normalized === 'processing') return 'pending'
  return 'healthy'
}

function statusLabel(status: string | null): string {
  return status ? status.replaceAll('_', ' ') : 'Not started'
}

export function CrawlItemsTable({ error, isLoading = false, items, total }: CrawlItemsTableProps) {
  if (isLoading) return <div className="crawl-items-state">Loading item outcomes...</div>
  if (error) return <div className="inline-error crawl-items-error" role="alert"><strong>Items unavailable.</strong><span>{error}</span></div>
  if (!items || items.length === 0) return <div className="crawl-items-state">No item outcomes were recorded for this crawl.</div>

  return (
    <div className="crawl-items-wrap">
      <div className="crawl-items-summary">{total ?? items.length} item outcomes</div>
      <div className="crawl-items-list" role="table" aria-label="Crawl item outcomes">
        <div className="crawl-items-header" role="row">
          <span>Item</span>
          <span>Fetch</span>
          <span>Index</span>
          <span>Document</span>
        </div>
        {items.map((item) => (
          <article className="crawl-item-row" key={`${item.source_item_id ?? item.url}-${item.position}`} role="row">
            <div className="crawl-item-page" role="cell">
              <span className="crawl-item-position">{String(item.position + 1).padStart(2, '0')}</span>
              <div>
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.title ?? 'Untitled item'}
                  <ExternalLink size={13} aria-hidden="true" />
                </a>
                {item.source_item_id && <span className="crawl-item-page-id">Source item {item.source_item_id}</span>}
              </div>
            </div>
            <div className="crawl-item-cell" data-label="Fetch" role="cell">
              <HealthBadge label={statusLabel(item.fetch_status)} tone={statusTone(item.fetch_status)} />
            </div>
            <div className="crawl-item-cell" data-label="Index" role="cell">
              <HealthBadge label={statusLabel(item.ingestion_status)} tone={statusTone(item.ingestion_status)} />
            </div>
            <div className="crawl-item-cell" data-label="Document" role="cell">
              {item.document_id ? <span className="document-id">#{item.document_id}</span> : <span className="not-indexed">Not indexed</span>}
              {item.error && <span className="crawl-item-error">{item.error}</span>}
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}
