import type { PropsWithChildren, ReactNode } from 'react'

type PanelProps = PropsWithChildren<{
  className?: string
  eyebrow?: string
  title?: string
  action?: ReactNode
}>

export function Panel({
  action,
  children,
  className = '',
  eyebrow,
  title,
}: PanelProps) {
  return (
    <section className={`panel ${className}`.trim()}>
      {(eyebrow || title || action) && (
        <header className="panel-header">
          <div>
            {eyebrow && <p className="panel-eyebrow">{eyebrow}</p>}
            {title && <h2 className="panel-title">{title}</h2>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  )
}
