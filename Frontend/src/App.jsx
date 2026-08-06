import { useEffect, useState } from 'react'

const API_BASE = 'http://127.0.0.1:8000/api'

function App() {
  const [records, setRecords] = useState([])
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [physicians, setPhysicians] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [logContent, setLogContent] = useState('')

  const refreshLog = async () => {
    try {
      const response = await fetch(`${API_BASE}/export/log`)
      const payload = await response.json()
      setLogContent(payload.content || 'No log output yet.')
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    fetch(`${API_BASE}/records/`)
      .then((res) => res.json())
      .then((data) => setRecords(data))
      .catch((err) => console.error(err))

    refreshLog()
    const timer = window.setInterval(refreshLog, 3000)
    return () => window.clearInterval(timer)
  }, [])

  const handleSubmit = async (event) => {
    event.preventDefault()
    setLoading(true)
    setStatus('')

    try {
      const response = await fetch(`${API_BASE}/export/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_date: fromDate,
          to_date: toDate,
          physicians: physicians.split(',').map((name) => name.trim()).filter(Boolean),
          skip_analyzer: true,
        }),
      })

      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload.detail || 'Export request failed')
      }

      setStatus(`Export started. PID: ${payload.pid || 'n/a'}`)
      await refreshLog()
    } catch (err) {
      setStatus(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="app">
      <section className="panel">
        <h1>Commission Export Control</h1>
        <p>Use this form to send export dates and physician names to the backend, avoiding the Tkinter date picker.</p>

        <form onSubmit={handleSubmit} className="form">
          <label>
            From date
            <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} required />
          </label>
          <label>
            To date
            <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} required />
          </label>
          <label>
            Physicians (comma-separated)
            <input type="text" value={physicians} onChange={(event) => setPhysicians(event.target.value)} placeholder="Dr. Ahmed, Dr. Sara" />
          </label>
          <button type="submit" disabled={loading}>{loading ? 'Starting export...' : 'Start export'}</button>
        </form>

        {status ? <p className="status">{status}</p> : null}

        <h3>Recent export log</h3>
        <pre className="log-box">{logContent}</pre>
      </section>

      <section className="panel">
        <h2>Stored Records</h2>
        <table>
          <thead>
            <tr>
              <th>Doctor</th>
              <th>Service</th>
              <th>Amount</th>
              <th>Category</th>
            </tr>
          </thead>
          <tbody>
            {records.map((record) => (
              <tr key={record.id}>
                <td>{record.doctor_name}</td>
                <td>{record.service}</td>
                <td>{record.amount}</td>
                <td>{record.category}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  )
}

export default App
