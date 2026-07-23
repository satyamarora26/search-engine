import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  ApiError,
  getJobStatus,
  listMediumCrawlItems,
  listRssCrawlItems,
  listWikipediaCrawlItems,
  submitMediumCrawl,
  submitRssCrawl,
  submitWikipediaCrawl,
} from '../api/client'
import type {
  AcceptedJob,
  CrawlItemListResponse,
  JobStatusResponse,
  WikipediaCrawlItemListResponse,
} from '../api/types'
import { CrawlsPage } from './CrawlsPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getJobStatus: vi.fn(),
    listMediumCrawlItems: vi.fn(),
    listRssCrawlItems: vi.fn(),
    listWikipediaCrawlItems: vi.fn(),
    submitMediumCrawl: vi.fn(),
    submitRssCrawl: vi.fn(),
    submitWikipediaCrawl: vi.fn(),
  }
})

const acceptedJob: AcceptedJob = {
  job_id: 'job-123',
  status: 'PENDING',
  status_url: '/api/v1/jobs/job-123',
}

const crawlResult = {
  discovered_count: 4,
  fetched_count: 3,
  imported_count: 2,
  duplicate_skipped_count: 1,
  fetch_failed_count: 1,
  ingestion_failed_count: 0,
  failed_count: 1,
}

const terminalJob: JobStatusResponse = {
  job_id: 'job-123',
  job_type: 'wikipedia_crawl',
  status: 'SUCCESS',
  ready: true,
  successful: true,
  progress: {
    current: 4,
    total: 4,
    percentage: 100,
    message: 'Wikipedia crawl completed',
  },
  result: crawlResult,
  error: null,
  created_at: '2026-07-22T00:00:00Z',
  started_at: '2026-07-22T00:00:00Z',
  finished_at: '2026-07-22T00:01:00Z',
}

const crawlItems: WikipediaCrawlItemListResponse = {
  job_id: 'job-123',
  total_results: 2,
  limit: 100,
  offset: 0,
  items: [
    {
      position: 0,
      wikipedia_page_id: 42,
      title: 'Information retrieval',
      url: 'https://en.wikipedia.org/wiki/Information_retrieval',
      fetch_status: 'fetched',
      ingestion_status: 'imported',
      document_id: 81,
      error: null,
    },
    {
      position: 1,
      wikipedia_page_id: 43,
      title: 'Missing article',
      url: 'https://en.wikipedia.org/wiki/Missing_article',
      fetch_status: 'failed',
      ingestion_status: null,
      document_id: null,
      error: 'wikipedia_not_found',
    },
  ],
}

const mediumTerminalJob: JobStatusResponse = {
  ...terminalJob,
  job_type: 'medium_crawl',
  progress: {
    ...terminalJob.progress,
    message: 'Medium crawl completed',
  },
}

const mediumItems: CrawlItemListResponse = {
  job_id: 'job-123',
  total_results: 1,
  limit: 100,
  offset: 0,
  items: [
    {
      position: 0,
      source_item_id: 'medium-article-1',
      title: 'Practical Search Ranking',
      url: 'https://medium.com/towards-data-science/practical-search-ranking',
      fetch_status: 'fetched',
      ingestion_status: 'imported',
      document_id: 91,
      error: null,
    },
  ],
}

const rssTerminalJob: JobStatusResponse = {
  ...terminalJob,
  job_type: 'rss_crawl',
  progress: {
    ...terminalJob.progress,
    message: 'RSS crawl completed',
  },
}

const rssItems: CrawlItemListResponse = {
  job_id: 'job-123',
  total_results: 1,
  limit: 100,
  offset: 0,
  items: [
    {
      position: 0,
      source_item_id: 'rss-article-1',
      title: 'A feed article',
      url: 'https://example.com/articles/search',
      fetch_status: 'fetched',
      ingestion_status: 'imported',
      document_id: 92,
      error: null,
    },
  ],
}

function job(status: JobStatusResponse['status']): JobStatusResponse {
  return {
    ...terminalJob,
    status,
    ready: status === 'SUCCESS' || status === 'FAILURE',
    successful: status === 'SUCCESS',
    result: status === 'SUCCESS' ? crawlResult : null,
  }
}

async function flushAsyncWork() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

function countText(value: string) {
  return screen.getByText((_, element) => element?.textContent === value)
}

