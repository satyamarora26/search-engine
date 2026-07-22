export type AppRoute = 'workspace' | 'crawls' | 'library'

export function routeFromPath(pathname: string): AppRoute {
  if (pathname === '/crawls') return 'crawls'
  if (pathname === '/library') return 'library'
  return 'workspace'
}

export function pathForRoute(route: AppRoute): string {
  if (route === 'crawls') return '/crawls'
  if (route === 'library') return '/library'
  return '/'
}

export function navigateTo(route: AppRoute): void {
  window.history.pushState({}, '', pathForRoute(route))
  window.dispatchEvent(new PopStateEvent('popstate'))
}
