import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { getJobStatus, listDocuments, submitWikipediaCrawl } from './api/client'
import type { JobStatusResponse } from './api/types'
import App from './App'

vi.mock('./api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api/client')>()
  return {
    ...actual,
    getJobStatus: vi.fn(),
    listDocuments: vi.fn(),
    submitWikipediaCrawl: vi.fn(),
  }
})

const crawlJob: JobStatusResponse = {
  job_id: 'job-123',
  job_type: 'wikipedia_crawl',
  status: 'STARTED',
  ready: false,
  successful: false,
  progress: {
    current: 1,
    total: 4,
    percentage: 25,
    message: 'Fetching articles',
  },
  result: null,
  error: null,
  created_at: '2026-07-22T00:00:00Z',
  started_at: '2026-07-22T00:00:00Z',
  finished_at: null,
}

describe('App journey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    window.history.replaceState({}, '', '/')
    vi.mocked(getJobStatus).mockResolvedValue(crawlJob)
    vi.mocked(listDocuments).mockResolvedValue({
      total_results: 0,
      limit: 20,
      offset: 0,
      documents: [],
    })
  })

  it('navigates across the product and remembers a submitted crawl', async () => {
    vi.mocked(submitWikipediaCrawl).mockResolvedValue({
      job_id: 'job-123',
      status: 'PENDING',
      status_url: '/api/v1/jobs/job-123',
    })
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('heading', { name: 'Find the useful thread.' })).toBeVisible()
    await user.click(screen.getByRole('link', { name: 'Crawls' }))
    expect(screen.getByRole('heading', { name: 'Bring new knowledge in.' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Start crawl' }))
    expect(await screen.findByText('Crawl accepted')).toBeVisible()

    await user.click(screen.getByRole('link', { name: 'Library' }))
    expect(await screen.findByRole('heading', { name: 'Everything your index has kept.' })).toBeVisible()
    expect(await screen.findByText('No documents in the index yet.')).toBeVisible()

    await user.click(screen.getByRole('link', { name: 'Workspace' }))
    expect(await screen.findByText('Fetching articles')).toBeVisible()
    expect(getJobStatus).toHaveBeenCalledWith('job-123')
  })
})
