import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ApiError, getDocument, listDocuments } from '../api/client'
import type { Document, DocumentListResponse } from '../api/types'
import '../styles/global.css'
import { LibraryPage } from './LibraryPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getDocument: vi.fn(),
    listDocuments: vi.fn(),
  }
})

const firstDocument: Document = {
  id: 81,
  title: 'Information retrieval',
  url: 'https://en.wikipedia.org/wiki/Information_retrieval',
  content: 'Information retrieval is the process of finding useful information in a collection of resources.',
  status: 'active',
  created_at: '2026-07-22T00:00:00Z',
  updated_at: '2026-07-22T00:00:00Z',
}

const secondDocument: Document = {
  ...firstDocument,
  id: 82,
  title: 'Search ranking',
  url: 'https://example.com/search-ranking',
  content: 'Search ranking orders documents by their relevance to a query.',
}

function response(documents: Document[]): DocumentListResponse {
  return {
    total_results: documents.length,
    limit: 20,
    offset: 0,
    documents,
  }
}

function documentPage(count: number, offset = 0): DocumentListResponse {
  return {
    total_results: count,
    limit: 20,
    offset,
    documents: Array.from({ length: count }, (_, index) => ({
      ...firstDocument,
      id: offset + index + 1,
      title: `Document ${offset + index + 1}`,
    })),
  }
}

describe('LibraryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads documents and selects a readable detail preview', async () => {
    vi.mocked(listDocuments).mockResolvedValue(response([firstDocument, secondDocument]))
    vi.mocked(getDocument).mockResolvedValue(firstDocument)
    const user = userEvent.setup()
    render(<LibraryPage />)

    expect(screen.getByText('Loading documents...')).toBeVisible()
    expect(await screen.findByText('Information retrieval')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /Information retrieval/ }))

    expect(await screen.findByRole('heading', { name: 'Information retrieval' })).toBeVisible()
    expect(screen.getByText(firstDocument.content)).toBeVisible()
    expect(screen.getByRole('link', { name: /Open source/ })).toHaveAttribute('href', firstDocument.url)
    expect(getDocument).toHaveBeenCalledWith(81)
  })

  it('renders an explicit empty state', async () => {
    vi.mocked(listDocuments).mockResolvedValue(response([]))
    render(<LibraryPage />)

    expect(await screen.findByText('No documents in the index yet.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  })

  it('moves between pages and disables next at the final short page', async () => {
    vi.mocked(listDocuments)
      .mockResolvedValueOnce(documentPage(20))
      .mockResolvedValueOnce(documentPage(2, 20))
    const user = userEvent.setup()
    render(<LibraryPage />)

    expect(await screen.findByText('Document 1')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next page' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Next page' }))

    expect(await screen.findByText('Document 21')).toBeVisible()
    expect(listDocuments).toHaveBeenLastCalledWith(20, 20)
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeEnabled()
  })

  it('preserves the selected row and offers retry when detail loading fails', async () => {
    vi.mocked(listDocuments).mockResolvedValue(response([firstDocument]))
    vi.mocked(getDocument).mockRejectedValue(new ApiError(404, 'Document 81 was not found.'))
    const user = userEvent.setup()
    render(<LibraryPage />)

    await user.click(await screen.findByRole('button', { name: /Information retrieval/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Document 81 was not found.')
    expect(screen.getByRole('button', { name: /Information retrieval/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Retry document' })).toBeVisible()
  })

  it('shows a service error without losing the document list', async () => {
    vi.mocked(listDocuments).mockResolvedValue(response([firstDocument]))
    vi.mocked(getDocument).mockRejectedValue(new ApiError(503, 'Document service unavailable.'))
    const user = userEvent.setup()
    render(<LibraryPage />)

    await user.click(await screen.findByRole('button', { name: /Information retrieval/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Document service unavailable.')
    expect(screen.getByText('Information retrieval')).toBeVisible()
  })

  it('keeps long titles and URLs inside a constrained list row', async () => {
    const longTitle = 'A very long document title that should wrap instead of pushing the library layout beyond the viewport width'
    const longUrl = `https://example.com/${'long-path-segment-'.repeat(16)}`
    vi.mocked(listDocuments).mockResolvedValue(response([{ ...firstDocument, title: longTitle, url: longUrl }]))
    render(<LibraryPage />)

    const row = await screen.findByRole('button', { name: new RegExp(longTitle) })
    expect(row).toHaveClass('document-list-row')
    expect(getComputedStyle(row).minWidth).toBe('0px')
    expect(getComputedStyle(row).overflowWrap).toBe('anywhere')
    expect(screen.getByText(longUrl)).toBeVisible()
  })

  it('shows loading state while a selected document is being fetched', async () => {
    let resolveDetail: (document: Document) => void = () => undefined
    vi.mocked(listDocuments).mockResolvedValue(response([firstDocument]))
    vi.mocked(getDocument).mockReturnValue(new Promise((resolve) => { resolveDetail = resolve }))
    const user = userEvent.setup()
    render(<LibraryPage />)

    await user.click(await screen.findByRole('button', { name: /Information retrieval/ }))
    expect(screen.getByText('Loading document...')).toBeVisible()

    await act(async () => resolveDetail(firstDocument))
    expect(await screen.findByText(firstDocument.content)).toBeVisible()
  })
})
