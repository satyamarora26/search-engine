import { Database, Sparkles } from 'lucide-react'
import { useRef, useState } from 'react'

import { ApiError, explainSearch, searchDocuments } from '../api/client'
import type { SearchRanking, SearchResponse, SearchScope } from '../api/types'
import { CrawlStatusPanel } from '../components/CrawlStatusPanel'
import { Panel } from '../components/Panel'
import { SearchForm } from '../components/SearchForm'
import type { SearchExplanationState } from '../components/SearchExplanation'
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
  const [explanations, setExplanations] = useState<Record<number, SearchExplanationState>>({})
  const [expandedExplanationId, setExpandedExplanationId] = useState<number | null>(null)
  const explanationContextRef = useRef(0)

  async function runSearch(
    nextQuery: string,
    nextRanking: SearchRanking,
    nextScope: SearchScope = scope,
    nextExactPhrase = exactPhrase,
    nextOffset = 0,
  ) {
    explanationContextRef.current += 1
    setExplanations({})
    setExpandedExplanationId(null)
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

  async function loadExplanation(documentId: number) {
    const context = explanationContextRef.current
    setExplanations((current) => ({
      ...current,
      [documentId]: {
        error: null,
        isLoading: true,
        response: current[documentId]?.response ?? null,
      },
    }))

    try {
      const explanation = await explainSearch(query, documentId)
      if (context !== explanationContextRef.current) return
      setExplanations((current) => ({
        ...current,
        [documentId]: { error: null, isLoading: false, response: explanation },
      }))
    } catch (requestError) {
      if (context !== explanationContextRef.current) return
      setExplanations((current) => ({
        ...current,
        [documentId]: {
          error: requestError instanceof Error
            ? requestError
            : new Error('Explanation could not be loaded.'),
          isLoading: false,
          response: current[documentId]?.response ?? null,
        },
      }))
    }
  }

  function toggleExplanation(documentId: number) {
    if (expandedExplanationId === documentId) {
      setExpandedExplanationId(null)
      return
    }

    setExpandedExplanationId(documentId)
    const state = explanations[documentId]
    if (!state?.response && !state?.isLoading) void loadExplanation(documentId)
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
              explanations={explanations}
              expandedExplanationId={expandedExplanationId}
              hasSubmitted={hasSubmitted}
              isLoading={isLoading}
              onPageChange={(nextOffset) => {
                if (query) {
                  void runSearch(query, ranking, scope, exactPhrase, nextOffset)
                }
              }}
              onRetryExplanation={(documentId) => void loadExplanation(documentId)}
              onToggleExplanation={toggleExplanation}
              response={response}
              showExplanations={ranking === 'bm25'}
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
