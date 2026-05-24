export const dynamic = 'force-dynamic'

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div
      className="relative min-h-screen flex items-center justify-center py-12 px-4 overflow-hidden"
      style={{
        background: `radial-gradient(ellipse 60% 50% at 20% 20%, rgba(var(--primary-rgb-500), .12), transparent 60%),
                     radial-gradient(ellipse 60% 50% at 80% 90%, rgba(var(--secondary-rgb-500), .10), transparent 60%),
                     linear-gradient(180deg, #eef1fa, #d3dcf2)`,
      }}
    >
      {/* faint dotted backdrop */}
      <div
        className="absolute inset-0 pointer-events-none opacity-60"
        style={{
          backgroundImage: 'radial-gradient(circle, #d1d5db 1px, transparent 1px)',
          backgroundSize: '24px 24px',
          maskImage: 'radial-gradient(ellipse 70% 60% at 50% 50%, transparent, #000 80%)',
          WebkitMaskImage: 'radial-gradient(ellipse 70% 60% at 50% 50%, transparent, #000 80%)',
        }}
      />
      <div className="relative w-full max-w-md">
        {children}
      </div>
    </div>
  )
}
