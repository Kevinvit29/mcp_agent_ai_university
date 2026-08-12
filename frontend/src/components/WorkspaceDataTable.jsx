import { useEffect, useMemo, useState } from 'react'


function valueForSort(value) {
  const text = String(value ?? '').trim()
  const numeric = Number(text.replace(/,/g, ''))
  if (text !== '' && Number.isFinite(numeric)) return { type: 'number', value: numeric }
  return { type: 'text', value: text.toLocaleLowerCase() }
}


function csvEscape(value) {
  const text = String(value ?? '')
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}


export default function WorkspaceDataTable({
  title,
  description,
  columns,
  rows,
  sourceLabel = 'Stored source data',
  externalQuery = ''
}) {
  const safeColumns = useMemo(() => (Array.isArray(columns) && columns.length ? columns : ['No', 'Information']), [columns])
  const safeRows = useMemo(() => (Array.isArray(rows) ? rows : []), [rows])
  const [columnFilter, setColumnFilter] = useState('__all__')
  const [sortKey, setSortKey] = useState('')
  const [sortDirection, setSortDirection] = useState('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)

  const query = String(externalQuery || '').trim().toLowerCase()
  const filteredRows = useMemo(() => {
    if (!query) return safeRows
    return safeRows.filter((row) => {
      const columnsToSearch = columnFilter === '__all__' ? safeColumns : [columnFilter]
      return columnsToSearch.some((column) => String(row?.[column] ?? '').toLowerCase().includes(query))
    })
  }, [safeRows, safeColumns, query, columnFilter])

  const sortedRows = useMemo(() => {
    if (!sortKey) return filteredRows
    const factor = sortDirection === 'asc' ? 1 : -1
    return [...filteredRows].sort((left, right) => {
      const a = valueForSort(left?.[sortKey])
      const b = valueForSort(right?.[sortKey])
      if (a.type === 'number' && b.type === 'number') return (a.value - b.value) * factor
      return String(a.value).localeCompare(String(b.value), undefined, { numeric: true, sensitivity: 'base' }) * factor
    })
  }, [filteredRows, sortKey, sortDirection])

  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const visibleRows = sortedRows.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  useEffect(() => { setPage(1) }, [query, columnFilter, sortKey, sortDirection, pageSize, safeRows.length])

  const toggleSort = (column) => {
    if (sortKey === column) setSortDirection((direction) => direction === 'asc' ? 'desc' : 'asc')
    else {
      setSortKey(column)
      setSortDirection('asc')
    }
  }

  const downloadCsv = () => {
    const lines = [safeColumns.map(csvEscape).join(',')]
    sortedRows.forEach((row) => lines.push(safeColumns.map((column) => csvEscape(row?.[column])).join(',')))
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${String(title || 'knowledge-table').replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase() || 'knowledge-table'}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  if (!safeRows.length) return null

  return (
    <section className="workspace-data-table">
      <header className="workspace-data-heading">
        <div>
          <p className="eyebrow">{sourceLabel}</p>
          <h3>{title}</h3>
          {description && <p>{description}</p>}
        </div>
        <button type="button" className="export-table-button" onClick={downloadCsv}>Export visible data</button>
      </header>

      <div className="data-table-summary" aria-label="Table summary">
        <span><strong>{safeRows.length}</strong> stored rows</span>
        <span><strong>{filteredRows.length}</strong> matching rows</span>
        <span><strong>{safeColumns.length}</strong> columns</span>
        <span>Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong></span>
      </div>

      <div className="data-table-controls">
        <label>
          <span>Search column</span>
          <select value={columnFilter} onChange={(event) => setColumnFilter(event.target.value)}>
            <option value="__all__">All columns</option>
            {safeColumns.map((column) => <option key={column} value={column}>{column}</option>)}
          </select>
        </label>
        <label>
          <span>Sort by</span>
          <select value={sortKey} onChange={(event) => setSortKey(event.target.value)}>
            <option value="">Original order</option>
            {safeColumns.map((column) => <option key={column} value={column}>{column}</option>)}
          </select>
        </label>
        <label>
          <span>Direction</span>
          <select value={sortDirection} disabled={!sortKey} onChange={(event) => setSortDirection(event.target.value)}>
            <option value="asc">A → Z / Low → High</option>
            <option value="desc">Z → A / High → Low</option>
          </select>
        </label>
        <label>
          <span>Rows per page</span>
          <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
            <option value={10}>10</option>
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
      </div>

      <div className="table-scroll workspace-table-scroll">
        {visibleRows.length === 0 ? (
          <div className="empty-docs"><strong>No matching rows.</strong><br />Clear the workspace search or try another column.</div>
        ) : (
          <table className="knowledge-table enhanced-knowledge-table">
            <thead>
              <tr>{safeColumns.map((column) => <th key={column}><button type="button" onClick={() => toggleSort(column)}>{column}{sortKey === column ? (sortDirection === 'asc' ? ' ↑' : ' ↓') : ''}</button></th>)}</tr>
            </thead>
            <tbody>
              {visibleRows.map((row, rowIndex) => (
                <tr key={`${currentPage}-${rowIndex}`}>
                  {safeColumns.map((column) => <td key={column} title={String(row?.[column] ?? '')}>{String(row?.[column] ?? '—')}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <footer className="data-table-pagination">
        <button type="button" onClick={() => setPage(1)} disabled={currentPage === 1}>First</button>
        <button type="button" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={currentPage === 1}>Previous</button>
        <span>Showing {visibleRows.length ? ((currentPage - 1) * pageSize) + 1 : 0}–{Math.min(currentPage * pageSize, sortedRows.length)} of {sortedRows.length}</span>
        <button type="button" onClick={() => setPage((value) => Math.min(totalPages, value + 1))} disabled={currentPage === totalPages}>Next</button>
        <button type="button" onClick={() => setPage(totalPages)} disabled={currentPage === totalPages}>Last</button>
      </footer>
    </section>
  )
}
