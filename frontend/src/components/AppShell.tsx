import type { PropsWithChildren } from 'react'

import { Activity } from 'lucide-react'

import { HealthBadge } from './HealthBadge'
import { SideNav } from './SideNav'
import type { AppRoute } from '../state/routes'

type AppShellProps = PropsWithChildren<{
  activeRoute: AppRoute
  onNavigate: (route: AppRoute) => void
}>

export function AppShell({ activeRoute, children, onNavigate }: AppShellProps) {
  return (
    <div className="app-shell">
      <SideNav activeRoute={activeRoute} onNavigate={onNavigate} />
      <div className="app-main">
        <header className="top-bar">
          <div className="top-bar-context">
            <Activity size={16} aria-hidden="true" />
            <span>Search infrastructure</span>
          </div>
          <HealthBadge label="Healthy" />
        </header>
        <main className="page-content">{children}</main>
      </div>
    </div>
  )
}
