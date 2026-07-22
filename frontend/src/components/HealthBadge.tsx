import { CircleAlert, CircleCheck, LoaderCircle } from 'lucide-react'

type HealthBadgeProps = {
  label: string
  tone?: 'healthy' | 'pending' | 'failed'
}

export function HealthBadge({ label, tone = 'healthy' }: HealthBadgeProps) {
  const Icon =
    tone === 'healthy'
      ? CircleCheck
      : tone === 'failed'
        ? CircleAlert
        : LoaderCircle

  return (
    <span className={`health-badge health-badge-${tone}`}>
      <Icon
        className={tone === 'pending' ? 'health-badge-spinner' : undefined}
        size={14}
        strokeWidth={2.2}
        aria-hidden="true"
      />
      <span>{label}</span>
    </span>
  )
}