describe('CrawlsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('validates crawl bounds before submitting', async () => {
    const user = userEvent.setup()
    render(<CrawlsPage />)

    await user.clear(screen.getByLabelText('Category'))
    await user.clear(screen.getByLabelText('Maximum articles'))
    await user.type(screen.getByLabelText('Maximum articles'), '0')
    await user.clear(screen.getByLabelText('Maximum depth'))
    await user.type(screen.getByLabelText('Maximum depth'), '3')
    await user.click(screen.getByRole('button', { name: 'Start crawl' }))

    expect(screen.getByText('Enter a category title.')).toBeVisible()
    expect(screen.getByText('Use a value between 1 and 500.')).toBeVisible()
    expect(screen.getByText('Use a value between 0 and 2.')).toBeVisible()
    expect(submitWikipediaCrawl).not.toHaveBeenCalled()
  })

  it('stores an accepted crawl and shows its active job state', async () => {
    vi.mocked(submitWikipediaCrawl).mockResolvedValue(acceptedJob)
    vi.mocked(getJobStatus).mockResolvedValue(job('STARTED'))
    const user = userEvent.setup()
    render(<CrawlsPage />)

    await user.click(screen.getByRole('button', { name: 'Start crawl' }))

    expect(await screen.findByText('Crawl accepted')).toBeVisible()
    expect(window.localStorage.getItem('search-engine:last-crawl-job')).toBe('job-123')
    expect(submitWikipediaCrawl).toHaveBeenCalledWith({
      category: 'Featured articles',
      max_articles: 100,
      max_depth: 0,
    })
  })

  it('polls to terminal success and renders exact result counts and item outcomes', async () => {
    vi.useFakeTimers()
    vi.mocked(submitWikipediaCrawl).mockResolvedValue(acceptedJob)
    vi.mocked(getJobStatus)
      .mockResolvedValueOnce(job('STARTED'))
      .mockResolvedValueOnce(terminalJob)
    vi.mocked(listWikipediaCrawlItems).mockResolvedValue(crawlItems)
    render(<CrawlsPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Start crawl' }))
    await flushAsyncWork()
    expect(getJobStatus).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    await flushAsyncWork()

    expect(screen.getByText('Wikipedia crawl completed')).toBeVisible()
    expect(countText('4 discovered')).toBeVisible()
    expect(countText('2 imported')).toBeVisible()
    expect(countText('1 skipped')).toBeVisible()
    expect(countText('1 failed')).toBeVisible()
    expect(screen.getByText('Information retrieval')).toBeVisible()
    expect(screen.getByText('wikipedia_not_found')).toBeVisible()
    expect(getJobStatus).toHaveBeenCalledTimes(2)
    expect(listWikipediaCrawlItems).toHaveBeenCalledWith('job-123')
  })

  it('submits and monitors a Medium crawl through the shared item view', async () => {
    vi.mocked(submitMediumCrawl).mockResolvedValue(acceptedJob)
    vi.mocked(getJobStatus).mockResolvedValue(mediumTerminalJob)
    vi.mocked(listMediumCrawlItems).mockResolvedValue(mediumItems)
    render(<CrawlsPage />)

    fireEvent.change(screen.getByLabelText('Crawl source'), { target: { value: 'medium' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start crawl' }))
    await flushAsyncWork()

    expect(submitMediumCrawl).toHaveBeenCalledWith({
      publication_url: 'https://medium.com/towards-data-science',
      max_articles: 100,
      max_depth: 0,
    })
    expect(submitWikipediaCrawl).not.toHaveBeenCalled()
    expect(await screen.findByText('Medium crawl completed')).toBeVisible()
    expect(screen.getByText('Practical Search Ranking')).toBeVisible()
    expect(listMediumCrawlItems).toHaveBeenCalledWith('job-123')
    expect(listWikipediaCrawlItems).not.toHaveBeenCalled()
  })

  it('submits and monitors an RSS crawl through the shared item view', async () => {
    vi.mocked(submitRssCrawl).mockResolvedValue(acceptedJob)
    vi.mocked(getJobStatus).mockResolvedValue(rssTerminalJob)
    vi.mocked(listRssCrawlItems).mockResolvedValue(rssItems)
    render(<CrawlsPage />)

    fireEvent.change(screen.getByLabelText('Crawl source'), { target: { value: 'rss' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start crawl' }))
    await flushAsyncWork()

    expect(submitRssCrawl).toHaveBeenCalledWith({
      feed_url: 'https://feeds.bbci.co.uk/news/rss.xml',
      max_articles: 100,
      max_depth: 0,
    })
    expect(submitWikipediaCrawl).not.toHaveBeenCalled()
    expect(await screen.findByText('RSS crawl completed')).toBeVisible()
    expect(screen.getByText('A feed article')).toBeVisible()
    expect(listRssCrawlItems).toHaveBeenCalledWith('job-123')
    expect(listWikipediaCrawlItems).not.toHaveBeenCalled()
  })

  it('stops polling after terminal failure and shows the safe error', async () => {
    vi.useFakeTimers()
    const failedJob = { ...job('FAILURE'), error: 'Wikipedia crawl failed.' }
    vi.mocked(submitWikipediaCrawl).mockResolvedValue(acceptedJob)
    vi.mocked(getJobStatus).mockResolvedValue(failedJob)
    vi.mocked(listWikipediaCrawlItems).mockResolvedValue({ ...crawlItems, items: [] })
    render(<CrawlsPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Start crawl' }))
    await flushAsyncWork()
    expect(screen.getByText('Wikipedia crawl failed.')).toBeVisible()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })

    expect(getJobStatus).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Submit another crawl' })).toBeVisible()
  })

  it('explains a duplicate crawl with the active job id', async () => {
    vi.mocked(submitWikipediaCrawl).mockRejectedValue(new ApiError(
      409,
      'A crawl is already active.',
      { active_job_id: 'active-456' },
    ))
    const user = userEvent.setup()
    render(<CrawlsPage />)

    await user.click(screen.getByRole('button', { name: 'Start crawl' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('A crawl is already active.')
    expect(screen.getByText('Active job: active-456')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open current crawl' })).toHaveAttribute('href', '/crawls')
  })

  it.each([
    [422, 'The crawl request was rejected.'],
    [503, 'The crawl service is unavailable.'],
  ])('shows a recoverable error for HTTP %s', async (status, message) => {
    vi.mocked(submitWikipediaCrawl).mockRejectedValue(new ApiError(status, message))
    const user = userEvent.setup()
    render(<CrawlsPage />)

    await user.click(screen.getByRole('button', { name: 'Start crawl' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getByRole('button', { name: 'Submit another crawl' })).toBeVisible()
  })
})
