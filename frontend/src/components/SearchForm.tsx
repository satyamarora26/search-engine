import { Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import type { SearchRanking } from '../api/types'

type SearchFormProps = {
  initialQuery?: string
  initialRanking?: SearchRanking
  isLoading: boolean
  onSubmit: (query: string, ranking: SearchRanking) => void
}

export function SearchForm({
  initialQuery = '',
  initialRanking = 'bm25',
  isLoading,
  onSubmit,
}: SearchFormProps) {
  const [query, setQuery] = useState(initialQuery)
  const [ranking, setRanking] = useState<SearchRanking>(initialRanking)
  const [validationError, setValidationError] = useState<string | null>(null)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuery = query.trim()
    if (!trimmedQuery) {
      setValidationError('Enter a search term to continue.')
      return
    }
    setValidationError(null)
    onSubmit(trimmedQuery, ranking)
  }

  return (
    <form className="search-form" onSubmit={handleSubmit}>
      <label className="search-field-label" htmlFor="search-documents">Search documents</label>
      <div className="search-input-wrap">
        <Search size={20} aria-hidden="true" />
        <input
          id="search-documents"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search your documents..."
          type="search"
          value={query}
        />
        <span className="search-shortcut" aria-hidden="true">⌘K</span>
      </div>
      <div className="search-form-actions">
        <label className="select-wrap" htmlFor="search-ranking">
          <span>Ranking</span>
          <select
            id="search-ranking"
            onChange={(event) => setRanking(event.target.value as SearchRanking)}
            value={ranking}
          >
            <option value="bm25">BM25 ranking</option>
            <option value="tfidf">TF-IDF ranking</option>
          </select>
        </label>
        <button className="button button-primary" disabled={isLoading} type="submit">
          <Search size={16} aria-hidden="true" />
          <span>{isLoading ? 'Searching...' : 'Search'}</span>
        </button>
      </div>
      {validationError && <p className="field-error" role="alert">{validationError}</p>}
    </form>
  )
}
