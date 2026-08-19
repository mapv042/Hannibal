'use client'

import React, { useEffect, useRef, useState } from 'react'

interface FadeUpProps {
  children: React.ReactNode
  className?: string
  /** Seconds to hold before the reveal starts, for staggering siblings. */
  delay?: number
  as?: 'div' | 'section'
}

/**
 * Reveals its children once they enter the viewport.
 *
 * Everything above the fold renders visible from the first paint — a landing
 * page that starts blank while JS boots reads as broken, and the whole point of
 * the reveal is to reward scrolling, not to gate the content on it. Anyone with
 * reduced motion set skips the animation entirely.
 */
export const FadeUp: React.FC<FadeUpProps> = ({
  children,
  className = '',
  delay = 0,
  as: Tag = 'div',
}) => {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setVisible(true)
      return
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setVisible(true)
            observer.disconnect()
          }
        })
      },
      { threshold: 0.15 }
    )

    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <Tag
      ref={ref as React.Ref<HTMLDivElement & HTMLElement>}
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(20px)',
        transition: `opacity .6s ease ${delay}s, transform .6s ease ${delay}s`,
      }}
    >
      {children}
    </Tag>
  )
}

FadeUp.displayName = 'FadeUp'
