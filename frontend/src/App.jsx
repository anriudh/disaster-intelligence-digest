import React from 'react'
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom'
import Map from './components/Map'
import EventDetail from './components/EventDetail'
import TrendPanel from './components/TrendPanel'

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-gray-50 flex flex-col">
        {/* Navigation */}
        <nav className="bg-slate-900 text-white shadow-lg z-[2000]">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <div className="flex items-center">
                <Link to="/" className="flex items-center space-x-2">
                  <span className="text-xl font-bold tracking-tight">Disaster Intelligence Digest</span>
                </Link>
              </div>
              <div className="flex space-x-4">
                <Link to="/" className="hover:bg-slate-800 px-3 py-2 rounded-md text-sm font-medium transition">Map</Link>
                <Link to="/trends" className="hover:bg-slate-800 px-3 py-2 rounded-md text-sm font-medium transition">Analytics</Link>
              </div>
            </div>
          </div>
        </nav>

        {/* Main Content */}
        <main className="flex-grow">
          <Routes>
            <Route path="/" element={<Map />} />
            <Route path="/events/:id" element={<EventDetail />} />
            <Route path="/trends" element={<TrendPanel />} />
          </Routes>
        </main>
      </div>
    </Router>
  )
}

export default App
