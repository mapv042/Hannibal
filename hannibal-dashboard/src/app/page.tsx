import React from 'react'
import { LandingNav } from '@/components/landing/LandingNav'
import { Hero } from '@/components/landing/Hero'
import { Statement } from '@/components/landing/Statement'
import { DemoSection } from '@/components/landing/DemoSection'
import { Steps } from '@/components/landing/Steps'
import { Pricing } from '@/components/landing/Pricing'
import { Security } from '@/components/landing/Security'
import { LandingFooter } from '@/components/landing/LandingFooter'

export const dynamic = 'force-dynamic'

/**
 * The page argues in one order: what it is (hero), why it exists (statement),
 * proof (demo), how it starts (steps), what it costs (price), why it's safe
 * (security). Price comes after the demo because nobody weighs a number before
 * they believe the thing works.
 */
export default function LandingPage() {
  return (
    <div className="bg-white min-h-screen">
      <LandingNav />
      <Hero />
      <Statement />
      <DemoSection />
      <Steps />
      <Pricing />
      <Security />
      <LandingFooter />
    </div>
  )
}
