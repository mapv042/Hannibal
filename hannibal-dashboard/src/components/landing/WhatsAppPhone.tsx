import React from 'react'
import { ChevronLeft, Phone, MoreVertical, Mic } from 'lucide-react'

const WA_HEADER = '#075e54'
const WA_GREEN = '#075e54'
const WA_BG = '#e5ddd5'

const WA_BG_PATTERN = `url("data:image/svg+xml;utf8,${encodeURIComponent(
  `<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200' viewBox='0 0 200 200'>
    <g fill='none' stroke='%23000' stroke-opacity='0.04' stroke-width='1'>
      <path d='M20 40 q10 -10 20 0 t20 0' />
      <circle cx='130' cy='60' r='8' />
      <path d='M50 120 l8 8 l16 -16' />
      <rect x='150' y='130' width='14' height='14' rx='3' transform='rotate(15 157 137)'/>
      <path d='M30 170 q15 -8 30 0' />
      <circle cx='100' cy='100' r='3' fill='%23000' fill-opacity='0.05' stroke='none'/>
    </g>
  </svg>`
)}")`

interface Message {
  date?: string
  from?: 'me' | 'them'
  text?: string
  time?: string
  ticks?: number
}

const DEMO_CONVO: Message[] = [
  { date: 'HOY' },
  { from: 'them', text: 'Hola, buenas tardes. Quería agendar una cita con el Dr. Méndez.', time: '14:22' },
  {
    from: 'me',
    text: '¡Hola! Soy Sofía, asistente del Dr. Méndez 👋\n\nClaro que sí, te ayudo a agendar. ¿Es tu primera consulta o eres paciente recurrente?',
    time: '14:22',
    ticks: 2,
  },
  { from: 'them', text: 'Es mi primera vez.', time: '14:23' },
  { from: 'me', text: 'Perfecto. ¿Me compartes tu nombre completo, por favor?', time: '14:23', ticks: 2 },
  { from: 'them', text: 'Mariana López Reyes', time: '14:24' },
  {
    from: 'me',
    text: 'Gracias, Mariana. Tengo estos espacios disponibles esta semana:\n\n• Jueves 25 — 11:00 hrs\n• Jueves 25 — 17:30 hrs\n• Viernes 26 — 09:00 hrs',
    time: '14:24',
    ticks: 2,
  },
  { from: 'them', text: 'El jueves 25 a las 17:30 me funciona', time: '14:25' },
  {
    from: 'me',
    text: '✓ Cita confirmada\n\nJue 25 de septiembre, 17:30 hrs\nDr. Méndez · Primera consulta\nDuración: 45 min\n\nTe mandaré un recordatorio 24h antes. ¿Necesitas algo más?',
    time: '14:25',
    ticks: 2,
  },
]

function Ticks({ blue }: { blue: boolean }) {
  return (
    <svg width="16" height="11" viewBox="0 0 16 11" fill="none" className="inline-block ml-1">
      <path d="M11.07.4L5.27 6.2l-.85.84L2 4.62l-.71.7L5.27 9.3 12.5 1.1z" fill={blue ? '#4fc3f7' : '#667781'} />
      <path d="M14.45.4l-5.8 5.8-.85.84-.7-.7L13.7 1.1z" fill={blue ? '#4fc3f7' : '#667781'} />
    </svg>
  )
}

