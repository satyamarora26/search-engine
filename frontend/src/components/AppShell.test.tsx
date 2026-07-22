import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AppShell } from './AppShell'

describe('AppShell', () => {
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
})
