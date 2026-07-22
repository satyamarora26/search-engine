import { useEffect, useState } from 'react'

import { AppShell } from './components/AppShell'
import { navigateTo, routeFromPath, type AppRoute } from './state/routes'

const pageCopy: Record<AppRoute, { eyebrow: string; title: string; copy: string }> = {
  workspace: {
    eyebrow: 'Personal search engine',
    title: 'Find the useful thread.',
    copy: 'Search, inspect, and understand the documents your index knows about.',
  },
  crawls: {
    eyebrow: 'Wikipedia ingestion',
    title: 'Bring new knowledge in.',
    copy: 'Start a bounded crawl and watch every page move through the pipeline.',
  },
  library: {
    eyebrow: 'Document library',
    title: 'Everything your index has kept.',
    copy: 'Browse the searchable corpus and inspect the source behind each result.',
  },
}

function App() {
  const [route, setRoute] = useState(() => routeFromPath(window.location.pathname))

  useEffect(() => {
    const handlePopState = () => setRoute(routeFromPath(window.location.pathname))
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const copy = pageCopy[route]

  return (
    <AppShell
      activeRoute={route}
      onNavigate={(nextRoute) => {
        navigateTo(nextRoute)
        setRoute(nextRoute)
      }}
    >
      <section className="page-intro" aria-labelledby="page-title">
        <p className="page-eyebrow">{copy.eyebrow}</p>
        <h1 id="page-title">{copy.title}</h1>
        <p className="page-copy">{copy.copy}</p>
      </section>
    </AppShell>
  )
}

export default App
