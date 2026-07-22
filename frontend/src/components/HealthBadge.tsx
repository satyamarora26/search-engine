import { CircleCheck } from 'lucide-react'

type HealthBadgeProps = {
  label: string
  tone?: 'healthy' | 'pending' | 'failed'
}

export function HealthBadge({ label, tone = 'healthy' }: HealthBadgeProps) {
  return (
    <span className={`health-badge health-badge-${tone}`}>
      <CircleCheck size={14} strokeWidth={2.2} aria-hidden="true" />
      <span>{label}</span>
    </span>
  )
}
