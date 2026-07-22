import { ArrowUpRight, ChevronDown, ChevronUp, CircleHelp } from 'lucide-react'

import type { SearchResult } from '../api/types'
import { SearchExplanation, type SearchExplanationState } from './SearchExplanation'

type SearchResultRowProps = {
  position: number
  result: SearchResult
  explanation?: SearchExplanationState
  isExplanationExpanded?: boolean
  showExplanation?: boolean
  onRetryExplanation?: () => void
  onToggleExplanation?: () => void
}

const EMPTY_EXPLANATION: SearchExplanationState = {
  error: null,
  isLoading: false,
  response: null,
}

function noop() {}

export function SearchResultRow({
  explanation = EMPTY_EXPLANATION,
  isExplanationExpanded = false,
  onRetryExplanation = noop,
  onToggleExplanation = noop,
  position,
  result,
  showExplanation = false,
}: SearchResultRowProps) {
  const explanationId = `result-explanation-${result.document_id}`
  const explanationLabel = explanation.isLoading
    ? 'Loading score explanation'
    : isExplanationExpanded
      ? 'Hide score explanation'
      : 'Explain score'

  return (
    <article className="result-row">
      <div className="result-position" aria-hidden="true">{String(position + 1).padStart(2, '0')}</div>
      <div className="result-body">
        <div className="result-heading">
          <h3>{result.title}</h3>
          <span className="result-score">{result.score.toFixed(2)}</span>
        </div>
        {result.url && (
          <a className="result-source" href={result.url} rel="noreferrer" target="_blank">
            {result.url}
            <ArrowUpRight size={14} aria-hidden="true" />
          </a>
        )}
        <p className="result-snippet">{result.snippet}</p>
        <div className="term-list" aria-label="Matched terms">
          {result.matched_terms.map((term) => <span className="term-chip" key={term}>{term}</span>)}
        </div>
        {showExplanation && (
          <>
            <div className="result-actions">
              <button
                aria-controls={explanationId}
                aria-expanded={isExplanationExpanded}
                className="button button-quiet result-explanation-action"
                disabled={explanation.isLoading}
                type="button"
                onClick={onToggleExplanation}
              >
                {isExplanationExpanded ? <ChevronUp size={14} aria-hidden="true" /> : <CircleHelp size={14} aria-hidden="true" />}
                {explanationLabel}
                {!isExplanationExpanded && <ChevronDown size={14} aria-hidden="true" />}
              </button>
            </div>
            {isExplanationExpanded && (
              <SearchExplanation
                id={explanationId}
                {...explanation}
                onRetry={onRetryExplanation}
              />
            )}
          </>
        )}
      </div>
    </article>
  )
}
