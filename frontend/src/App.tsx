import { useEffect, useState } from 'react'

import { AppShell } from './components/AppShell'
import { CrawlsPage } from './pages/CrawlsPage'
import { LibraryPage } from './pages/LibraryPage'
import { WorkspacePage } from './pages/WorkspacePage'
import { navigateTo, routeFromPath } from './state/routes'

function App() {
  const [route, setRoute] = useState(() => routeFromPath(window.location.pathname))

  useEffect(() => {
    const handlePopState = () => setRoute(routeFromPath(window.location.pathname))
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  return (
    <AppShell
      activeRoute={route}
      onNavigate={(nextRoute) => {
        navigateTo(nextRoute)
        setRoute(nextRoute)
      }}
    >
      {route === 'workspace' ? <WorkspacePage /> : route === 'crawls' ? <CrawlsPage /> : <LibraryPage />}
    </AppShell>
  )
}

export default App
