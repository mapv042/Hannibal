'use client'

import React, { useState, useEffect } from 'react'
import { useApi } from '@/lib/api'
import { createBrowserSupabaseClient } from '@/lib/supabase'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Settings, Save, Globe, Zap } from 'lucide-react'
import type { Office } from '@/lib/supabase'

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
  const api = useApi()
  const supabase = createBrowserSupabaseClient()

  useEffect(() => {
    const loadOffice = async () => {
      try {
        const {
          data: { user },
        } = await supabase.auth.getUser()

        if (!user) return

        const response = await api.getOffice(user.id)
        if (response.success && response.data) {
          setOffice(response.data)
          setFormData({
            assistant_name: response.data.assistant_name,
            tone: response.data.tone,
            custom_prompt: response.data.custom_prompt,
          })
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

  if (loading) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-600">Loading settings...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-600 mt-1">Customize your WhatsApp assistant</p>
      </div>

      {/* Save Notification */}
      {saved && (
        <div className="p-4 bg-green-100 border border-green-300 rounded-lg">
          <p className="text-sm text-green-800">
            Settings saved successfully
          </p>
        </div>
      )}

      {/* General Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Settings size={20} className="text-primary-600" />
            <h2 className="text-xl font-semibold text-gray-900">
              General Settings
            </h2>
          </div>
        </CardHeader>
        <CardBody className="space-y-5">
          <Input
            label="Assistant Name"
            name="assistant_name"
            placeholder="My Assistant"
            value={formData.assistant_name}
            onChange={handleChange}
            helpText="This name will appear in messages to patients"
          />

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Conversation Tone
            </label>
            <select
              name="tone"
              value={formData.tone}
              onChange={handleChange}
              className="input-field"
            >
              <option value="formal">Formal (professional)</option>
              <option value="informal">Informal (friendly)</option>
            </select>
            <p className="text-xs text-gray-500 mt-1">
              Choose how the assistant communicates with your patients
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Custom Instructions
            </label>
            <textarea
              name="custom_prompt"
              value={formData.custom_prompt}
              onChange={handleChange}
              placeholder="Write custom instructions for the assistant..."
              rows={6}
              className="input-field resize-none"
            />
            <p className="text-xs text-gray-500 mt-1">
              Provide specific instructions the assistant should follow
            </p>
          </div>

          <Button
            onClick={handleSave}
            isLoading={saving}
            className="gap-2"
          >
            <Save size={16} />
            Save Changes
          </Button>
        </CardBody>
      </Card>

      {/* WhatsApp Status */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Zap size={20} className="text-primary-600" />
            <h2 className="text-xl font-semibold text-gray-900">
              WhatsApp Status
            </h2>
          </div>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg border border-gray-200">
            <div>
              <p className="font-medium text-gray-900">WhatsApp Number</p>
              <p className="text-sm text-gray-600 mt-1">
                {office?.whatsapp_number || 'Not configured'}
              </p>
            </div>
            <div
              className={`w-3 h-3 rounded-full ${
                office?.whatsapp_number ? 'bg-green-500' : 'bg-gray-400'
              }`}
            />
          </div>

          <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg border border-gray-200">
            <div>
              <p className="font-medium text-gray-900">Bot Status</p>
              <p className="text-sm text-gray-600 mt-1">
                {office?.bot_status === 'active'
                  ? 'Bot active and responding'
                  : 'Bot paused'}
              </p>
            </div>
            <div
              className={`w-3 h-3 rounded-full ${
                office?.bot_status === 'active'
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
          <div className="flex items-center gap-2">
            <Globe size={20} className="text-primary-600" />
            <h2 className="text-xl font-semibold text-gray-900">
              Integrations
            </h2>
          </div>
        </CardHeader>
        <CardBody className="space-y-4">
          <p className="text-sm text-gray-600">
            Connect Google Calendar to automatically sync your appointments
          </p>
          <Button variant="secondary">
            Connect Google Calendar
          </Button>
        </CardBody>
      </Card>

      {/* Schedules */}
      <Card>
        <CardHeader>
          <h2 className="text-xl font-semibold text-gray-900">
            Availability Schedules
          </h2>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="space-y-3">
            {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map(
              (day) => (
                <div key={day} className="flex items-center gap-4">
                  <label className="w-24 font-medium text-gray-900 text-sm">
                    {day}
                  </label>
                  <input
                    type="time"
                    className="input-field w-32"
                    placeholder="09:00"
                  />
                  <span className="text-gray-500">-</span>
                  <input
                    type="time"
                    className="input-field w-32"
                    placeholder="17:00"
                  />
                </div>
              )
            )}
          </div>
          <Button variant="secondary" className="w-full">
            Save Schedules
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}
