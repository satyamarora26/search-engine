import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { CrawlForm } from './WikipediaCrawlForm'

describe('CrawlForm', () => {
  it('switches to Medium fields and submits the bounded Medium request', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<CrawlForm onSubmit={onSubmit} />)

    await user.selectOptions(screen.getByLabelText('Crawl source'), 'medium')
    await user.clear(screen.getByLabelText('Publication URL'))
    await user.type(
      screen.getByLabelText('Publication URL'),
      'https://medium.com/towards-data-science',
    )
    await user.clear(screen.getByLabelText('Maximum articles'))
    await user.type(screen.getByLabelText('Maximum articles'), '25')
    await user.click(screen.getByRole('button', { name: 'Start crawl' }))

    expect(onSubmit).toHaveBeenCalledWith({
      source: 'medium',
      publication_url: 'https://medium.com/towards-data-science',
      max_articles: 25,
      max_depth: 0,
    })
    expect(screen.getByLabelText('Maximum depth')).toHaveValue(0)
    expect(screen.getByLabelText('Maximum depth')).toBeDisabled()
  })

  it('rejects an invalid Medium URL before submitting', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<CrawlForm onSubmit={onSubmit} />)

    await user.selectOptions(screen.getByLabelText('Crawl source'), 'medium')
    await user.clear(screen.getByLabelText('Publication URL'))
    await user.type(screen.getByLabelText('Publication URL'), 'https://example.com/news')
    await user.click(screen.getByRole('button', { name: 'Start crawl' }))

    expect(screen.getByText('Enter a public Medium publication URL.')).toBeVisible()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
