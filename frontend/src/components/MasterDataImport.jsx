import { useEffect, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'
const IMPORTANT_FIELDS = [
  ['student_id', 'Student ID', true],
  ['full_name', 'Full name', true],
  ['program_code', 'Program code', true],
  ['program_name', 'Program name', true],
  ['gpa', 'GPA', false],
  ['attendance_rate', 'Attendance rate', false],
  ['email', 'Email', false],
  ['academic_status', 'Academic status', false]
]

export default function MasterDataImport({ apiFetch, onCompleted }) {
  const [selectedFile, setSelectedFile] = useState(null)
  const [batch, setBatch] = useState(null)
  const [mapping, setMapping] = useState({})
  const [imports, setImports] = useState([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const summary = batch?.validation_summary || {}
  const canConfirm = batch?.status === 'staged' && summary.valid === true
  const loadImports = async () => {
    const response = await apiFetch(`${API_BASE}/admin/master-data/imports?limit=20`)
    const data = await response.json()
    if (!response.ok || !data?.success) throw new Error(data?.detail || 'Could not load import history.')
    setImports(data.imports || [])
  }

  useEffect(() => { loadImports().catch(() => {}) }, [])

  const preview = async (file = selectedFile, requestedMapping = null) => {
    if (!file) return
    setBusy(true)
    setMessage('Checking columns, values, duplicates, and both databases. No live records are being changed.')
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('mapping', JSON.stringify(requestedMapping || {}))
      const response = await apiFetch(`${API_BASE}/admin/master-data/imports/preview`, { method: 'POST', body: form })
      const data = await response.json()
      if (!response.ok || !data?.success) throw new Error(data?.detail || 'Could not create an import preview.')
      setBatch(data.batch)
      setMapping(data.batch.column_mapping || {})
      setMessage('Preview ready. Live student records are unchanged until you explicitly confirm.')
      await loadImports()
    } catch (error) {
      setBatch(null)
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  const chooseFile = (event) => {
    const file = event.target.files?.[0] || null
    setSelectedFile(file)
    setBatch(null)
    setMapping({})
    setMessage('')
    if (file) preview(file, {})
  }

  const rebuildPreview = () => preview(selectedFile, mapping)

  const confirmImport = async () => {
    if (!canConfirm || !window.confirm(`Import ${summary.row_count} student row(s) into both databases? A rollback snapshot will be kept.`)) return
    setBusy(true)
    setMessage('Synchronizing PostgreSQL and MongoDB, then verifying every imported student…')
    try {
      const response = await apiFetch(`${API_BASE}/admin/master-data/imports/${batch.import_id}/confirm`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true })
      })
      const data = await response.json()
      if (!response.ok || !data?.success) throw new Error(data?.detail || 'Import failed.')
      setBatch(current => ({ ...current, ...data.batch }))
      setMessage(`Import complete: ${data.batch.inserted_count} added, ${data.batch.updated_count} updated, and both databases verified.`)
      await loadImports()
      onCompleted?.()
    } catch (error) {
      setMessage(error.message)
      await loadImports().catch(() => {})
    } finally {
      setBusy(false)
    }
  }

  const rollback = async (item = batch) => {
    if (!item?.import_id || item.status !== 'committed' || !window.confirm(`Roll back ${item.filename}? This restores the snapshot from before that import.`)) return
    setBusy(true)
    setMessage('Restoring the pre-import snapshot in both databases…')
    try {
      const response = await apiFetch(`${API_BASE}/admin/master-data/imports/${item.import_id}/rollback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true })
      })
      const data = await response.json()
      if (!response.ok || !data?.success) throw new Error(data?.detail || 'Rollback failed.')
      if (batch?.import_id === item.import_id) setBatch(current => ({ ...current, ...data.batch }))
      setMessage(`Rollback complete. ${data.restored_students} student record(s) restored.`)
      await loadImports()
      onCompleted?.()
    } catch (error) {
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="master-import-pane">
      <section className="knowledge-upload-card master-import-card">
        <div className="upload-card-heading"><div><p className="eyebrow">Student master data</p><h3>Safe CSV / Excel import</h3></div><span className="upload-agent-badge">Admin only</span></div>
        <p>This is separate from knowledge files. It previews first, then updates MongoDB and PostgreSQL together only after confirmation.</p>
        <label className="file-picker-label">
          <input type="file" accept=".csv,.xlsx,.xls" onChange={chooseFile} />
          <span>{selectedFile?.name || 'Choose student CSV or Excel file'}</span>
        </label>
      </section>

      {message && <div className={`upload-result-card ${summary.valid === false ? 'import-error' : ''}`}><strong>Master-data status</strong><p>{message}</p></div>}
      {busy && <div className="upload-progress-card">Working safely. Do not close this page.</div>}

      {batch && <section className="master-preview-card">
        <div className="master-preview-heading">
          <div><p className="eyebrow">Import preview</p><h3>{batch.filename}</h3></div>
          <span className={`import-status ${batch.status}`}>{batch.status}</span>
        </div>
        <div className="import-stat-grid">
          <div><strong>{summary.row_count || 0}</strong><span>Rows</span></div>
          <div><strong>{summary.new_student_count || 0}</strong><span>New</span></div>
          <div><strong>{summary.existing_student_count || 0}</strong><span>Updates</span></div>
          <div className={summary.error_count ? 'bad' : ''}><strong>{summary.error_count || 0}</strong><span>Errors</span></div>
        </div>

        <details className="mapping-editor" open>
          <summary>Column mapping</summary>
          <div className="mapping-grid">
            {IMPORTANT_FIELDS.map(([field, label, required]) => <label key={field}><span>{label}{required ? ' *' : ''}</span><select value={mapping[field] || ''} onChange={(event) => setMapping(current => ({ ...current, [field]: event.target.value }))}><option value="">Not mapped</option>{(batch.source_columns || []).map(column => <option key={column} value={column}>{column}</option>)}</select></label>)}
          </div>
          <button type="button" className="secondary-file-button" disabled={busy} onClick={rebuildPreview}>Recheck this mapping</button>
        </details>

        <div className="master-preview-table-wrap"><table className="master-preview-table"><thead><tr><th>Row</th><th>Student</th><th>Name</th><th>Program</th><th>GPA</th><th>Check</th></tr></thead><tbody>{(batch.rows || []).slice(0, 10).map(row => { const record = row.canonical_data || {}; const errors = (row.issues || []).filter(item => item.severity === 'error'); return <tr key={row.row_number}><td>{row.row_number}</td><td>{record.student_id || '—'}</td><td>{record.full_name || '—'}</td><td>{record.program_name || '—'}</td><td>{record.gpa ?? '—'}</td><td className={errors.length ? 'cell-error' : ''}>{errors.length ? `${errors.length} error(s)` : 'Ready'}</td></tr>})}</tbody></table></div>
        {batch.preview_truncated && <small>Showing the first preview rows only. Every row will still be validated.</small>}
        <div className="master-import-actions">
          <button type="button" className="upload-primary-button" disabled={!canConfirm || busy} onClick={confirmImport}>{busy ? 'Working…' : 'Confirm synchronized import'}</button>
          {batch.status === 'committed' && <button type="button" className="rollback-button" disabled={busy} onClick={() => rollback(batch)}>Rollback this import</button>}
        </div>
      </section>}

      <section className="import-history-card">
        <div className="file-library-toolbar"><div><p className="eyebrow">Audit history</p><h3>Recent imports</h3></div><button type="button" className="refresh-library-button" onClick={loadImports}>Refresh</button></div>
        <div className="import-history-list">{imports.length === 0 ? <p>No student imports yet.</p> : imports.map(item => <article key={item.import_id}><div><strong>{item.filename}</strong><small>{item.row_count} row(s) · {item.status}</small></div>{item.status === 'committed' && <button type="button" className="rollback-link" onClick={() => rollback(item)}>Rollback</button>}</article>)}</div>
      </section>
    </div>
  )
}
