'use client'

import React, { useState, useEffect } from 'react'
import Link from 'next/link'
import { format } from 'date-fns'
import { es } from 'date-fns/locale'
import { useApi } from '@/lib/api'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Input } from '@/components/ui/Input'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Users, Search } from 'lucide-react'
import type { Patient } from '@/lib/supabase'

export default function PatientsPage() {
  const [_patients, setPatients] = useState<Patient[]>([])
  const [search, setSearch] = useState('')
  const [filteredPatients, setFilteredPatients] = useState<Patient[]>([])
  const [loading, setLoading] = useState(true)
  const api = useApi()
  const supabase = createBrowserSupabaseClient()

  useEffect(() => {
    const loadPatients = async () => {
      try {
        const {
          data: { user },
        } = await supabase.auth.getUser()

        if (!user) return

        const response = await api.getPatients(user.id, search || undefined)
        if (response.success && response.data) {
          setPatients(response.data)
          setFilteredPatients(response.data)
        }
      } catch (error) {
        console.error('Error loading patients:', error)
      } finally {
        setLoading(false)
      }
    }

    const timer = setTimeout(() => {
      loadPatients()
    }, 300)

    return () => clearTimeout(timer)
  }, [api, supabase, search])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Pacientes</h1>
        <p className="text-gray-600 mt-1">Administra y consulta la información de tus pacientes</p>
      </div>

      {/* Search */}
      <div className="relative">
        <Input
          placeholder="Buscar por nombre o teléfono..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-10"
        />
        <Search size={20} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
      </div>

      {/* Patients List */}
      <Card>
        <CardHeader>
          <h2 className="text-xl font-semibold text-gray-900">
            {filteredPatients.length} Paciente{filteredPatients.length !== 1 ? 's' : ''}
          </h2>
        </CardHeader>
        <CardBody>
          {loading ? (
            <div className="text-center py-12">
              <p className="text-gray-600">Cargando pacientes...</p>
            </div>
          ) : filteredPatients.length === 0 ? (
            <div className="text-center py-12">
              <Users size={48} className="mx-auto text-gray-300 mb-4" />
              <p className="text-gray-600">No se encontraron pacientes</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-3 px-4 font-medium text-gray-700 text-sm">
                      Nombre
                    </th>
                    <th className="text-left py-3 px-4 font-medium text-gray-700 text-sm">
                      Teléfono
                    </th>
                    <th className="text-left py-3 px-4 font-medium text-gray-700 text-sm">
                      Correo
                    </th>
                    <th className="text-left py-3 px-4 font-medium text-gray-700 text-sm">
                      Citas
                    </th>
                    <th className="text-left py-3 px-4 font-medium text-gray-700 text-sm">
                      Última cita
                    </th>
                    <th className="text-left py-3 px-4 font-medium text-gray-700 text-sm">
                      Acciones
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPatients.map((patient) => (
                    <tr
                      key={patient.id}
                      className="border-b border-gray-200 hover:bg-gray-50 transition-colors"
                    >
                      <td className="py-3 px-4 text-sm font-medium text-gray-900">
                        {patient.name}
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-600">
                        {patient.whatsapp_number}
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-600">
                        {patient.email}
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-900 font-medium">
                        {patient.total_consultations}
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-600">
                        {patient.last_consultation_at
                          ? format(new Date(patient.last_consultation_at), 'dd/MM/yy', {
                              locale: es,
                            })
                          : '-'}
                      </td>
                      <td className="py-3 px-4 text-sm">
                        <Link
                          href={`/dashboard/patients/${patient.id}`}
                          className="text-primary-600 hover:text-primary-700 font-medium"
                        >
                          Ver perfil
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
