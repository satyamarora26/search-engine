import { Database, Sparkles } from 'lucide-react'
import { useState } from 'react'

import { ApiError, searchDocuments } from '../api/client'
import type { SearchRanking, SearchResponse, SearchScope } from '../api/types'
import { CrawlStatusPanel } from '../components/CrawlStatusPanel'
import { Panel } from '../components/Panel'
import { SearchForm } from '../components/SearchForm'
import { SearchResults } from '../components/SearchResults'

const PAGE_SIZE = 10

export function WorkspacePage() {
  const [response, setResponse] = useState<SearchResponse | null>(null)
  const [query, setQuery] = useState('')
  const [ranking, setRanking] = useState<SearchRanking>('bm25')
  const [scope, setScope] = useState<SearchScope>('all')
  const [exactPhrase, setExactPhrase] = useState(false)
  const [offset, setOffset] = useState(0)
  const [hasSubmitted, setHasSubmitted] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)

  async function runSearch(
    nextQuery: string,
    nextRanking: SearchRanking,
    nextScope: SearchScope = scope,
    nextExactPhrase = exactPhrase,
    nextOffset = 0,
  ) {
    setQuery(nextQuery)
    setRanking(nextRanking)
    setScope(nextScope)
    setExactPhrase(nextExactPhrase)
    setOffset(nextOffset)
    setHasSubmitted(true)
    setIsLoading(true)
    setError(null)
    try {
      setResponse(
        await searchDocuments(nextQuery, nextRanking, PAGE_SIZE, {
          offset: nextOffset,
          scope: nextScope,
          exact_phrase: nextExactPhrase,
        }),
      )
    } catch (requestError) {
      setResponse(null)
      setError(
        requestError instanceof Error
          ? requestError
          : new Error('Search service unavailable.'),
      )
    } finally {
      setIsLoading(false)
    }
  }

  const isServiceError = error instanceof ApiError && error.status >= 500

  return (
    <>
      <section className="page-intro" aria-labelledby="page-title">
        <p className="page-eyebrow">Personal search engine</p>
        <h1 id="page-title">Find the useful thread.</h1>
        <p className="page-copy">Search, inspect, and understand the documents your index knows about.</p>
      </section>

      <div className="workspace-grid">
        <div className="workspace-primary">
          <Panel className="search-panel" eyebrow="Search the index" title="What are you looking for?">
            <SearchForm
              initialExactPhrase={exactPhrase}
              initialQuery={query}
              initialRanking={ranking}
              initialScope={scope}
              isLoading={isLoading}
              onSubmit={runSearch}
            />
            {error && (
              <div className="inline-error search-error" role="alert">
                <strong>{isServiceError ? 'Search service unavailable.' : 'Search could not be completed.'}</strong>
                <span>{error.message}</span>
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => void runSearch(query, ranking, scope, exactPhrase, offset)}
                >
                  Retry search
                </button>
              </div>
            )}
            <SearchResults
              hasSubmitted={hasSubmitted}
              isLoading={isLoading}
              onPageChange={(nextOffset) => {
                if (query) {
                  void runSearch(query, ranking, scope, exactPhrase, nextOffset)
                }
              }}
              response={response}
            />
          </Panel>
        </div>

        <aside className="workspace-secondary" aria-label="Index context">
          <Panel className="context-panel" eyebrow="Active snapshot" title="A clear index is a useful index.">
            <div className="snapshot-stat"><Database size={18} aria-hidden="true" /><div><strong>{response?.index_version ?? 'Waiting for first search'}</strong><span>Current search snapshot</span></div></div>
            <div className="snapshot-stat"><Sparkles size={18} aria-hidden="true" /><div><strong>{response ? response.total_results : '—'}</strong><span>{response ? 'Results in this search' : 'Search results'}</span></div></div>
          </Panel>
          <Panel className="context-panel" eyebrow="Crawler status" title="Knowledge in motion.">
            <CrawlStatusPanel />
          </Panel>
        </aside>
      </div>
    </>
  )
}
