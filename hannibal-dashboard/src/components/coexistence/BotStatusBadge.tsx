'use client'

import React, { useCallback, useEffect, useState } from 'react'
import { StatusBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useApi, type BotStatus } from '@/lib/api'
import { formatDateSafe } from '@/lib/appointments'
import { Power, Pause } from 'lucide-react'

interface BotStatusBadgeProps {
  officeId: string
  onStatusChange?: (newStatus: BotStatus) => void
}

/**
 * The assistant's live on/off switch. The state comes from the backend's pause
 * key — the same one the doctor's "pausa el bot" sets over WhatsApp — so the
 * sidebar never claims the bot is answering while it is silent, or vice versa.
 */
export const BotStatusBadge: React.FC<BotStatusBadgeProps> = ({
  officeId,
  onStatusChange,
}) => {
  const [status, setStatus] = useState<BotStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const api = useApi()

  const refresh = useCallback(async () => {
    const response = await api.getBotStatus(officeId)
    if (response.success && response.data) setStatus(response.data)
  }, [api, officeId])

  useEffect(() => {
    refresh()
    // The pause expires on its own; re-read so the badge flips back in time.
    const timer = setInterval(refresh, 60_000)
    return () => clearInterval(timer)
  }, [refresh])

  const handleToggleBot = async () => {
    if (!status) return
    try {
      setLoading(true)
      const response =
        status.bot_status === 'active'
          ? await api.pauseBot(officeId)
          : await api.resumeBot(officeId)

      if (response.success && response.data) {
        setStatus(response.data)
        onStatusChange?.(response.data)
      }
    } catch (error) {
      console.error('Error toggling bot:', error)
    } finally {
      setLoading(false)
    }
  }

  const active = status?.bot_status !== 'paused'

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <div
            className={`w-3 h-3 rounded-full ${
              active ? 'bg-green-500 animate-pulse' : 'bg-gray-400'
            }`}
          />
          <StatusBadge estado={active ? 'active' : 'paused'} />
        </div>

        <Button
          size="sm"
          variant="secondary"
          isLoading={loading}
          disabled={!status}
          onClick={handleToggleBot}
          className="gap-2"
        >
          {active ? (
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
      {!active && status?.paused_until && (
        <p className="text-xs text-gray-600">
          Se reactiva a las {formatDateSafe(status.paused_until, 'h:mm a')}
        </p>
      )}
    </div>
  )
}

BotStatusBadge.displayName = 'BotStatusBadge'
