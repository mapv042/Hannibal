'use client'

import React, { useEffect, useRef, useState } from 'react'
import { EyeMark } from '@/components/brand/EyeMark'
import {
  CLOSING_MESSAGE,
  CTA_AFTER,
  GREETING,
  MAX_USER_MESSAGES,
  SUGGESTIONS,
  getDemoReply,
  type Turn,
} from '@/components/landing/demoScript'

/** WhatsApp's doodle wallpaper, inlined so the page makes no outside request. */
const WA_DOODLES = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100'%3E%3Cg fill='%23000000' fill-opacity='0.025'%3E%3Cpath d='M11 18c3.866 0 7-3.134 7-7s-3.134-7-7-7-7 3.134-7 7 3.134 7 7 7zm48 25c3.866 0 7-3.134 7-7s-3.134-7-7-7-7 3.134-7 7 3.134 7 7 7zm-43-7c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zm63 31c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zM34 90c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zm56-76c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zM12 86c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm28-65c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm23-11c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zm-6 60c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4z'/%3E%3C/g%3E%3C/svg%3E")`

interface Bubble {
  role: 'user' | 'assistant'
  text: string
  time: string
}

function fmtTime(d: Date) {
  const m = d.getMinutes().toString().padStart(2, '0')
  const ap = d.getHours() >= 12 ? 'p. m.' : 'a. m.'
  const h = d.getHours() % 12 || 12
  return `${h}:${m} ${ap}`
}

function fmtClock(d: Date) {
  const m = d.getMinutes().toString().padStart(2, '0')
  return `${d.getHours() % 12 || 12}:${m}`
}

