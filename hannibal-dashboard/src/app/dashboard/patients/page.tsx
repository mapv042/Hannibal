'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import { useApi } from '@/lib/api'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Input } from '@/components/ui/Input'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { EmptyState } from '@/components/ui/states/EmptyState'
import { ErrorState } from '@/components/ui/states/ErrorState'
import { SkeletonRows } from '@/components/ui/states/Skeleton'
import { Users, Search, ChevronRight } from 'lucide-react'
import type { Patient } from '@/lib/supabase'

export default function PatientsPage() {
  const [patients, setPatients] = useState<Patient[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const api = useApi()
  const supabase = createBrowserSupabaseClient()
  const router = useRouter()

  const loadPatients = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const {
        data: { user },
      } = await supabase.auth.getUser()

      if (!user) return

      const response = await api.getPatients(user.id, search || undefined)
      if (response.success && response.data) {
        setPatients(response.data)
      } else {
        setError(true)
      }
    } catch (err) {
      console.error('Error loading patients:', err)
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [api, supabase, search])

  useEffect(() => {
    const timer = setTimeout(loadPatients, 350)
    return () => clearTimeout(timer)
  }, [loadPatients])

  const isSearching = search.trim().length > 0

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pacientes"
        subtitle="Administra y consulta la información de tus pacientes"
      />

      {/* Search */}
      <div className="relative">
        <Search size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <Input
          placeholder="Buscar por nombre o teléfono..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-10"
          aria-label="Buscar pacientes"
        />
      </div>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold text-gray-900">
            {loading ? 'Pacientes' : `${patients.length} Paciente${patients.length !== 1 ? 's' : ''}`}
          </h2>
        </CardHeader>
        <CardBody>
          {loading ? (
            <SkeletonRows rows={6} cols={5} />
          ) : error ? (
            <ErrorState onRetry={loadPatients} />
          ) : patients.length === 0 ? (
            <EmptyState
              icon={Users}
              title={isSearching ? 'Sin resultados' : 'Aún no tienes pacientes'}
              description={
                isSearching
                  ? 'No encontramos pacientes que coincidan con tu búsqueda.'
                  : 'Los pacientes aparecerán aquí cuando el asistente registre su primera conversación.'
              }
            />
          ) : (
            <>
              {/* Desktop / tablet: table */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th scope="col" className="text-left py-3 px-4 font-medium text-gray-700 text-sm">Nombre</th>
                      <th scope="col" className="text-left py-3 px-4 font-medium text-gray-700 text-sm">Teléfono</th>
                      <th scope="col" className="text-left py-3 px-4 font-medium text-gray-700 text-sm">Correo</th>
                      <th scope="col" className="text-left py-3 px-4 font-medium text-gray-700 text-sm">Citas</th>
                      <th scope="col" className="text-left py-3 px-4 font-medium text-gray-700 text-sm">Última cita</th>
                      <th scope="col" className="w-10" />
                    </tr>
                  </thead>
                  <tbody>
                    {patients.map((patient) => (
                      <tr
                        key={patient.id}
                        onClick={() => router.push(`/dashboard/patients/${patient.id}`)}
                        className="border-b border-gray-200 hover:bg-gray-50 transition-colors cursor-pointer"
                      >
                        <td className="py-3 px-4 text-sm font-medium text-gray-900">{patient.name}</td>
                        <td className="py-3 px-4 text-sm text-gray-600 tabular-nums">{patient.whatsapp_number}</td>
                        <td className="py-3 px-4 text-sm text-gray-600">{patient.email || '—'}</td>
                        <td className="py-3 px-4 text-sm text-gray-900 font-medium tabular-nums">{patient.total_consultations}</td>
                        <td className="py-3 px-4 text-sm text-gray-600 tabular-nums">
                          {patient.last_consultation_at
                            ? format(new Date(patient.last_consultation_at), 'dd/MM/yy', { locale: es })
                            : '—'}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <ChevronRight size={16} className="text-gray-400" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile: stacked cards */}
              <div className="md:hidden space-y-2">
                {patients.map((patient) => (
                  <button
                    key={patient.id}
                    type="button"
                    onClick={() => router.push(`/dashboard/patients/${patient.id}`)}
                    className="w-full flex items-center justify-between gap-3 p-3 rounded-xl border border-gray-200 text-left hover:bg-gray-50 transition-colors"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-gray-900 truncate">{patient.name}</p>
                      <p className="text-xs text-gray-500 tabular-nums mt-0.5">{patient.whatsapp_number}</p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {patient.total_consultations} cita{patient.total_consultations !== 1 ? 's' : ''}
                        {patient.last_consultation_at &&
                          ` · ${format(new Date(patient.last_consultation_at), 'dd/MM/yy', { locale: es })}`}
                      </p>
                    </div>
                    <ChevronRight size={18} className="text-gray-400 flex-shrink-0" />
                  </button>
                ))}
              </div>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
