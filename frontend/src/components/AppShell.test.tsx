import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { getHealth } from '../api/client'
import { AppShell } from './AppShell'

vi.mock('../api/client', () => ({
  getHealth: vi.fn(),
}))

const mockedGetHealth = vi.mocked(getHealth)

const healthyResponse = {
  status: 'healthy' as const,
  checks: {
    api: { status: 'healthy' as const, detail: null },
    database: { status: 'healthy' as const, detail: null },
    redis: { status: 'healthy' as const, detail: null },
    search_index: {
      status: 'healthy' as const,
      detail: null,
      index_version: 'redis-v4',
      document_count: 12,
    },
  },
}

describe('AppShell', () => {
  beforeEach(() => {
    mockedGetHealth.mockResolvedValue(healthyResponse)
  })

  it('renders the active navigation route and main landmark', () => {
    render(
      <AppShell activeRoute="workspace" onNavigate={vi.fn()}>
        <h1>Workspace</h1>
      </AppShell>,
    )

    expect(screen.getByRole('main')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Workspace' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('navigates from the rail using an accessible link', async () => {
    const user = userEvent.setup()
    const onNavigate = vi.fn()
    render(
      <AppShell activeRoute="workspace" onNavigate={onNavigate}>
        <h1>Workspace</h1>
      </AppShell>,
    )

    await user.click(screen.getByRole('link', { name: 'Crawls' }))

    expect(onNavigate).toHaveBeenCalledWith('crawls')
  })

  it('reflects a degraded service state in the health badge', async () => {
    mockedGetHealth.mockResolvedValueOnce({
      ...healthyResponse,
      status: 'degraded',
    })

    render(
      <AppShell activeRoute="workspace" onNavigate={vi.fn()}>
        <h1>Workspace</h1>
      </AppShell>,
    )

    expect(await screen.findByText('Degraded')).toBeVisible()
  })
})
