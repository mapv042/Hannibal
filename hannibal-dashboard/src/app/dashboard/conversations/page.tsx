'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useApi, type ConversationSummary, type InboxMessage } from '@/lib/api'
import { formatDateSafe } from '@/lib/appointments'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { EmptyState } from '@/components/ui/states/EmptyState'
import { ErrorState } from '@/components/ui/states/ErrorState'
import { SkeletonList } from '@/components/ui/states/Skeleton'
import { ArrowLeft, MessageCircle, Search, ChevronRight } from 'lucide-react'

const PAGE_SIZE = 50

const AUTHOR_LABEL: Record<InboxMessage['author'], string> = {
  assistant: 'Asistente',
  doctor: 'Tú (mensaje aprobado)',
  doctor_app: 'Tú, desde tu WhatsApp',
  reminder: 'Recordatorio automático',
  system: 'Mensaje automático',
  patient: '',
}

/** "Lo atiendes tú hasta las 4:30 PM" while the assistant stays out of this thread. */
function TakenOverBadge({ until }: { until: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-50 text-amber-800 border border-amber-200 whitespace-nowrap">
      Lo atiendes tú hasta las {formatDateSafe(until, 'h:mm a')}
    </span>
  )
}

function threadTitle(c: ConversationSummary): string {
  return c.patient_name?.trim() || `+${c.whatsapp_id}`
}

/** "3:45 p. m." today, "lun 3:45 p. m." this week, "12/09/26" before that. */
function listTimestamp(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  const days = (now.getTime() - date.getTime()) / 86_400_000
  if (date.toDateString() === now.toDateString()) return formatDateSafe(value, 'h:mm a')
  if (days < 6) return formatDateSafe(value, 'EEE h:mm a')
  return formatDateSafe(value, 'dd/MM/yy')
}

/**
 * What the assistant told each patient, read-only. Supervising the bot is the
 * point; replying, pausing or taking over a conversation happens on WhatsApp.
 */
