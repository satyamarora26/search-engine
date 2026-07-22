import { AlertCircle, LoaderCircle, RotateCcw } from 'lucide-react'

import type { SearchExplainResponse } from '../api/types'

export type SearchExplanationState = {
  error: Error | null
  isLoading: boolean
  response: SearchExplainResponse | null
}

type SearchExplanationProps = SearchExplanationState & {
  id?: string
  onRetry: () => void
}

function formatScore(value: number): string {
  return value.toFixed(2)
}

export function SearchExplanation({
  error,
  id,
  isLoading,
  onRetry,
  response,
}: SearchExplanationProps) {
  if (isLoading) {
    return (
      <div className="result-explanation explanation-state" id={id} role="status">
        <LoaderCircle className="spin" size={16} aria-hidden="true" />
        <span>Loading score explanation...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="result-explanation explanation-state explanation-error" id={id} role="alert">
        <AlertCircle size={16} aria-hidden="true" />
        <span>{error.message}</span>
        <button className="button button-quiet" type="button" onClick={onRetry}>
          <RotateCcw size={14} aria-hidden="true" />
          Retry score explanation
        </button>
      </div>
    )
  }

  if (!response) {
    return (
      <div className="result-explanation explanation-state" id={id}>
        <span>No term contributions available.</span>
      </div>
    )
  }

  return (
    <section className="result-explanation" id={id} aria-labelledby={`${id}-title`}>
      <div className="explanation-summary">
        <div>
          <p className="explanation-eyebrow">BM25 ranking</p>
          <h4 id={`${id}-title`}>Score explanation</h4>
        </div>
        <div className="explanation-final-score">
          <span>Final score</span>
          <strong>{formatScore(response.final_score)}</strong>
        </div>
      </div>
      {response.terms.length > 0 ? (
        <div className="explanation-table-wrap">
          <table className="explanation-table">
            <caption className="sr-only">BM25 term contribution breakdown</caption>
            <thead>
              <tr>
                <th scope="col">Term</th>
                <th scope="col">TF</th>
                <th scope="col">DF</th>
                <th scope="col">IDF</th>
                <th scope="col">Contribution</th>
              </tr>
            </thead>
            <tbody>
              {response.terms.map((term) => (
                <tr key={term.term}>
                  <th scope="row">{term.term}</th>
                  <td>{term.term_frequency}</td>
                  <td>{term.document_frequency}</td>
                  <td>{formatScore(term.idf)}</td>
                  <td>{formatScore(term.contribution)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="explanation-empty">No term contributions available.</p>
      )}
    </section>
  )
}