/** WhatsApp's read receipt. */
function BlueTicks() {
  return (
    <svg width="15" height="10" viewBox="0 0 16 11" fill="none" className="flex-shrink-0">
      <path
        d="M1 5.5L4.5 9L11 1.5"
        stroke="#53BDEB"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M5.5 5.5L9 9L15.5 1.5"
        stroke="#53BDEB"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

interface WhatsAppPhoneProps {
  /** Fires once the visitor has exchanged enough turns to be worth asking. */
  onEngaged?: () => void
}

/**
 * A WhatsApp conversation rendered as a screenshot, not as a device.
 *
 * Dropping the phone body is the point: a doctor evaluating this has seen a
 * thousand marketing mockups inside a rounded rectangle with a notch. What
 * convinces them is the chat looking like the one already open on their phone —
 * so the details that get the budget are the iOS status bar showing their own
 * clock, the encryption notice, the doodle wallpaper and the blue ticks.
 */
export const WhatsAppPhone: React.FC<WhatsAppPhoneProps> = ({ onEngaged }) => {
  const [bubbles, setBubbles] = useState<Bubble[]>([])
  const [history, setHistory] = useState<Turn[]>([
    { role: 'assistant', content: GREETING },
  ])
  const [clock, setClock] = useState('9:15')
  const [greetingTime, setGreetingTime] = useState('9:14 a. m.')
  const [typing, setTyping] = useState(false)
  const [input, setInput] = useState('')
  const [userMsgCount, setUserMsgCount] = useState(0)
  const [showChips, setShowChips] = useState(true)
  const [finished, setFinished] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  // Times come from the visitor's own device, so they can only be read after
  // hydration — rendering them on the server would mismatch.
  useEffect(() => {
    const now = new Date()
    setClock(fmtClock(now))
    setGreetingTime(fmtTime(now))
  }, [])

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [bubbles, typing])

  const send = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || typing || finished) return

    setShowChips(false)
    setInput('')
    const now = new Date()
    setBubbles((b) => [...b, { role: 'user', text: trimmed, time: fmtTime(now) }])

    const nextCount = userMsgCount + 1
    setUserMsgCount(nextCount)
    if (nextCount >= CTA_AFTER) onEngaged?.()

    const historyNow: Turn[] = [...history, { role: 'user', content: trimmed }]
    setHistory(historyNow)
    setTyping(true)

    let reply: string
    try {
      reply = await getDemoReply(trimmed, historyNow)
    } catch {
      reply = 'Ups, tuve un problema de conexión. ¿Puede intentar de nuevo? 🙏'
    }

    setTyping(false)
    setBubbles((b) => [
      ...b,
      { role: 'assistant', text: reply, time: fmtTime(new Date()) },
    ])
    setHistory((h) => [...h, { role: 'assistant', content: reply }])

    if (nextCount >= MAX_USER_MESSAGES) {
      setFinished(true)
      setBubbles((b) => [
        ...b,
        { role: 'assistant', text: CLOSING_MESSAGE, time: fmtTime(new Date()) },
      ])
      onEngaged?.()
    }
  }

  return (
    <div
      className="w-full max-w-[360px] mx-auto overflow-hidden bg-[#ECE5DD] shadow-float"
      style={{ borderRadius: 32, border: '6px solid #0a0a0a' }}
    >
      {/* iOS status bar */}
      <div className="bg-[#F7F5F3] px-5 pt-1.5 pb-1 flex items-center justify-between">
        <span className="text-[13.5px] font-semibold text-black tabular-nums">{clock}</span>
        <div className="flex items-center gap-1.5">
          <svg width="17" height="11" viewBox="0 0 17 11" fill="none" aria-hidden="true">
            <rect x="0" y="6" width="3" height="5" rx="0.5" fill="#000" />
            <rect x="4.5" y="4" width="3" height="7" rx="0.5" fill="#000" />
            <rect x="9" y="2" width="3" height="9" rx="0.5" fill="#000" />
            <rect x="13.5" y="0" width="3" height="11" rx="0.5" fill="#000" />
          </svg>
          <svg width="15" height="11" viewBox="0 0 15 11" fill="none" aria-hidden="true">
            <path
              d="M7.5 2.5C10 2.5 12 3.5 13.5 5.2L12.2 6.6C11 5.2 9.3 4.4 7.5 4.4C5.7 4.4 4 5.2 2.8 6.6L1.5 5.2C3 3.5 5 2.5 7.5 2.5Z"
              fill="#000"
            />
            <path
              d="M7.5 6.5C8.6 6.5 9.6 7 10.3 7.8L7.5 10.8L4.7 7.8C5.4 7 6.4 6.5 7.5 6.5Z"
              fill="#000"
            />
          </svg>
          <svg width="24" height="11" viewBox="0 0 24 11" fill="none" aria-hidden="true">
            <rect
              x="0.5"
              y="0.5"
              width="20"
              height="10"
              rx="2.3"
              stroke="#000"
              strokeOpacity="0.4"
            />
            <rect x="2" y="2" width="15" height="7" rx="1.3" fill="#000" />
            <rect x="21.5" y="3.5" width="1.5" height="4" rx="0.7" fill="#000" fillOpacity="0.4" />
          </svg>
        </div>
      </div>

      {/* Conversation header */}
      <div className="bg-[#F7F5F3] flex items-center gap-2.5 px-3 pt-1.5 pb-2.5">
        <svg width="11" height="19" viewBox="0 0 11 19" fill="none" aria-hidden="true">
          <path
            d="M9.5 1L1 9.5L9.5 18"
            stroke="#028478"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <div className="w-[34px] h-[34px] rounded-full bg-[#0B141A] flex items-center justify-center flex-shrink-0 overflow-hidden">
          <EyeMark size={26} variant="compact" color="#2952A3" iris="#0B141A" pupil="#2952A3" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-black text-[14.5px] font-semibold truncate">
            Consultorio Dr. García
          </div>
          <div className="text-[#667781] text-[11.5px]">
            {typing ? 'escribiendo…' : 'en línea'}
          </div>
        </div>
        <div className="flex items-center gap-4 text-[#028478]" aria-hidden="true">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor">
            <path d="M17 10.5V7a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h12a1 1 0 001-1v-3.5l4 4v-11l-4 4z" />
          </svg>
          <svg width="4" height="18" viewBox="0 0 4 18" fill="currentColor">
            <circle cx="2" cy="2" r="2" />
            <circle cx="2" cy="9" r="2" />
            <circle cx="2" cy="16" r="2" />
          </svg>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={bodyRef}
        className="h-[340px] sm:h-[380px] overflow-y-auto px-2.5 pt-3 pb-2 flex flex-col gap-1.5 scroll-smooth"
        style={{ backgroundColor: '#ECE5DD', backgroundImage: WA_DOODLES }}
      >
        <div className="self-center bg-[#FFF3C4] text-[#7A6A2E] text-[9.5px] px-3 py-1.5 rounded-lg mb-1 flex items-center gap-1.5 max-w-[240px] text-center leading-tight">
          <svg width="11" height="13" viewBox="0 0 11 13" fill="none" className="flex-shrink-0">
            <path d="M2 5.5V3.5a3.5 3.5 0 017 0v2" stroke="#8696A0" strokeWidth="1.1" fill="none" />
            <rect x="1" y="5.5" width="9" height="6.5" rx="1.3" fill="#8696A0" />
          </svg>
          <span>Los mensajes están cifrados de extremo a extremo</span>
        </div>

        <div className="self-center bg-[#E1F2FB] text-[#4C7C93] text-[10.5px] font-medium px-2.5 py-1 rounded-lg mb-1">
          Hoy
        </div>

        <div className="wa-msg self-start bg-white max-w-[84%] px-2.5 py-2 rounded-lg rounded-tl-sm shadow-[0_1px_0.5px_rgba(11,20,26,0.13)] flex flex-col">
          <span className="text-[13.5px] text-[#111B21] leading-snug">{GREETING}</span>
          <span className="self-end text-[10px] text-[rgba(17,27,33,0.45)] mt-0.5">
            {greetingTime}
          </span>
        </div>

        {showChips && (
          <div className="flex flex-wrap gap-1.5 mt-1">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => send(s)}
                className="bg-white border border-accent text-accent text-[11px] font-semibold px-2.5 py-1.5 rounded-full hover:bg-primary-50 transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {bubbles.map((b, i) => (
          <div
            key={i}
            className={`wa-msg max-w-[84%] px-2.5 py-2 rounded-lg shadow-[0_1px_0.5px_rgba(11,20,26,0.13)] flex flex-col ${
              b.role === 'user'
                ? 'self-end bg-[#D9FDD3] rounded-tr-sm'
                : 'self-start bg-white rounded-tl-sm'
            }`}
          >
            <span className="text-[13.5px] text-[#111B21] leading-snug whitespace-pre-wrap">
              {b.text}
            </span>
            <span className="self-end flex items-center gap-1 text-[10px] text-[rgba(17,27,33,0.45)] mt-0.5">
              {b.time}
              {b.role === 'user' && <BlueTicks />}
            </span>
          </div>
        ))}

        {typing && (
          <div className="wa-msg self-start bg-white px-3 py-2.5 rounded-lg rounded-tl-sm shadow-[0_1px_0.5px_rgba(11,20,26,0.13)] flex gap-1">
            <span className="wa-dot" />
            <span className="wa-dot" />
            <span className="wa-dot" />
          </div>
        )}

        {finished && (
          <div className="self-center bg-[#F0E6D6] text-[#8A6D3B] text-[10.5px] font-medium px-2.5 py-1 rounded-lg mt-1">
            — Fin de la demo —
          </div>
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
        className="bg-[#F7F5F3] px-2.5 pt-2 pb-3 flex items-center gap-2"
      >
        <div className="flex-1 bg-white rounded-[20px] px-3.5 py-2 flex items-center gap-2 shadow-[0_1px_0.5px_rgba(11,20,26,0.1)]">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={finished}
            placeholder={
              finished ? 'Demo terminada — actívelo abajo' : 'Escríbale a Sofía…'
            }
            aria-label="Escribir un mensaje a Sofía"
            autoComplete="off"
            className="flex-1 min-w-0 bg-transparent border-none outline-none text-[13.5px] text-[#111B21] placeholder:text-[#8696A0]"
          />
        </div>
        <button
          type="submit"
          disabled={finished || typing}
          aria-label="Enviar mensaje"
          className="w-9 h-9 rounded-full bg-[#00A884] flex items-center justify-center flex-shrink-0 disabled:opacity-40 transition-opacity"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="#fff" aria-hidden="true">
            <path d="M3 20l17-8L3 4v6l12 2-12 2v6z" />
          </svg>
        </button>
      </form>
    </div>
  )
}

WhatsAppPhone.displayName = 'WhatsAppPhone'