function Bubble({ msg }: { msg: Message }) {
  const isMe = msg.from === 'me'
  return (
    <div className={`flex px-2 mb-1.5 ${isMe ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`relative max-w-[80%] rounded-lg px-2.5 py-1.5 shadow-[0_1px_0.5px_rgba(0,0,0,.13)] ${
          isMe ? 'bg-[#dcf8c6] rounded-tr-none' : 'bg-white rounded-tl-none'
        }`}
        style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif' }}
      >
        <div className="text-[14.5px] leading-snug text-[#0b141a] whitespace-pre-wrap">{msg.text}</div>
        <div className="flex justify-end items-center text-[11px] text-[#667781] mt-0.5 tabular-nums">
          {msg.time}
          {isMe && <Ticks blue={(msg.ticks ?? 0) >= 2} />}
        </div>
      </div>
    </div>
  )
}

interface WhatsAppPhoneProps {
  width?: number
  name?: string
}

export const WhatsAppPhone: React.FC<WhatsAppPhoneProps> = ({
  width = 340,
  name = 'Sofía · Asistente',
}) => {
  const height = Math.round(width / 0.462)
  const radius = Math.round(width * 0.165)

  return (
    <div
      className="relative bg-[#0b1014]"
      style={{
        width,
        height,
        borderRadius: radius,
        padding: 8,
        boxShadow:
          '0 30px 80px -20px rgba(15,30,40,.35), 0 6px 18px rgba(15,30,40,.18), inset 0 0 0 2px rgba(255,255,255,.06)',
      }}
    >
      {/* Side buttons */}
      <div className="absolute -left-0.5 top-[15%] w-[3px] h-8 bg-[#1a2228] rounded" />
      <div className="absolute -left-0.5 top-[24%] w-[3px] h-14 bg-[#1a2228] rounded" />
      <div className="absolute -left-0.5 top-[33%] w-[3px] h-14 bg-[#1a2228] rounded" />
      <div className="absolute -right-0.5 top-[22%] w-[3px] h-[90px] bg-[#1a2228] rounded" />

      {/* Screen */}
      <div
        className="relative w-full h-full overflow-hidden flex flex-col"
        style={{ background: WA_BG, borderRadius: radius - 8 }}
      >
        {/* Dynamic island */}
        <div
          className="absolute top-2 left-1/2 -translate-x-1/2 bg-black rounded-full z-10"
          style={{ width: width * 0.32, height: 26 }}
        />

        {/* Status bar */}
        <div
          className="h-11 px-5 flex items-center justify-between text-white text-sm font-semibold"
          style={{ background: WA_HEADER, fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' }}
        >
          <span className="tabular-nums">9:41</span>
          <div className="flex items-center gap-1.5">
            <svg width="17" height="11" viewBox="0 0 17 11" fill="#fff"><rect x="0" y="7" width="3" height="4" rx="0.5" /><rect x="4.5" y="5" width="3" height="6" rx="0.5" /><rect x="9" y="3" width="3" height="8" rx="0.5" /><rect x="13.5" y="0" width="3" height="11" rx="0.5" /></svg>
            <svg width="27" height="12" viewBox="0 0 27 12" fill="none"><rect x="0.5" y="0.5" width="22" height="11" rx="2.5" stroke="#fff" opacity="0.5" /><rect x="2" y="2" width="19" height="8" rx="1.5" fill="#fff" /><rect x="23.5" y="3.5" width="2" height="5" rx="1" fill="#fff" opacity="0.5" /></svg>
          </div>
        </div>

        {/* Chat header */}
        <div className="h-14 flex items-center px-3 gap-2.5 text-white" style={{ background: WA_HEADER }}>
          <ChevronLeft size={22} strokeWidth={2.4} />
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm"
            style={{ background: 'linear-gradient(135deg, #3b5fc7, #1535a3)' }}
          >
            S
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[15px] font-semibold">{name}</div>
            <div className="text-xs opacity-85">en línea</div>
          </div>
          <Phone size={18} />
          <MoreVertical size={18} />
        </div>

        {/* Chat */}
        <div
          className="flex-1 overflow-hidden py-2 flex flex-col"
          style={{ background: WA_BG, backgroundImage: WA_BG_PATTERN, backgroundSize: '200px' }}
        >
          {DEMO_CONVO.map((m, i) =>
            m.date ? (
              <div key={i} className="flex justify-center py-2">
                <div className="bg-[rgba(225,245,254,.92)] text-[#54656f] text-xs font-medium px-2.5 py-1 rounded-lg shadow-[0_1px_0.5px_rgba(0,0,0,.08)]">
                  {m.date}
                </div>
              </div>
            ) : (
              <Bubble key={i} msg={m} />
            )
          )}
        </div>

        {/* Composer */}
        <div className="px-2 py-1.5 flex items-center gap-2 bg-[#f0f2f5]">
          <div className="flex-1 bg-white rounded-3xl px-3 py-2 flex items-center gap-2.5 text-sm text-[#8696a0]">
            <span className="flex-1">Mensaje</span>
          </div>
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center text-white"
            style={{ background: WA_GREEN }}
          >
            <Mic size={18} />
          </div>
        </div>

        {/* Home indicator */}
        <div
          className="absolute bottom-1.5 left-1/2 -translate-x-1/2 h-1 bg-black rounded-full opacity-85 z-10"
          style={{ width: width * 0.32 }}
        />
      </div>
    </div>
  )
}

WhatsAppPhone.displayName = 'WhatsAppPhone'
