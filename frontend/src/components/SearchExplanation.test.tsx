import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import type { SearchExplainResponse } from '../api/types'
import { SearchExplanation } from './SearchExplanation'

const explanationResponse: SearchExplainResponse = {
  query: 'information retrieval',
  ranking: 'bm25',
  document_id: 7,
  final_score: 1.09,
  terms: [
    { term: 'information', term_frequency: 2, document_frequency: 4, idf: 0.81, contribution: 0.62 },
    { term: 'retrieval', term_frequency: 1, document_frequency: 3, idf: 0.94, contribution: 0.47 },
  ],
}

describe('SearchExplanation', () => {
  it('renders BM25 term contributions', () => {
    render(<SearchExplanation response={explanationResponse} error={null} isLoading={false} onRetry={vi.fn()} />)

    expect(screen.getByText('Score explanation')).toBeVisible()
    expect(screen.getByRole('columnheader', { name: 'Contribution' })).toBeVisible()
    expect(screen.getByText('0.62')).toBeVisible()
  })

  it('renders loading, empty, and retryable error states', () => {
    const onRetry = vi.fn()
    const { rerender } = render(
      <SearchExplanation response={null} error={null} isLoading onRetry={onRetry} />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Loading score explanation')

    rerender(<SearchExplanation response={null} error={null} isLoading={false} onRetry={onRetry} />)
    expect(screen.getByText('No term contributions available.')).toBeVisible()

    rerender(
      <SearchExplanation
        response={null}
        error={new Error('Explanation unavailable.')}
        isLoading={false}
        onRetry={onRetry}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Explanation unavailable.')
    screen.getByRole('button', { name: 'Retry score explanation' }).click()
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
