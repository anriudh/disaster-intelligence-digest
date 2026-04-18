import React, { useEffect, useState } from 'react'
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import L from 'leaflet'
import api from '../api/client'
import { Link } from 'react-router-dom'

// Fix for default marker icons in Leaflet + React
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

const getMarkerColor = (severity) => {
  switch (severity) {
    case 'HIGH': return 'red';
    case 'MODERATE': return 'orange';
    case 'LOW': return 'green';
    default: return 'blue';
  }
}

const customIcon = (color) => new L.Icon({
  iconUrl: `https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-${color}.png`,
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

const Map = () => {
  const [events, setEvents] = useState([])
  const [filteredEvents, setFilteredEvents] = useState([])
  const [categories, setCategories] = useState([])
  const [selectedCategories, setSelectedCategories] = useState([])

  useEffect(() => {
    const fetchEvents = async () => {
      try {
        const response = await api.get('/api/events')
        const fetchedEvents = response.data.events
        setEvents(fetchedEvents)
        setFilteredEvents(fetchedEvents)
        
        const cats = [...new Set(fetchedEvents.map(e => e.category))]
        setCategories(cats)
        setSelectedCategories(cats)
      } catch (error) {
        console.error("Error fetching events:", error)
      }
    }
    fetchEvents()
  }, [])

  useEffect(() => {
    setFilteredEvents(
      events.filter(e => selectedCategories.includes(e.category))
    )
  }, [selectedCategories, events])

  const toggleCategory = (cat) => {
    if (selectedCategories.includes(cat)) {
      setSelectedCategories(selectedCategories.filter(c => c !== cat))
    } else {
      setSelectedCategories([...selectedCategories, cat])
    }
  }

  return (
    <div className="relative h-screen w-full">
      {/* Sidebar / Overlay for Filters */}
      <div className="absolute top-4 right-4 z-[1000] bg-white p-4 rounded shadow-md max-w-xs">
        <h3 className="font-bold mb-2">Categories</h3>
        <div className="space-y-1">
          {categories.map(cat => (
            <label key={cat} className="flex items-center space-x-2">
              <input 
                type="checkbox" 
                checked={selectedCategories.includes(cat)}
                onChange={() => toggleCategory(cat)}
              />
              <span>{cat}</span>
            </label>
          ))}
        </div>
      </div>

      <MapContainer center={[20, 0]} zoom={2} className="h-full w-full">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {filteredEvents.map(event => (
          <Marker 
            key={event.id} 
            position={[event.lat, event.lon]}
            icon={customIcon(getMarkerColor(event.severity_label))}
          >
            <Popup>
              <div className="p-1">
                <h4 className="font-bold">{event.title}</h4>
                <p className="text-sm text-gray-600">{event.category}</p>
                <p className={`text-sm font-semibold ${
                  event.severity_label === 'HIGH' ? 'text-red-600' : 
                  event.severity_label === 'MODERATE' ? 'text-orange-600' : 'text-green-600'
                }`}>
                  Severity: {event.severity_label}
                </p>
                <Link to={`/events/${event.id}`} className="text-blue-500 hover:underline mt-2 inline-block">
                  View Details
                </Link>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  )
}

export default Map
