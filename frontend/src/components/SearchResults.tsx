import type { SearchResponse } from '../api/types'

import { SearchResultRow } from './SearchResultRow'

type SearchResultsProps = {
  hasSubmitted: boolean
  isLoading: boolean
  response: SearchResponse | null
}

export function SearchResults({ hasSubmitted, isLoading, response }: SearchResultsProps) {
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

  return (
    <div className="results-list" aria-live="polite">
      {response.results.map((result, index) => (
        <SearchResultRow key={result.document_id} position={index} result={result} />
      ))}
    </div>
  )
}
