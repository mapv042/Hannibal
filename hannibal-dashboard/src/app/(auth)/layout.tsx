export const dynamic = 'force-dynamic'

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div
      className="relative min-h-screen flex items-center justify-center py-12 px-4"
      style={{
        background:
          'radial-gradient(ellipse 800px 400px at 50% 0%, rgba(41,82,163,0.05), transparent), #fff',
      }}
    >
      <div className="relative w-full max-w-md">{children}</div>
    </div>
  )
}
