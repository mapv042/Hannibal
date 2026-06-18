'use client'

import React, { useState, useEffect } from 'react'
import { useApi, type ReminderRule } from '@/lib/api'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { PageHeader } from '@/components/ui/PageHeader'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Settings, Save, Globe, Zap, Clock, Bell, BellRing, LucideIcon } from 'lucide-react'
import type { Office } from '@/lib/supabase'

type NotifKey =
  | 'notify_new_appointment'
  | 'notify_cancellation'
  | 'notify_new_patient'
  | 'notify_unconfirmed'

const NOTIFICATION_DEFS: { key: NotifKey; label: string; description: string }[] = [
  {
    key: 'notify_new_appointment',
    label: 'Cita nueva agendada',
    description: 'Te avisamos cuando el asistente agenda una cita.',
  },
  {
    key: 'notify_cancellation',
    label: 'Cancelación de paciente',
    description: 'Te avisamos cuando un paciente cancela su cita.',
  },
  {
    key: 'notify_new_patient',
    label: 'Paciente nuevo',
    description: 'Te avisamos cuando se registra un paciente nuevo.',
  },
  {
    key: 'notify_unconfirmed',
    label: 'Citas sin confirmar',
    description: 'Resumen al inicio del día con las citas de hoy sin confirmar.',
  },
]
import {
  REMINDER_DEFS,
  DEFAULT_REMINDER_TOGGLES,
  reminderTogglesFromRules,
  rulesFromReminderToggles,
  type ReminderToggles,
  type ReminderType,
} from '@/components/onboarding/StepSchedule'

/** Marks a section/control that is intentionally not wired up yet (pre-launch). */
function SoonPill() {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-100 text-gray-500 uppercase tracking-wide">
      Próximamente
    </span>
  )
}

