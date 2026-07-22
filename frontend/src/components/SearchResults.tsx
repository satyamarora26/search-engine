import { ChevronLeft, ChevronRight } from 'lucide-react'

import type { SearchResponse } from '../api/types'

import type { SearchExplanationState } from './SearchExplanation'
import { SearchResultRow } from './SearchResultRow'

type SearchResultsProps = {
  explanations: Record<number, SearchExplanationState>
  expandedExplanationId: number | null
  hasSubmitted: boolean
  isLoading: boolean
  onPageChange: (offset: number) => void
  onRetryExplanation: (documentId: number) => void
  onToggleExplanation: (documentId: number) => void
  response: SearchResponse | null
  showExplanations: boolean
}

export function SearchResults({
  explanations,
  expandedExplanationId,
  hasSubmitted,
  isLoading,
  onPageChange,
  onRetryExplanation,
  onToggleExplanation,
  response,
  showExplanations,
}: SearchResultsProps) {
  if (isLoading) {
    return (
      <div className="result-state result-loading" aria-live="polite">
        <span className="loading-line loading-line-wide" />
        <span className="loading-line" />
        <span className="loading-line loading-line-short" />
      </div>
    )
  }

  if (!hasSubmitted) {
    return <div className="result-state"><p>Search across your indexed documents to begin.</p></div>
  }

  if (!response || response.results.length === 0) {
    return <div className="result-state"><p>No matching documents yet. Try a broader phrase.</p></div>
  }

  const pageCount = Math.max(1, Math.ceil(response.total_results / response.limit))
  const pageNumber = Math.floor(response.offset / response.limit) + 1
  const canGoPrevious = response.offset > 0
  const canGoNext = response.offset + response.results.length < response.total_results

  return (
    <>
      <div className="results-meta" aria-live="polite">
        <span>{response.total_results} results</span>
      </div>
      <div className="results-list">
        {response.results.map((result, index) => (
          <SearchResultRow
            explanation={explanations[result.document_id]}
            isExplanationExpanded={expandedExplanationId === result.document_id}
            onRetryExplanation={() => onRetryExplanation(result.document_id)}
            onToggleExplanation={() => onToggleExplanation(result.document_id)}
            key={result.document_id}
            position={response.offset + index}
            result={result}
            showExplanation={showExplanations}
          />
        ))}
      </div>
      {pageCount > 1 && (
        <nav className="search-pagination" aria-label="Search pagination">
          <button
            aria-label="Previous search page"
            className="button button-quiet"
            disabled={!canGoPrevious || isLoading}
            onClick={() => onPageChange(Math.max(0, response.offset - response.limit))}
            type="button"
          >
            <ChevronLeft size={15} aria-hidden="true" />
            Previous
          </button>
          <span>Page {pageNumber} of {pageCount}</span>
          <button
            aria-label="Next search page"
            className="button button-quiet"
            disabled={!canGoNext || isLoading}
            onClick={() => onPageChange(response.offset + response.limit)}
            type="button"
          >
            Next
            <ChevronRight size={15} aria-hidden="true" />
          </button>
        </nav>
      )}
    </>
  )
}
