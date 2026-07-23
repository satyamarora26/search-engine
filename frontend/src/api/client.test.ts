import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getHealth,
  searchDocuments,
  listMediumCrawlItems,
  listRssCrawlItems,
  submitMediumCrawl,
  submitRssCrawl,
  submitWikipediaCrawl,
} from './client'

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('API client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('requests BM25 search with encoded query parameters', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        query: 'information retrieval',
        ranking: 'bm25',
        total_results: 0,
        index_version: 'redis-test',
        limit: 10,
        offset: 0,
        scope: 'all',
        exact_phrase: false,
        results: [],
      }),
    )

    await searchDocuments('information retrieval', 'bm25')

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/search?q=information+retrieval&ranking=bm25&limit=10',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )
  })

  it('preserves a conflict response as ApiError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ detail: 'An active index job already exists.' }, 409),
    )

    await expect(
      submitWikipediaCrawl({
        category: 'Featured articles',
        max_articles: 4,
        max_depth: 0,
      }),
    ).rejects.toMatchObject({
      status: 409,
      message: 'An active index job already exists.',
    })
  })

  it('submits a Medium crawl and requests its generic item outcomes', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({
        job_id: 'medium-job',
        status: 'PENDING',
        status_url: '/api/v1/jobs/medium-job',
      }))
      .mockResolvedValueOnce(response({
        job_id: 'medium-job',
        total_results: 1,
        limit: 25,
        offset: 5,
        items: [],
      }))

    await submitMediumCrawl({
      publication_url: 'https://medium.com/towards-data-science',
      max_articles: 25,
      max_depth: 0,
    })
    await listMediumCrawlItems('medium/job', 25, 5)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/crawls/medium',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          publication_url: 'https://medium.com/towards-data-science',
          max_articles: 25,
          max_depth: 0,
        }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/crawls/medium/medium%2Fjob/items?limit=25&offset=5',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )
  })

  it('submits an RSS crawl and requests its generic item outcomes', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({
        job_id: 'rss-job',
        status: 'PENDING',
        status_url: '/api/v1/jobs/rss-job',
      }))
      .mockResolvedValueOnce(response({
        job_id: 'rss-job',
        total_results: 1,
        limit: 25,
        offset: 5,
        items: [],
      }))

    await submitRssCrawl({
      feed_url: 'https://example.com/feed.xml',
      max_articles: 25,
      max_depth: 0,
    })
    await listRssCrawlItems('rss/job', 25, 5)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/crawls/rss',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          feed_url: 'https://example.com/feed.xml',
          max_articles: 25,
          max_depth: 0,
        }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/crawls/rss/rss%2Fjob/items?limit=25&offset=5',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )
  })

  it('requests the current service health status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        status: 'healthy',
        checks: {
          api: { status: 'healthy', detail: null },
          database: { status: 'healthy', detail: null },
          redis: { status: 'healthy', detail: null },
          search_index: {
            status: 'healthy',
            detail: null,
            index_version: 'redis-v4',
            document_count: 12,
          },
        },
      }),
    )

    await getHealth()

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/health',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )
  })

  it('encodes advanced search options when provided', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        query: 'python search',
        ranking: 'bm25',
        total_results: 1,
        index_version: 'redis-test',
        limit: 10,
        offset: 10,
        scope: 'content',
        exact_phrase: true,
        results: [],
      }),
    )

    await searchDocuments('python search', 'bm25', 10, {
      offset: 10,
      scope: 'content',
      exact_phrase: true,
    })

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/search?q=python+search&ranking=bm25&limit=10&offset=10&scope=content&exact_phrase=true',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )
  })
})
