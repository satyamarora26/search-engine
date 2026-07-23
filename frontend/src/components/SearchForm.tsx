import { RotateCcw, Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import type { SearchFilters, SearchRanking, SearchScope } from '../api/types'

type SearchFormProps = {
  initialQuery?: string
  initialRanking?: SearchRanking
  initialScope?: SearchScope
  initialExactPhrase?: boolean
  initialFilters?: SearchFilters
  isLoading: boolean
  onSubmit: (
    query: string,
    ranking: SearchRanking,
    scope: SearchScope,
    exactPhrase: boolean,
    filters: SearchFilters,
  ) => void
}

export function SearchForm({
  initialQuery = '',
  initialRanking = 'bm25',
  initialScope = 'all',
  initialExactPhrase = false,
  initialFilters = { source: '', createdFrom: '', createdTo: '' },
  isLoading,
  onSubmit,
}: SearchFormProps) {
  const [query, setQuery] = useState(initialQuery)
  const [ranking, setRanking] = useState<SearchRanking>(initialRanking)
  const [scope, setScope] = useState<SearchScope>(initialScope)
  const [exactPhrase, setExactPhrase] = useState(initialExactPhrase)
  const [source, setSource] = useState(initialFilters.source)
  const [createdFrom, setCreatedFrom] = useState(initialFilters.createdFrom)
  const [createdTo, setCreatedTo] = useState(initialFilters.createdTo)
  const [validationError, setValidationError] = useState<string | null>(null)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuery = query.trim()
    if (!trimmedQuery) {
      setValidationError('Enter a search term to continue.')
      return
    }
    setValidationError(null)
    onSubmit(trimmedQuery, ranking, scope, exactPhrase, {
      source: source.trim(),
      createdFrom,
      createdTo,
    })
  }

  function handleClearFilters() {
    setSource('')
    setCreatedFrom('')
    setCreatedTo('')
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
      <div className="search-filter-grid">
        <label className="search-filter-field" htmlFor="search-source">
          <span>Source or domain</span>
          <input
            id="search-source"
            list="source-suggestions"
            onChange={(event) => setSource(event.target.value)}
            placeholder="wikipedia.org"
            type="text"
            value={source}
          />
          <datalist id="source-suggestions">
            <option value="wikipedia.org" />
          </datalist>
        </label>
        <label className="search-filter-field" htmlFor="created-from">
          <span>Created from</span>
          <input
            id="created-from"
            onChange={(event) => setCreatedFrom(event.target.value)}
            type="date"
            value={createdFrom}
          />
        </label>
        <label className="search-filter-field" htmlFor="created-to">
          <span>Created to</span>
          <input
            id="created-to"
            onChange={(event) => setCreatedTo(event.target.value)}
            type="date"
            value={createdTo}
          />
        </label>
        <div className="search-filter-actions">
          <button className="button button-quiet" onClick={handleClearFilters} type="button">
            <RotateCcw size={15} aria-hidden="true" />
            <span>Clear filters</span>
          </button>
        </div>
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
