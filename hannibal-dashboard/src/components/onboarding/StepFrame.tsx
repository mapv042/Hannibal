import React from 'react'
import { Card, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { StepHeader } from '@/components/onboarding/StepHeader'
import { Save } from 'lucide-react'

/**
 * Where a step renders. The same fields serve the onboarding wizard and, after
 * it, the Settings page: the doctor edits their office with exactly the form
 * they filled in, instead of a second, drifting copy of it.
 */
export type StepVariant = 'wizard' | 'settings'

interface StepFrameProps {
  variant: StepVariant
  eyebrow: string
  title: string
  subtitle: string
  onNext: () => void
  onBack: () => void
  loading?: boolean
  /** Card body spacing in the wizard (steps differ slightly). */
  bodyClassName?: string
  children: React.ReactNode
}

export const StepFrame: React.FC<StepFrameProps> = ({
  variant,
  eyebrow,
  title,
  subtitle,
  onNext,
  onBack,
  loading,
  bodyClassName = 'space-y-5 p-8',
  children,
}) => {
  if (variant === 'settings') {
    // Settings supplies its own card and section title; the step is just the
    // fields plus a save button (no "Paso N", no back/next).
    return (
      <div className="space-y-5">
        {children}
        <Button onClick={onNext} isLoading={loading} className="gap-2">
          <Save size={16} />
          Guardar cambios
        </Button>
      </div>
    )
  }

  return (
    <Card>
      <CardBody className={bodyClassName}>
        <StepHeader eyebrow={eyebrow} title={title} subtitle={subtitle} />
        {children}
        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={onBack}>
            Atrás
          </Button>
          <Button onClick={onNext} isLoading={loading} className="flex-1">
            Continuar
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

StepFrame.displayName = 'StepFrame'
