'use client'

import React, { useState, useEffect } from 'react'
import Link from 'next/link'
import { useRouter, usePathname } from 'next/navigation'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { BotStatusBadge } from '@/components/coexistence/BotStatusBadge'
import { Button } from '@/components/ui/Button'
import { useApi } from '@/lib/api'
import {
  Calendar,
  Users,
  Settings,
  LogOut,
  Menu,
  X,
  Heart,
  Clock,
} from 'lucide-react'
import type { Office } from '@/lib/supabase'

const navItems = [
  {
    label: 'Today',
    href: '/dashboard',
    icon: Clock,
  },
  {
    label: 'Schedule',
    href: '/dashboard/schedule',
    icon: Calendar,
  },
  {
    label: 'Patients',
    href: '/dashboard/patients',
    icon: Users,
  },
  {
    label: 'Settings',
    href: '/dashboard/settings',
    icon: Settings,
  },
]

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [user, setUser] = useState<any>(null)
  const [office, setOffice] = useState<Office | null>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()
  const pathname = usePathname()
  const supabase = createBrowserSupabaseClient()
  const api = useApi()

  useEffect(() => {
    const loadUser = async () => {
      try {
        const {
          data: { user },
        } = await supabase.auth.getUser()
        setUser(user)

        if (user) {
          const officeRes = await api.listOffices()
          if (officeRes.success && officeRes.data && officeRes.data.length > 0) {
            const userOffice = officeRes.data[0]
            if (!userOffice.onboarding_completed) {
              router.push('/onboarding')
              return
            }
            setOffice(userOffice)
          } else {
            router.push('/onboarding')
            return
          }
        }
      } catch (error) {
        console.error('Error loading user:', error)
      } finally {
        setLoading(false)
      }
    }

    loadUser()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleLogout = async () => {
    await supabase.auth.signOut()
    router.push('/login')
    router.refresh()
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full border-4 border-primary-200 border-t-primary-600 animate-spin mx-auto mb-4" />
          <p className="text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 bg-white border-r border-gray-200 transition-transform duration-300 w-64 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        } lg:translate-x-0 lg:static`}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-6 border-b border-gray-200">
          <div className="p-2 bg-primary-100 rounded-lg">
            <Heart className="w-6 h-6 text-primary-600" fill="currentColor" />
          </div>
          <div>
            <h1 className="font-bold text-lg text-gray-900">Hannibal</h1>
            <p className="text-xs text-gray-500">Asistente WhatsApp</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-4 py-6 space-y-2">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = pathname === item.href

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-4 py-2.5 rounded-lg transition-colors duration-200 ${
                  isActive
                    ? 'bg-primary-50 text-primary-600 font-medium'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
                onClick={() => setSidebarOpen(false)}
              >
                <Icon size={20} />
                <span>{item.label}</span>
              </Link>
            )
          })}
        </nav>

        {/* Bot Status */}
        {office && (
          <div className="px-4 py-4 border-t border-gray-200">
            <p className="text-xs font-medium text-gray-600 mb-3 uppercase tracking-wide">
              Bot Status
            </p>
            <BotStatusBadge
              officeId={office.id}
              currentStatus={office.is_active ? 'active' : 'paused'}
            />
          </div>
        )}

        {/* User Menu */}
        <div className="px-4 py-4 border-t border-gray-200">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-full bg-primary-100 flex items-center justify-center">
              <span className="font-semibold text-primary-600">
                {user?.email?.[0].toUpperCase() || 'U'}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">
                {user?.email || 'User'}
              </p>
              <p className="text-xs text-gray-500">Doctor</p>
            </div>
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={handleLogout}
            className="w-full justify-start gap-2"
          >
            <LogOut size={16} />
            Sign Out
          </Button>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="bg-white border-b border-gray-200">
          <div className="flex items-center justify-between h-16 px-4 lg:px-8">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="lg:hidden p-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            >
              {sidebarOpen ? (
                <X size={24} />
              ) : (
                <Menu size={24} />
              )}
            </button>

            <div className="flex-1" />

            <div className="text-right">
              <p className="text-sm font-medium text-gray-900">
                {office?.assistant_name || 'My Office'}
              </p>
              <p className="text-xs text-gray-500">
                {office?.whatsapp_phone || 'No number'}
              </p>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-auto">
          <div className="p-4 lg:p-8">{children}</div>
        </main>
      </div>

      {/* Mobile Sidebar Backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
    </div>
  )
}