function SectionHeader({
  icon: Icon,
  title,
  subtitle,
  soon,
}: {
  icon: LucideIcon
  title: string
  subtitle?: string
  soon?: boolean
}) {
  return (
    <div className="flex items-center gap-3.5">
      <div className="w-10 h-10 rounded-[10px] bg-primary-50 flex items-center justify-center flex-shrink-0">
        <Icon size={20} className="text-primary-700" />
      </div>
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold tracking-tight text-gray-900">{title}</h2>
          {soon && <SoonPill />}
        </div>
        {subtitle && <p className="text-[13px] text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const [office, setOffice] = useState<Office | null>(null)
  const [formData, setFormData] = useState({
    assistant_name: '',
    tone: 'formal' as 'formal' | 'informal',
    custom_prompt: '',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [reminders, setReminders] = useState<ReminderToggles>(DEFAULT_REMINDER_TOGGLES)
  const [savingReminders, setSavingReminders] = useState(false)
  const [remindersSaved, setRemindersSaved] = useState(false)
  const [notifications, setNotifications] = useState<Record<NotifKey, boolean>>({
    notify_new_appointment: true,
    notify_cancellation: true,
    notify_new_patient: true,
    notify_unconfirmed: true,
  })
  const [savingNotifications, setSavingNotifications] = useState(false)
  const [notificationsSaved, setNotificationsSaved] = useState(false)
  const api = useApi()
  const supabase = createBrowserSupabaseClient()

  useEffect(() => {
    const loadOffice = async () => {
      try {
        const {
          data: { user },
        } = await supabase.auth.getUser()

        if (!user) return

        const response = await api.listOffices()
        if (response.success && response.data && response.data.length > 0) {
          const officeData = response.data[0]
          setOffice(officeData)
          setFormData({
            assistant_name: officeData.assistant_name,
            tone: officeData.assistant_tone as 'formal' | 'informal',
            custom_prompt: officeData.custom_prompt || '',
          })

          setNotifications({
            notify_new_appointment: officeData.notify_new_appointment,
            notify_cancellation: officeData.notify_cancellation,
            notify_new_patient: officeData.notify_new_patient,
            notify_unconfirmed: officeData.notify_unconfirmed,
          })

          const rulesRes = await api.getReminderRules(officeData.id)
          if (rulesRes.success && rulesRes.data) {
            setReminders(reminderTogglesFromRules(rulesRes.data))
          }
        }
      } catch (error) {
        console.error('Error loading office:', error)
      } finally {
        setLoading(false)
      }
    }

    loadOffice()
  }, [api, supabase])

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }))
  }

  const handleSave = async () => {
    if (!office) return

    setSaving(true)
    try {
      const response = await api.updateOffice(office.id, formData)
      if (response.success) {
        setSaved(true)
        setTimeout(() => setSaved(false), 3000)
      }
    } catch (error) {
      console.error('Error saving settings:', error)
    } finally {
      setSaving(false)
    }
  }

  const toggleReminder = (type: ReminderType) => {
    setReminders((prev) => ({ ...prev, [type]: !prev[type] }))
  }

  const toggleNotification = (key: NotifKey) => {
    setNotifications((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const handleSaveNotifications = async () => {
    if (!office) return

    setSavingNotifications(true)
    try {
      const response = await api.updateOffice(office.id, notifications)
      if (response.success) {
        setNotificationsSaved(true)
        setTimeout(() => setNotificationsSaved(false), 3000)
      }
    } catch (error) {
      console.error('Error saving notifications:', error)
    } finally {
      setSavingNotifications(false)
    }
  }

  const handleSaveReminders = async () => {
    if (!office) return

    setSavingReminders(true)
    try {
      const rules: ReminderRule[] = rulesFromReminderToggles(reminders)
      const response = await api.updateReminderRules(office.id, rules)
      if (response.success) {
        setRemindersSaved(true)
        setTimeout(() => setRemindersSaved(false), 3000)
      }
    } catch (error) {
      console.error('Error saving reminders:', error)
    } finally {
      setSavingReminders(false)
    }
  }

  if (loading) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-600">Cargando configuración...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <PageHeader title="Configuración" subtitle="Personaliza tu asistente de WhatsApp" />


      {/* Save Notification */}
      {saved && (
        <div className="p-4 bg-green-100 border border-green-300 rounded-xl">
          <p className="text-sm text-green-800">
            Configuración guardada correctamente
          </p>
        </div>
      )}

      {/* General Settings */}
      <Card>
        <CardHeader>
          <SectionHeader
            icon={Settings}
            title="General"
            subtitle="Identidad y voz de tu asistente"
          />
        </CardHeader>
        <CardBody className="space-y-5">
          <Input
            label="Nombre del asistente"
            name="assistant_name"
            placeholder="Mi asistente"
            value={formData.assistant_name}
            onChange={handleChange}
            helpText="Este nombre aparecerá en los mensajes a pacientes"
          />

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Tono de conversación
            </label>
            <select
              name="tone"
              value={formData.tone}
              onChange={handleChange}
              className="input-field"
            >
              <option value="formal">De usted · formal</option>
              <option value="informal">De tú · cercano</option>
            </select>
            <p className="text-xs text-gray-500 mt-1">
              Elige cómo se comunica el asistente con tus pacientes
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Instrucciones personalizadas
            </label>
            <textarea
              name="custom_prompt"
              value={formData.custom_prompt}
              onChange={handleChange}
              placeholder="Escribe instrucciones personalizadas para el asistente..."
              rows={6}
              className="input-field resize-none"
            />
            <p className="text-xs text-gray-500 mt-1">
              Proporciona instrucciones específicas que el asistente debe seguir
            </p>
          </div>

          <Button
            onClick={handleSave}
            isLoading={saving}
            className="gap-2"
          >
            <Save size={16} />
            Guardar cambios
          </Button>
        </CardBody>
      </Card>

      {/* Reminders */}
      <Card>
        <CardHeader>
          <SectionHeader
            icon={Bell}
            title="Recordatorios automáticos"
            subtitle="Elige qué recordatorios envía el asistente por WhatsApp"
          />
        </CardHeader>
        <CardBody className="space-y-4">
          {remindersSaved && (
            <div className="p-3 bg-green-100 border border-green-300 rounded-xl">
              <p className="text-sm text-green-800">Recordatorios guardados correctamente</p>
            </div>
          )}

          <div className="space-y-2">
            {REMINDER_DEFS.map((reminder) => {
              const enabled = reminders[reminder.type]
              return (
                <button
                  key={reminder.type}
                  type="button"
                  onClick={() => toggleReminder(reminder.type)}
                  className={`w-full flex items-center gap-3 p-3 rounded-xl border text-left transition-colors ${
                    enabled ? 'border-primary-200 bg-primary-50' : 'border-gray-200 bg-gray-50'
                  }`}
                >
                  <span
                    className={`w-6 h-6 rounded flex items-center justify-center border-2 transition-colors flex-shrink-0 ${
                      enabled ? 'bg-primary-600 border-primary-600 text-white' : 'bg-white border-gray-300'
                    }`}
                  >
                    {enabled && (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                  <span>
                    <span className={`block text-sm font-medium ${enabled ? 'text-gray-900' : 'text-gray-500'}`}>
                      {reminder.label}
                    </span>
                    <span className="block text-xs text-gray-500">{reminder.description}</span>
                  </span>
                </button>
              )
            })}
          </div>

          <Button onClick={handleSaveReminders} isLoading={savingReminders} className="gap-2">
            <Save size={16} />
            Guardar recordatorios
          </Button>
        </CardBody>
      </Card>

      {/* Doctor Notifications */}
      <Card>
        <CardHeader>
          <SectionHeader
            icon={BellRing}
            title="Notificaciones al doctor"
            subtitle="Elige de qué eventos quieres que el asistente te avise por WhatsApp"
          />
        </CardHeader>
        <CardBody className="space-y-4">
          {notificationsSaved && (
            <div className="p-3 bg-green-100 border border-green-300 rounded-xl">
              <p className="text-sm text-green-800">Notificaciones guardadas correctamente</p>
            </div>
          )}

          <div className="space-y-2">
            {NOTIFICATION_DEFS.map((notif) => {
              const enabled = notifications[notif.key]
              return (
                <button
                  key={notif.key}
                  type="button"
                  onClick={() => toggleNotification(notif.key)}
                  className={`w-full flex items-center gap-3 p-3 rounded-xl border text-left transition-colors ${
                    enabled ? 'border-primary-200 bg-primary-50' : 'border-gray-200 bg-gray-50'
                  }`}
                >
                  <span
                    className={`w-6 h-6 rounded flex items-center justify-center border-2 transition-colors flex-shrink-0 ${
                      enabled ? 'bg-primary-600 border-primary-600 text-white' : 'bg-white border-gray-300'
                    }`}
                  >
                    {enabled && (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                  <span>
                    <span className={`block text-sm font-medium ${enabled ? 'text-gray-900' : 'text-gray-500'}`}>
                      {notif.label}
                    </span>
                    <span className="block text-xs text-gray-500">{notif.description}</span>
                  </span>
                </button>
              )
            })}
          </div>

          <Button onClick={handleSaveNotifications} isLoading={savingNotifications} className="gap-2">
            <Save size={16} />
            Guardar notificaciones
          </Button>
        </CardBody>
      </Card>

      {/* WhatsApp Status */}
      <Card>
        <CardHeader>
          <SectionHeader
            icon={Zap}
            title="Estado de WhatsApp"
            subtitle="Conexión y control del asistente"
          />
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl border border-gray-200">
            <div>
              <p className="font-medium text-gray-900">Número de WhatsApp</p>
              <p className="text-sm text-gray-600 mt-1">
                {office?.whatsapp_phone || 'Sin configurar'}
              </p>
            </div>
            <div
              className={`w-3 h-3 rounded-full ${
                office?.whatsapp_phone ? 'bg-green-500' : 'bg-gray-400'
              }`}
            />
          </div>

          <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl border border-gray-200">
            <div>
              <p className="font-medium text-gray-900">Estado del bot</p>
              <p className="text-sm text-gray-600 mt-1">
                {office?.is_active
                  ? 'Bot activo y respondiendo'
                  : 'Bot en pausa'}
              </p>
            </div>
            <div
              className={`w-3 h-3 rounded-full ${
                office?.is_active
                  ? 'bg-green-500 animate-pulse'
                  : 'bg-gray-400'
              }`}
            />
          </div>
        </CardBody>
      </Card>

      {/* Integration Info */}
      <Card>
        <CardHeader>
          <SectionHeader
            icon={Globe}
            title="Integraciones"
            subtitle="Conecta tu calendario y otras herramientas"
            soon
          />
        </CardHeader>
        <CardBody className="space-y-4">
          <p className="text-sm text-gray-600">
            Conecta Google Calendar para sincronizar tus citas automáticamente
          </p>
          <Button variant="secondary" disabled>
            Conectar Google Calendar
          </Button>
        </CardBody>
      </Card>

      {/* Schedules */}
      <Card>
        <CardHeader>
          <SectionHeader
            icon={Clock}
            title="Horarios de atención"
            subtitle="Disponibilidad semanal. El bot solo agenda dentro de estos bloques."
            soon
          />
        </CardHeader>
        <CardBody className="space-y-4">
          <p className="text-sm text-gray-600">
            Por ahora puedes configurar tus horarios durante el alta de tu consultorio.
            La edición desde aquí estará disponible pronto.
          </p>
          <div className="space-y-3 opacity-60 pointer-events-none select-none" aria-hidden="true">
            {['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'].map(
              (day) => (
                <div key={day} className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <label className="w-24 font-medium text-gray-900 text-sm">
                    {day}
                  </label>
                  <input type="time" className="input-field flex-1 min-w-0 sm:flex-none sm:w-32" disabled />
                  <span className="text-gray-500">-</span>
                  <input type="time" className="input-field flex-1 min-w-0 sm:flex-none sm:w-32" disabled />
                </div>
              )
            )}
          </div>
          <Button variant="secondary" className="w-full" disabled>
            Guardar horarios
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}
