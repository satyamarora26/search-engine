import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  searchDocuments,
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
})
