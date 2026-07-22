import { Globe2, Library, Search } from 'lucide-react'

import { pathForRoute, type AppRoute } from '../state/routes'

type SideNavProps = {
  activeRoute: AppRoute
  onNavigate: (route: AppRoute) => void
}

const navigation = [
  { route: 'workspace' as const, label: 'Workspace', icon: Search },
  { route: 'crawls' as const, label: 'Crawls', icon: Globe2 },
  { route: 'library' as const, label: 'Library', icon: Library },
]

export function SideNav({ activeRoute, onNavigate }: SideNavProps) {
  return (
    <nav className="side-nav" aria-label="Primary navigation">
      <div className="brand-lockup">
        <span className="brand-mark" aria-hidden="true">i</span>
        <span>
          <strong>Index</strong>
          <small>personal search</small>
        </span>
      </div>

      <div className="nav-links">
        {navigation.map(({ icon: Icon, label, route }) => (
          <a
            aria-current={activeRoute === route ? 'page' : undefined}
            className={`nav-link ${activeRoute === route ? 'nav-link-active' : ''}`}
            href={pathForRoute(route)}
            key={route}
            onClick={(event) => {
              event.preventDefault()
              onNavigate(route)
            }}
          >
            <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
            <span>{label}</span>
          </a>
        ))}
      </div>

      <div className="nav-footer">
        <span className="nav-footer-dot" aria-hidden="true" />
        <span>Index is ready</span>
      </div>
    </nav>
  )
}
