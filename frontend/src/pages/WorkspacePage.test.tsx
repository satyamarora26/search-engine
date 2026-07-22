import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { JobStatusResponse, SearchResponse } from '../api/types'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getJobStatus: vi.fn(),
    searchDocuments: vi.fn(),
  }
})

import { getJobStatus, searchDocuments } from '../api/client'
import { WorkspacePage } from './WorkspacePage'

const resultResponse: SearchResponse = {
  query: 'information retrieval',
  ranking: 'bm25',
  total_results: 1,
  index_version: 'redis-test',
  limit: 10,
  offset: 0,
  scope: 'all',
  exact_phrase: false,
  results: [{
    document_id: 7,
    title: 'Information retrieval',
    url: 'https://example.com/ir',
    score: 1.09,
    snippet: 'A concise explanation of indexing and ranking.',
    matched_terms: ['information', 'retrieval'],
  }],
}

function job(status: JobStatusResponse['status']): JobStatusResponse {
  return {
    job_id: 'job-123',
    job_type: 'wikipedia_crawl',
    status,
    ready: status === 'SUCCESS' || status === 'FAILURE',
    successful: status === 'SUCCESS',
    progress: {
      current: status === 'SUCCESS' ? 4 : 1,
      total: 4,
      percentage: status === 'SUCCESS' ? 100 : 25,
      message: status === 'SUCCESS' ? 'Wikipedia crawl completed' : 'Fetching articles',
    },
    result: null,
    error: null,
    created_at: '2026-07-22T00:00:00Z',
    started_at: '2026-07-22T00:00:00Z',
    finished_at: null,
  }
}

describe('WorkspacePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
  })

  it('submits a BM25 search and renders the returned result', async () => {
    vi.mocked(searchDocuments).mockResolvedValue(resultResponse)
    const user = userEvent.setup()
    render(<WorkspacePage />)

    await user.type(screen.getByLabelText('Search documents'), 'information retrieval')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('Information retrieval')).toBeVisible()
    expect(searchDocuments).toHaveBeenCalledWith(
      'information retrieval',
      'bm25',
      10,
      { offset: 0, scope: 'all', exact_phrase: false },
    )
  })

  it('switches to TF-IDF in the request', async () => {
    vi.mocked(searchDocuments).mockResolvedValue({ ...resultResponse, ranking: 'tfidf' })
    const user = userEvent.setup()
    render(<WorkspacePage />)

    await user.type(screen.getByLabelText('Search documents'), 'ranking')
    await user.selectOptions(screen.getByLabelText('Ranking'), 'tfidf')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(searchDocuments).toHaveBeenCalledWith(
      'ranking',
      'tfidf',
      10,
      { offset: 0, scope: 'all', exact_phrase: false },
    )
  })

  it('submits scope and exact-phrase search options', async () => {
    vi.mocked(searchDocuments).mockResolvedValue(resultResponse)
    const user = userEvent.setup()
    render(<WorkspacePage />)

    await user.type(screen.getByLabelText('Search documents'), 'information retrieval')
    await user.selectOptions(screen.getByLabelText('Search scope'), 'content')
    await user.click(screen.getByLabelText('Exact phrase'))
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(searchDocuments).toHaveBeenCalledWith(
      'information retrieval',
      'bm25',
      10,
      { offset: 0, scope: 'content', exact_phrase: true },
    )
  })

  it('paginates results while preserving advanced search options', async () => {
    const firstPage = {
      ...resultResponse,
      total_results: 21,
      limit: 10,
      offset: 0,
    }
    const secondPage = {
      ...firstPage,
      offset: 10,
      results: [{ ...resultResponse.results[0], document_id: 8 }],
    }
    vi.mocked(searchDocuments)
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(secondPage)
    const user = userEvent.setup()
    render(<WorkspacePage />)

    await user.type(screen.getByLabelText('Search documents'), 'ranking')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('21 results')
    await user.click(screen.getByRole('button', { name: 'Next search page' }))

    expect(await screen.findByText('Page 2 of 3')).toBeVisible()
    expect(searchDocuments).toHaveBeenLastCalledWith(
      'ranking',
      'bm25',
      10,
      { offset: 10, scope: 'all', exact_phrase: false },
    )
  })

  it('shows a retryable service error', async () => {
    vi.mocked(searchDocuments).mockRejectedValue(new Error('Search service unavailable.'))
    const user = userEvent.setup()
    render(<WorkspacePage />)

    await user.type(screen.getByLabelText('Search documents'), 'ranking')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Search service unavailable.')
    expect(screen.getByRole('button', { name: 'Retry search' })).toBeVisible()
  })

  it('polls the remembered crawl job until it reaches a terminal state', async () => {
    window.localStorage.setItem('search-engine:last-crawl-job', 'job-123')
    vi.mocked(getJobStatus)
      .mockResolvedValueOnce(job('STARTED'))
      .mockResolvedValueOnce(job('SUCCESS'))
    render(<WorkspacePage />)

    await waitFor(() => expect(getJobStatus).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('Wikipedia crawl completed', {}, { timeout: 3000 })).toBeVisible()
    expect(getJobStatus).toHaveBeenCalledTimes(2)
  })
})
