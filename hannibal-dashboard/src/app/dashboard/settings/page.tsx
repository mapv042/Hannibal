'use client'

import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'next/navigation'
import { useApi, type ReminderRule } from '@/lib/api'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { ASSISTANT_GENDERS } from '@/lib/constants/catalogs'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { PageHeader } from '@/components/ui/PageHeader'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { GoogleCalendarIntegration } from '@/components/settings/GoogleCalendarIntegration'
import { BotStatusBadge } from '@/components/coexistence/BotStatusBadge'
import { OfficeProfileSections } from '@/components/settings/OfficeProfileSections'
import { Settings, Save, Globe, Zap, Bell, BellRing, LucideIcon } from 'lucide-react'
import type { Office } from '@/lib/supabase'

type NotifKey =
  | 'notify_new_appointment'
  | 'notify_cancellation'
  | 'notify_new_patient'
  | 'notify_unconfirmed'
  | 'notify_arrival'
  | 'notify_reschedule'

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
    label: 'Resumen del día',
    description: 'Una hora antes de tu primer horario: tus citas de hoy, cuáles faltan por confirmar, urgencias pendientes y horarios libres.',
  },
  {
    key: 'notify_arrival',
    label: 'Llegada del paciente',
    description: 'Te avisamos en cuanto el paciente responde que ya llegó o que viene en camino.',
  },
  {
    key: 'notify_reschedule',
    label: 'Cita movida',
    description: 'Te avisamos cuando un paciente cambia su cita de horario.',
  },
]

/** Idea 12: the doctor decides which of these go out, never what they say. */
const META_FIXED_TEXT_NOTE =
  'El texto de estos avisos está aprobado por WhatsApp y no se puede editar. ' +
  'Aquí decides cuáles se mandan, no qué dicen.' 
import {
  REMINDER_DEFS,
  DEFAULT_REMINDER_TOGGLES,
  reminderTogglesFromRules,
  rulesFromReminderToggles,
  type ReminderToggles,
  type ReminderType,
} from '@/components/onboarding/StepSchedule'

function SectionHeader({
  icon: Icon,
  title,
  subtitle,
}: {
  icon: LucideIcon
  title: string
  subtitle?: string
}) {
  return (
    <div className="flex items-center gap-3.5">
      <div className="w-10 h-10 rounded-[10px] bg-primary-50 flex items-center justify-center flex-shrink-0">
        <Icon size={20} className="text-primary-700" />
      </div>
      <div>
        <h2 className="text-base font-semibold tracking-tight text-gray-900">{title}</h2>
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
    assistant_gender: 'femenino',
    custom_prompt: '',
    welcome_message: '',
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
    notify_arrival: true,
    notify_reschedule: true,
  })
  const [savingNotifications, setSavingNotifications] = useState(false)
  const [notificationsSaved, setNotificationsSaved] = useState(false)
  const api = useApi()
  const supabase = createBrowserSupabaseClient()

  // Set by the Google OAuth callback when the flow started from this page.
  const searchParams = useSearchParams()
  const gcalNotice = searchParams.get('gcal')

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
            assistant_gender: officeData.assistant_gender || 'femenino',
            custom_prompt: officeData.custom_prompt || '',
            welcome_message: officeData.welcome_message || '',
          })

          setNotifications({
            notify_new_appointment: officeData.notify_new_appointment,
            notify_cancellation: officeData.notify_cancellation,
            notify_new_patient: officeData.notify_new_patient,
            notify_unconfirmed: officeData.notify_unconfirmed,
            notify_arrival: officeData.notify_arrival,
            notify_reschedule: officeData.notify_reschedule,
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
      // Mapped field by field on purpose: the form calls it `tone` while the
      // API field is `assistant_tone`, and posting the raw form meant Pydantic
      // silently dropped it — the tone selector never saved anything.
      const response = await api.updateOffice(office.id, {
        assistant_name: formData.assistant_name,
        assistant_tone: formData.tone,
        assistant_gender: formData.assistant_gender,
        custom_prompt: formData.custom_prompt,
        // Empty string clears a previous greeting.
        welcome_message: formData.welcome_message.trim(),
      })
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
              Cómo habla de sí mismo
            </label>
            <select
              name="assistant_gender"
              value={formData.assistant_gender}
              onChange={handleChange}
              className="input-field"
            >
              {ASSISTANT_GENDERS.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.label} · {g.description}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              Para que concuerde bien al referirse a sí mismo, según el nombre que le pusiste
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Mensaje de bienvenida
            </label>
            <textarea
              name="welcome_message"
              value={formData.welcome_message}
              onChange={handleChange}
              placeholder="Hola, gracias por escribir al consultorio. ¿En qué te puedo ayudar?"
              rows={3}
              maxLength={2000}
              className="input-field resize-none"
            />
            <p className="text-xs text-gray-500 mt-1">
              Con esto saluda el asistente a quien escribe por primera vez. Déjalo vacío para un saludo normal.
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

      {office && (
        <OfficeProfileSections office={office} onOfficeUpdated={setOffice} />
      )}

      {/* Reminders */}
      <Card>
        <CardHeader>
          <SectionHeader
            icon={Bell}
            title="Recordatorios automáticos"
            subtitle="Elige cuáles envía el asistente. El texto lo aprueba WhatsApp y no se edita."
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
            subtitle={`Elige de qué eventos quieres que te avise. ${META_FIXED_TEXT_NOTE}`}
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

          {office && (
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-200 space-y-2">
              <p className="font-medium text-gray-900">Estado del asistente</p>
              <BotStatusBadge officeId={office.id} />
              <p className="text-xs text-gray-500">
                En pausa, los mensajes de tus pacientes se guardan pero el asistente no responde.
              </p>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Integration Info */}
      <Card>
        <CardHeader>
          <SectionHeader
            icon={Globe}
            title="Google Calendar"
            subtitle="Sincroniza las citas con tu calendario"
          />
        </CardHeader>
        <CardBody>
          {gcalNotice === 'success' && (
            <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-xl">
              <p className="text-sm text-green-800">Google Calendar se conectó correctamente.</p>
            </div>
          )}
          {gcalNotice === 'error' && (
            <div className="mb-4 p-3 bg-red-100 border border-red-300 rounded-xl">
              <p className="text-sm text-red-800">
                No se pudo conectar Google Calendar. Intenta de nuevo.
              </p>
            </div>
          )}
          <GoogleCalendarIntegration
            connected={!!office?.google_calendar_connected}
            onDisconnected={() =>
              setOffice((prev) => (prev ? { ...prev, google_calendar_connected: false } : prev))
            }
          />
        </CardBody>
      </Card>

    </div>
  )
}
