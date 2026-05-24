'use client'

import React, { useState } from 'react'
import { StatusBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useApi } from '@/lib/api'
import { Power, Pause } from 'lucide-react'

interface BotStatusBadgeProps {
  officeId: string
  currentStatus: 'active' | 'paused' | 'inactive'
  onStatusChange?: (newStatus: string) => void
}

export const BotStatusBadge: React.FC<BotStatusBadgeProps> = ({
  officeId,
  currentStatus,
  onStatusChange,
}) => {
  const [status, setStatus] = useState(currentStatus)
  const [loading, setLoading] = useState(false)
  const api = useApi()

  const handleToggleBot = async () => {
    try {
      setLoading(true)
      let response

      if (status === 'active') {
        response = await api.pauseBot(officeId)
      } else {
        response = await api.resumeBot(officeId)
      }

      if (response.success && response.data) {
        setStatus(response.data.bot_status as 'active' | 'paused' | 'inactive')
        onStatusChange?.(response.data.bot_status)
      }
    } catch (error) {
      console.error('Error toggling bot:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center gap-4">
      <div className="flex items-center gap-2">
        <div
          className={`w-3 h-3 rounded-full ${
            status === 'active' ? 'bg-green-500 animate-pulse' : 'bg-gray-400'
          }`}
        />
        <StatusBadge estado={status} />
      </div>

      <Button
        size="sm"
        variant="secondary"
        isLoading={loading}
        onClick={handleToggleBot}
        className="gap-2"
      >
        {status === 'active' ? (
          <>
            <Pause size={16} />
            Pausar
          </>
        ) : (
          <>
            <Power size={16} />
            Activar
          </>
        )}
      </Button>
    </div>
  )
}

BotStatusBadge.displayName = 'BotStatusBadge'
