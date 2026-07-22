import { Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import type { SearchRanking, SearchScope } from '../api/types'

type SearchFormProps = {
  initialQuery?: string
  initialRanking?: SearchRanking
  initialScope?: SearchScope
  initialExactPhrase?: boolean
  isLoading: boolean
  onSubmit: (
    query: string,
    ranking: SearchRanking,
    scope: SearchScope,
    exactPhrase: boolean,
  ) => void
}

export function SearchForm({
  initialQuery = '',
  initialRanking = 'bm25',
  initialScope = 'all',
  initialExactPhrase = false,
  isLoading,
  onSubmit,
}: SearchFormProps) {
  const [query, setQuery] = useState(initialQuery)
  const [ranking, setRanking] = useState<SearchRanking>(initialRanking)
  const [scope, setScope] = useState<SearchScope>(initialScope)
  const [exactPhrase, setExactPhrase] = useState(initialExactPhrase)
  const [validationError, setValidationError] = useState<string | null>(null)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuery = query.trim()
    if (!trimmedQuery) {
      setValidationError('Enter a search term to continue.')
      return
    }
    setValidationError(null)
    onSubmit(trimmedQuery, ranking, scope, exactPhrase)
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
        <div className="search-form-options">
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
          <label className="select-wrap" htmlFor="search-scope">
            <span>Search scope</span>
            <select
              id="search-scope"
              onChange={(event) => setScope(event.target.value as SearchScope)}
              value={scope}
            >
              <option value="all">Title and content</option>
              <option value="title">Title only</option>
              <option value="content">Content only</option>
            </select>
          </label>
          <label className="checkbox-wrap" htmlFor="exact-phrase">
            <input
              checked={exactPhrase}
              id="exact-phrase"
              onChange={(event) => setExactPhrase(event.target.checked)}
              type="checkbox"
            />
            <span>Exact phrase</span>
          </label>
        </div>
        <button className="button button-primary" disabled={isLoading} type="submit">
          <Search size={16} aria-hidden="true" />
          <span>{isLoading ? 'Searching...' : 'Search'}</span>
        </button>
      </div>
      {validationError && <p className="field-error" role="alert">{validationError}</p>}
    </form>
  )
}
