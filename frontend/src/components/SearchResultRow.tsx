import { ArrowUpRight } from 'lucide-react'

import type { SearchResult } from '../api/types'

type SearchResultRowProps = {
  result: SearchResult
  position: number
}

export function SearchResultRow({ result, position }: SearchResultRowProps) {
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
      </div>
    </article>
  )
}
