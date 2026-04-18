import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts'

const COLORS = ['#10b981', '#f59e0b', '#ef4444', '#3b82f6', '#8b5cf6'];

const TrendPanel = () => {
  const [trends, setTrends] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchTrends = async () => {
      try {
        const response = await api.get('/api/trends')
        setTrends(response.data)
      } catch (error) {
        console.error("Error fetching trends:", error)
      } finally {
        setLoading(false)
      }
    }
    fetchTrends()
  }, [])

  if (loading) return <div className="p-8 text-center">Loading analytics...</div>
  if (!trends) return <div className="p-8 text-center text-red-500">Could not load analytics.</div>

  const severityData = trends.severity_trends.map(t => ({
    name: t.severity_label,
    value: t.count
  }))

  const categoryData = trends.category_trends.map(t => ({
    name: t.category,
    count: t.count
  })).sort((a, b) => b.count - a.count)

  const totalEvents = categoryData.reduce((sum, item) => sum + item.count, 0)
  const highAlerts = severityData.find(s => s.name === 'HIGH')?.value || 0

  return (
    <div className="max-w-6xl mx-auto p-6 bg-gray-50 min-h-screen">
      <Link to="/" className="text-blue-500 hover:underline mb-6 inline-block">&larr; Back to Map</Link>
      
      <h1 className="text-3xl font-bold mb-8">Disaster Intelligence Trends</h1>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
        <div className="bg-white p-6 rounded-lg shadow-sm border-l-4 border-blue-500">
          <p className="text-sm text-gray-500 uppercase font-semibold">Active Events</p>
          <p className="text-4xl font-bold">{totalEvents}</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow-sm border-l-4 border-red-500">
          <p className="text-sm text-gray-500 uppercase font-semibold">Critical (HIGH) Alerts</p>
          <p className="text-4xl font-bold text-red-600">{highAlerts}</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow-sm border-l-4 border-green-500">
          <p className="text-sm text-gray-500 uppercase font-semibold">Most Active</p>
          <p className="text-2xl font-bold">{categoryData[0]?.name || 'N/A'}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Category Bar Chart */}
        <div className="bg-white p-6 rounded-lg shadow-sm">
          <h2 className="text-xl font-bold mb-6">Events by Category</h2>
          <div className="h-80 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={categoryData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Severity Pie Chart */}
        <div className="bg-white p-6 rounded-lg shadow-sm">
          <h2 className="text-xl font-bold mb-6">Severity Distribution</h2>
          <div className="h-80 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={severityData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                  outerRadius={100}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {severityData.map((entry, index) => (
                    <Cell 
                      key={`cell-${index}`} 
                      fill={entry.name === 'HIGH' ? '#ef4444' : entry.name === 'MODERATE' ? '#f59e0b' : '#10b981'} 
                    />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  )
}

export default TrendPanel
