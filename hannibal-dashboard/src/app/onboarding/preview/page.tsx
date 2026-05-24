'use client'

import React from 'react'
import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard'

// Public, auth-free demo of the onboarding flow. It renders the exact same
// OnboardingWizard as the real /onboarding route — the only difference is that
// no submit handlers are passed, so steps just navigate without hitting the API.
export default function OnboardingPreviewPage() {
  return (
    <OnboardingWizard
      showPreviewBanner
      onFinish={() => alert('Preview — en producción redirige al dashboard')}
    />
  )
}
