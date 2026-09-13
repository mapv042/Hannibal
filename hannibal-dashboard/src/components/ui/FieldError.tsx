import React from 'react'

/**
 * Inline error for fields that aren't an `<Input>` — choice cards, checklists,
 * the schedule grid. `Input` renders its own `error` prop; this keeps the
 * wording and colour identical for everything else.
 */
export function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <p className="mt-1.5 text-[13px] text-error">{message}</p>
}