export default function ConversationsPage() {
  const api = useApi()
  const [search, setSearch] = useState('')
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState(false)

  const [selected, setSelected] = useState<ConversationSummary | null>(null)
  const [messages, setMessages] = useState<InboxMessage[]>([])
  const [threadLoading, setThreadLoading] = useState(false)
  const [threadError, setThreadError] = useState(false)
  const [hasOlder, setHasOlder] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const loadConversations = useCallback(async () => {
    setListLoading(true)
    setListError(false)
    const res = await api.getConversations(search.trim() || undefined)
    if (res.success && res.data) setConversations(res.data)
    else setListError(true)
    setListLoading(false)
  }, [api, search])

  useEffect(() => {
    const timer = setTimeout(loadConversations, 350)
    return () => clearTimeout(timer)
  }, [loadConversations])

  const openThread = useCallback(
    async (conversation: ConversationSummary) => {
      setSelected(conversation)
      setMessages([])
      setThreadLoading(true)
      setThreadError(false)
      const res = await api.getConversationMessages(conversation.id)
      if (res.success && res.data) {
        setMessages(res.data)
        setHasOlder(res.data.length === PAGE_SIZE)
      } else {
        setThreadError(true)
      }
      setThreadLoading(false)
    },
    [api]
  )

  const loadOlder = async () => {
    if (!selected || messages.length === 0) return
    setLoadingOlder(true)
    const res = await api.getConversationMessages(selected.id, messages[0].created_at)
    if (res.success && res.data) {
      setMessages((prev) => [...res.data!, ...prev])
      setHasOlder(res.data.length === PAGE_SIZE)
    }
    setLoadingOlder(false)
  }

  // Land on the newest message when a thread opens, not when paging back.
  useEffect(() => {
    if (!threadLoading && messages.length > 0 && !loadingOlder) {
      bottomRef.current?.scrollIntoView({ block: 'end' })
    }
  }, [threadLoading]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-6">
      <PageHeader
        title="Conversaciones"
        subtitle="Lo que tu asistente ha hablado con tus pacientes por WhatsApp"
      />

      <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-4 lg:h-[calc(100vh-220px)] lg:min-h-[480px]">
        {/* Thread list — hidden on mobile while a thread is open */}
        <Card className={`flex flex-col min-h-0 ${selected ? 'hidden lg:flex' : 'flex'}`}>
          <div className="p-3 border-b border-gray-100">
            <div className="relative">
              <Search
                size={18}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
              />
              <Input
                placeholder="Buscar por nombre o teléfono..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-10"
                aria-label="Buscar conversaciones"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {listLoading ? (
              <div className="p-3">
                <SkeletonList count={5} />
              </div>
            ) : listError ? (
              <ErrorState onRetry={loadConversations} />
            ) : conversations.length === 0 ? (
              <EmptyState
                icon={MessageCircle}
                title={search.trim() ? 'Sin resultados' : 'Aún no hay conversaciones'}
                description={
                  search.trim()
                    ? 'No encontramos conversaciones que coincidan con tu búsqueda.'
                    : 'Cuando un paciente escriba a tu WhatsApp, la conversación aparecerá aquí.'
                }
              />
            ) : (
              <ul>
                {conversations.map((c) => {
                  const active = selected?.id === c.id
                  return (
                    <li key={c.id}>
                      <button
                        type="button"
                        onClick={() => openThread(c)}
                        className={`w-full text-left px-4 py-3 border-b border-gray-100 transition-colors ${
                          active ? 'bg-primary-50' : 'hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-baseline justify-between gap-2">
                          <p className="text-sm font-semibold text-gray-900 truncate">
                            {threadTitle(c)}
                          </p>
                          <span className="text-[11px] text-gray-500 flex-shrink-0 tabular-nums">
                            {listTimestamp(c.last_message_at)}
                          </span>
                        </div>
                        {c.taken_over_until && (
                          <div className="mt-1">
                            <TakenOverBadge until={c.taken_over_until} />
                          </div>
                        )}
                        {c.last_message_preview && (
                          <p className="text-xs text-gray-600 truncate mt-0.5">
                            {c.last_message_preview}
                          </p>
                        )}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </Card>

        {/* Thread */}
        <Card className={`flex flex-col min-h-[480px] lg:min-h-0 ${selected ? 'flex' : 'hidden lg:flex'}`}>
          {!selected ? (
            <div className="flex-1 flex items-center justify-center">
              <EmptyState
                icon={MessageCircle}
                title="Selecciona una conversación"
                description="Aquí verás cada mensaje tal como lo recibió tu paciente."
              />
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2 px-3 py-3 border-b border-gray-100">
                <Button
                  variant="ghost"
                  size="sm"
                  className="lg:hidden"
                  onClick={() => setSelected(null)}
                  aria-label="Volver a la lista"
                >
                  <ArrowLeft size={16} />
                </Button>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-900 truncate">
                    {threadTitle(selected)}
                  </p>
                  <p className="text-xs text-gray-500 tabular-nums">+{selected.whatsapp_id}</p>
                  {selected.taken_over_until && (
                    <div className="mt-1">
                      <TakenOverBadge until={selected.taken_over_until} />
                    </div>
                  )}
                </div>
                {selected.patient_id && (
                  <Link
                    href={`/dashboard/patients/${selected.patient_id}`}
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline flex-shrink-0"
                  >
                    Ver paciente
                    <ChevronRight size={14} />
                  </Link>
                )}
              </div>

              <div className="flex-1 overflow-y-auto bg-gray-50 px-3 sm:px-5 py-4 space-y-2">
                {threadLoading ? (
                  <SkeletonList count={4} />
                ) : threadError ? (
                  <ErrorState onRetry={() => openThread(selected)} />
                ) : messages.length === 0 ? (
                  <EmptyState title="Sin mensajes" />
                ) : (
                  <>
                    {hasOlder && (
                      <div className="flex justify-center pb-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          isLoading={loadingOlder}
                          onClick={loadOlder}
                        >
                          Ver mensajes anteriores
                        </Button>
                      </div>
                    )}
                    {messages.map((m) => {
                      const outgoing = m.direction === 'outgoing'
                      return (
                        <div
                          key={m.id}
                          className={`flex ${outgoing ? 'justify-end' : 'justify-start'}`}
                        >
                          <div
                            className={`max-w-[85%] sm:max-w-[70%] rounded-2xl px-3.5 py-2 text-sm shadow-sm ${
                              outgoing
                                ? 'bg-primary-50 text-gray-900 rounded-br-md'
                                : 'bg-white text-gray-900 rounded-bl-md border border-gray-100'
                            }`}
                          >
                            {outgoing && (
                              <p className="text-[11px] font-semibold text-primary-700 mb-0.5">
                                {AUTHOR_LABEL[m.author]}
                              </p>
                            )}
                            <p className="whitespace-pre-wrap break-words">{m.content}</p>
                            <p className="text-[10px] text-gray-500 mt-1 text-right tabular-nums">
                              {formatDateSafe(m.created_at, "d MMM, h:mm a")}
                              {m.delivery_status === 'failed' && (
                                <span className="text-red-600 font-medium"> · no se entregó</span>
                              )}
                            </p>
                          </div>
                        </div>
                      )
                    })}
                    <div ref={bottomRef} />
                  </>
                )}
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
