import React, { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../api/client'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const EventDetail = () => {
  const { id } = useParams()
  const [event, setEvent] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchEventDetail = async () => {
      try {
        const response = await api.get(`/api/events/${id}`)
        setEvent(response.data)
      } catch (error) {
        console.error("Error fetching event detail:", error)
      } finally {
        setLoading(false)
      }
    }
    fetchEventDetail()
  }, [id])

  if (loading) return <div className="p-8 text-center">Loading event details...</div>
  if (!event) return <div className="p-8 text-center text-red-500">Event not found.</div>

  // Prepare SHAP data for chart
  const shapData = event.shap_values ? Object.entries(event.shap_values).map(([name, value]) => ({
    name: name.replace(/_/g, ' '),
    value: parseFloat(value.toFixed(4))
  })).sort((a, b) => Math.abs(b.value) - Math.abs(a.value)) : []

  const digest = event.gemini_digest || null

  return (
    <div className="max-w-5xl mx-auto p-6 bg-white min-h-screen">
      <Link to="/" className="text-blue-500 hover:underline mb-6 inline-block">&larr; Back to Map</Link>
      
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-3xl font-bold mb-2">{event.title}</h1>
          <div className="flex space-x-2">
            <span className="px-3 py-1 bg-gray-100 rounded-full text-sm font-medium">{event.category}</span>
            <span className={`px-3 py-1 rounded-full text-sm font-bold ${
              event.severity_label === 'HIGH' ? 'bg-red-100 text-red-700' : 
              event.severity_label === 'MODERATE' ? 'bg-orange-100 text-orange-700' : 'bg-green-100 text-green-700'
            }`}>
              Severity: {event.severity_label} ({ (event.severity_score * 100).toFixed(1) }%)
            </span>
          </div>
        </div>
        <div className="text-right text-sm text-gray-500">
          <p>ID: {event.id}</p>
          <p>Last Updated: {new Date(event.last_updated).toLocaleString()}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
        {/* Left Column: AI Digest */}
        <div className="md:col-span-2 space-y-8">
          <section>
            <h2 className="text-xl font-bold mb-4 border-b pb-2">Situation Report</h2>
            {digest ? (
              <div className="space-y-4">
                <div>
                  <h3 className="font-semibold text-gray-700">What Happened</h3>
                  <p className="text-gray-800 leading-relaxed">{digest.what_happened}</p>
                </div>
                <div>
                  <h3 className="font-semibold text-gray-700">Where</h3>
                  <p className="text-gray-800">{digest.where}</p>
                </div>
                <div>
                  <h3 className="font-semibold text-gray-700">Severity Rationale</h3>
                  <p className="text-gray-800 italic">{digest.severity_rationale}</p>
                </div>
                <div>
                  <h3 className="font-semibold text-gray-700">Agency Response</h3>
                  <p className="text-gray-800">{digest.agency_response}</p>
                </div>
                <div>
                  <h3 className="font-semibold text-gray-700">Outlook</h3>
                  <p className="text-gray-800">{digest.outlook}</p>
                </div>
              </div>
            ) : (
              <div className="p-4 bg-gray-50 rounded">
                <h3 className="font-semibold mb-2">Automated Summary</h3>
                <p className="text-gray-700">{event.nlp_summary || "No automated summary available for this level of severity."}</p>
              </div>
            )}
          </section>

          <section>
            <h2 className="text-xl font-bold mb-4 border-b pb-2">Key Entities</h2>
            <div className="flex flex-wrap gap-2">
              {event.keyphrases && event.keyphrases.map(([phrase, score]) => (
                <span key={phrase} className="px-3 py-1 bg-blue-50 text-blue-700 rounded border border-blue-100 text-sm">
                  {phrase}
                </span>
              ))}
            </div>
          </section>
        </div>

        {/* Right Column: Model Explainability & Metadata */}
        <div className="space-y-8">
          <section>
            <h2 className="text-xl font-bold mb-4 border-b pb-2">Model Rationale (SHAP)</h2>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={shapData} layout="vertical" margin={{ top: 5, right: 30, left: 40, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Bar dataKey="value">
                    {shapData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.value > 0 ? '#ef4444' : '#10b981'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="text-xs text-gray-500 mt-2">Red indicates features increasing severity score, green indicates decreasing.</p>
          </section>

          <section className="bg-gray-50 p-4 rounded">
            <h2 className="text-lg font-bold mb-3">Enrichment Data</h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between border-b pb-1">
                <span className="text-gray-600">GDACS Alert Level</span>
                <span className="font-semibold">{event.gdacs_alert_level || 'N/A'}</span>
              </div>
              <div className="flex justify-between border-b pb-1">
                <span className="text-gray-600">GDACS Score</span>
                <span className="font-semibold">{event.gdacs_alert_score || 'N/A'}</span>
              </div>
              <div className="flex justify-between border-b pb-1">
                <span className="text-gray-600">Pop. Exposure</span>
                <span className="font-semibold">{event.population_exposure?.toLocaleString() || 'N/A'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Sources</span>
                <span className="font-semibold">{event.source_count}</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

export default EventDetail
