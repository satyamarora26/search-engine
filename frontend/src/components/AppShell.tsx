import { useEffect, useState, type PropsWithChildren } from 'react'

import { Activity } from 'lucide-react'

import { getHealth } from '../api/client'
import type { HealthResponse } from '../api/types'
import { HealthBadge } from './HealthBadge'
import { SideNav } from './SideNav'
import type { AppRoute } from '../state/routes'

type AppShellProps = PropsWithChildren<{
  activeRoute: AppRoute
  onNavigate: (route: AppRoute) => void
}>

export function AppShell({ activeRoute, children, onNavigate }: AppShellProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    let active = true

    const refreshHealth = async () => {
      try {
        const nextHealth = await getHealth()
        if (active) {
          setHealth(nextHealth)
        }
      } catch {
        if (active) {
          setHealth({
            status: 'degraded',
            checks: {
              api: {
                status: 'unhealthy',
                detail: 'Health endpoint unavailable.',
              },
            },
          })
        }
      }
    }

    void refreshHealth()
    const interval = window.setInterval(refreshHealth, 10_000)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [])

  const healthTone =
    health === null ? 'pending' : health.status === 'healthy' ? 'healthy' : 'failed'
  const healthLabel =
    health === null
      ? 'Checking...'
      : health.status === 'healthy'
        ? 'Healthy'
        : 'Degraded'

  return (
    <div className="app-shell">
      <SideNav activeRoute={activeRoute} onNavigate={onNavigate} />
      <div className="app-main">
        <header className="top-bar">
          <div className="top-bar-context">
            <Activity size={16} aria-hidden="true" />
            <span>Search infrastructure</span>
          </div>
          <HealthBadge label={healthLabel} tone={healthTone} />
        </header>
        <main className="page-content">{children}</main>
      </div>
    </div>
  )
}
