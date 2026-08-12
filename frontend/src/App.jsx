import { useEffect, useMemo, useRef, useState } from 'react'
import './style.css'
import LoginPage from './LoginPage'
import WorkspaceDataTable from './components/WorkspaceDataTable'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

const STORAGE_EXPLANATIONS = {
  postgres: {
    label: 'PostgreSQL knowledge record',
    plain: 'Stored as a structured record with searchable text and rows. Best for clear tables, filters, auditing, and reliable record lookup.'
  },
  mongodb: {
    label: 'MongoDB knowledge clone',
    plain: 'Stored as a flexible document-style record. Best for nested content, extracted PDF chunks, and retrieval from varied file structures.'
  },
  excel: {
    label: 'Excel-agent structured store',
    plain: 'Stored in spreadsheet-style form. Best for sheets, columns, totals, comparisons, and row-by-row analysis.'
  }
}

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [accessToken, setAccessToken] = useState('')
  const [messages, setMessages] = useState([])
  const [sessions, setSessions] = useState([])
  const [input, setInput] = useState('')
  const [userRole, setUserRole] = useState('student')
  const [studentId, setStudentId] = useState('')
  const [advisorId, setAdvisorId] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [userName, setUserName] = useState('')
  const [language, setLanguage] = useState('en')
  const [loading, setLoading] = useState(false)
  const [uploadMessage, setUploadMessage] = useState('')
  const [documents, setDocuments] = useState([])
  const [uploading, setUploading] = useState(false)
  const [selectedDocument, setSelectedDocument] = useState(null)
  const [documentLoading, setDocumentLoading] = useState(false)
  const [tablePageDocument, setTablePageDocument] = useState(null)
  const [activeTableTab, setActiveTableTab] = useState('overview')
  const [tableSearch, setTableSearch] = useState('')
  const [advisorSubjects, setAdvisorSubjects] = useState([])
  const [selectedSubjectCode, setSelectedSubjectCode] = useState('')
  const [storageTarget, setStorageTarget] = useState('postgres')
  const [learningMemoryCount, setLearningMemoryCount] = useState(0)
  const [dataAgentCount, setDataAgentCount] = useState(0)
  const [selectedDebugTrace, setSelectedDebugTrace] = useState(null)
  const [debugPanelOpen, setDebugPanelOpen] = useState(false)
  const [systemHealth, setSystemHealth] = useState(null)
  const [systemLoading, setSystemLoading] = useState(false)
  const [systemCheckRunning, setSystemCheckRunning] = useState(false)
  const [systemCheckResult, setSystemCheckResult] = useState(null)
  const [adminAccount, setAdminAccount] = useState(null)
  const [adminPasswordForm, setAdminPasswordForm] = useState({ current_password: '', new_password: '', confirm_password: '' })
  const [adminPasswordLoading, setAdminPasswordLoading] = useState(false)
  const [adminPasswordMessage, setAdminPasswordMessage] = useState('')
  const [reindexingAgents, setReindexingAgents] = useState(false)
  const [evaluationReport, setEvaluationReport] = useState(null)
  const [evaluationLoading, setEvaluationLoading] = useState(false)
  const [qualityGateReport, setQualityGateReport] = useState(null)
  const [qualityGateLoading, setQualityGateLoading] = useState(false)
  const [endToEndReport, setEndToEndReport] = useState(null)
  const [endToEndLoading, setEndToEndLoading] = useState(false)
  const [liveSmokeReport, setLiveSmokeReport] = useState(null)
  const [liveSmokeLoading, setLiveSmokeLoading] = useState(false)
  const [dataTruth, setDataTruth] = useState(null)
  const [semanticTraining, setSemanticTraining] = useState(false)
  const [autoTrainingStatus, setAutoTrainingStatus] = useState(null)
  const [autoTrainingLoading, setAutoTrainingLoading] = useState(false)
  const [neuralRouterStatus, setNeuralRouterStatus] = useState(null)
  const [neuralRouterTraining, setNeuralRouterTraining] = useState(false)
  const [knowledgeTab, setKnowledgeTab] = useState('files')
  const [librarySearch, setLibrarySearch] = useState('')
  const [libraryFilter, setLibraryFilter] = useState('all')
  const [showAllDocuments, setShowAllDocuments] = useState(false)
  const [selectedUploadFileName, setSelectedUploadFileName] = useState('')
  const [lastUploadedDocument, setLastUploadedDocument] = useState(null)
  // Exact source selected from Knowledge Workspace; used once by the next chat message.
  const [activeDocumentContext, setActiveDocumentContext] = useState(null)
  const [answerFeedbackState, setAnswerFeedbackState] = useState({})
  const [learningControl, setLearningControl] = useState(null)
  const [learningReviewMemories, setLearningReviewMemories] = useState([])
  const [learningReviewFeedback, setLearningReviewFeedback] = useState([])
  const [learningControlLoading, setLearningControlLoading] = useState(false)
  const messagesEndRef = useRef(null)

  const identityParams = useMemo(() => new URLSearchParams({
    user_role: userRole,
    requester_student_id: studentId || '',
    requester_advisor_id: advisorId || ''
  }), [userRole, studentId, advisorId])

  // Every protected endpoint receives the signed login token. The backend ignores
  // any role/ID values in the request when they disagree with this token.
  const apiFetch = (url, options = {}) => {
    const headers = new Headers(options.headers || {})
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
    return window.fetch(url, { ...options, headers })
  }


  const filteredDocuments = useMemo(() => {
    const term = librarySearch.trim().toLowerCase()
    return (documents || []).filter((doc) => {
      const sourceType = String(doc.source_type || 'pdf').toLowerCase()
      if (libraryFilter !== 'all' && sourceType !== libraryFilter) return false
      if (!term) return true
      const table = doc.conclusion_table || {}
      const profile = table.data_profile || {}
      const haystack = [doc.filename, doc.summary, table.short_summary, table.main_topic, doc.storage_target, doc.subject_name, doc.document_scope, profile.main_topic, profile.document_type]
        .filter(Boolean).join(' ').toLowerCase()
      return haystack.includes(term)
    })
  }, [documents, librarySearch, libraryFilter])

  const handleLogin = (loginData) => {
    setUserRole(loginData.role)
    setStudentId(loginData.studentId || '')
    setAdvisorId(loginData.advisorId || '')
    setSessionId(loginData.sessionId || '')
    setUserName(loginData.name || '')
    setAccessToken(loginData.accessToken || '')
    setIsLoggedIn(true)
  }

  const handleLogout = () => {
    setAccessToken('')
    setIsLoggedIn(false)
    setMessages([])
    setSessions([])
    setInput('')
    setStudentId('')
    setAdvisorId('')
    setSessionId('')
    setUserName('')
    setDocuments([])
    setTablePageDocument(null)
    setSelectedDocument(null)
    setActiveTableTab('overview')
    setTableSearch('')
    setUploadMessage('')
    setAdvisorSubjects([])
    setSelectedSubjectCode('')
    setStorageTarget('postgres')
    setLearningMemoryCount(0)
    setDataAgentCount(0)
    setSelectedDebugTrace(null)
    setDebugPanelOpen(false)
    setSystemHealth(null)
    setSystemLoading(false)
    setAdminAccount(null)
    setAdminPasswordForm({ current_password: '', new_password: '', confirm_password: '' })
    setAdminPasswordLoading(false)
    setAdminPasswordMessage('')
    setReindexingAgents(false)
    setEvaluationReport(null)
    setEvaluationLoading(false)
    setQualityGateReport(null)
    setQualityGateLoading(false)
    setEndToEndReport(null)
    setEndToEndLoading(false)
    setDataTruth(null)
    setSemanticTraining(false)
    setAutoTrainingStatus(null)
    setAutoTrainingLoading(false)
    setKnowledgeTab('files')
    setLibrarySearch('')
    setLibraryFilter('all')
    setShowAllDocuments(false)
    setSelectedUploadFileName('')
    setLastUploadedDocument(null)
    setActiveDocumentContext(null)
    setAnswerFeedbackState({})
    setLearningControl(null)
    setLearningReviewMemories([])
    setLearningReviewFeedback([])
    setLearningControlLoading(false)
  }

  const refreshSessions = async () => {
    const res = await apiFetch(`${API_BASE}/chat/sessions?${identityParams.toString()}`)
    const data = await res.json()
    if (data.success) {
      setSessions(data.sessions || [])
      if (!sessionId && data.active_session_id) {
        setSessionId(data.active_session_id)
        await loadHistory(data.active_session_id)
      }
    }
  }

  const loadHistory = async (sid = sessionId) => {
    const params = new URLSearchParams(identityParams)
    params.set('session_id', sid || '')
    const res = await apiFetch(`${API_BASE}/chat/history?${params.toString()}`)
    const data = await res.json()
    if (data.success) {
      setSessionId(data.session_id)
      setMessages(data.messages || [])
    }
  }

  const createNewChat = async () => {
    const formData = new FormData()
    formData.append('user_role', userRole)
    if (studentId) formData.append('requester_student_id', studentId)
    if (advisorId) formData.append('requester_advisor_id', advisorId)

    const res = await apiFetch(`${API_BASE}/chat/sessions/new`, { method: 'POST', body: formData })
    const data = await res.json()
    if (data.success) {
      setSessionId(data.session_id)
      setMessages([])
      setActiveDocumentContext(null)
      await refreshSessions()
      await loadLearningMemories().catch(() => {})
    }
  }

  const deleteChatSession = async (sid, e) => {
    e.stopPropagation()
    if (!sid) return
    if (!window.confirm('Delete this chat history?')) return

    const params = new URLSearchParams(identityParams)
    try {
      const res = await apiFetch(`${API_BASE}/chat/sessions/${sid}?${params.toString()}`, { method: 'DELETE' })
      const data = await res.json()
      if (!res.ok || !data.success) {
        alert(data.detail || 'Could not delete chat history')
        return
      }
      setSessions(prev => prev.filter(item => item.session_id !== sid))
      if (sid === sessionId) {
        setSessionId('')
        setMessages([])
      }
      await refreshSessions()
    } catch (err) {
      alert(`Delete error: ${err.message}`)
    }
  }

  useEffect(() => {
    if (!isLoggedIn) return
    refreshSessions().catch(() => {})
    if (userRole === 'admin' || userRole === 'advisor' || userRole === 'student') {
      loadDocuments().catch(() => {})
      loadLearningMemories().catch(() => {})
      loadDataAgents().catch(() => {})
      loadSystemHealth().catch(() => {})
      if (userRole === 'admin') { loadAdminAccount().catch(() => {}); loadEvaluationReport().catch(() => {}); loadQualityGateReport().catch(() => {}); loadEndToEndReport().catch(() => {}); loadLiveSmokeReport().catch(() => {}); loadDataTruth().catch(() => {}); loadAutoTrainingStatus().catch(() => {}); loadNeuralRouterStatus().catch(() => {}); loadLearningControl().catch(() => {}) }
    }
    if (userRole === 'advisor') loadAdvisorSubjects().catch(() => {})
  }, [isLoggedIn, identityParams])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, loading])

  const askQuick = (text, doc = null) => {
    setInput(text)
    setActiveDocumentContext(doc ? { id: doc.id, scope: doc.document_scope || (doc.subject_name ? 'advisor' : 'admin'), filename: doc.filename } : null)
    setTimeout(() => document.querySelector('.message-input')?.focus(), 0)
  }

const downloadProtectedReport = async (rawUrl) => {
  try {
    const parsed = new URL(rawUrl, window.location.origin)
    const reportPath = `${parsed.pathname}${parsed.search}`

    if (!parsed.pathname.startsWith('/reports/')) {
      throw new Error('This is not a report download URL.')
    }

    // apiFetch automatically adds Authorization: Bearer <signed token>
    const response = await apiFetch(reportPath)

    if (!response.ok) {
      let detail = `Could not download report (HTTP ${response.status})`
      try {
        const data = await response.json()
        detail = data?.detail || data?.error?.message || detail
      } catch (_) {}
      throw new Error(detail)
    }

    const blob = await response.blob()
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')

    link.href = blobUrl
    link.download = parsed.pathname.split('/').pop() || 'university-report.pdf'
    document.body.appendChild(link)
    link.click()
    link.remove()

    window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000)
  } catch (error) {
    window.alert(`Report download failed: ${error.message}`)
  }
}

  const renderMessageContent = (content = '') => {
  const parts = String(content).split(/(https?:\/\/[^\s]+)/g)

  return parts.map((part, index) => {
    if (/^https?:\/\//.test(part)) {
      const parsed = new URL(part)

      // Browser links cannot carry the Bearer token.
      // Report downloads must use authenticated fetch instead.
      if (parsed.pathname.startsWith('/reports/')) {
        return (
          <button
            key={index}
            type="button"
            className="message-link report-download-button"
            onClick={() => downloadProtectedReport(part)}
          >
            Download full PDF report
          </button>
        )
      }

      return (
        <a
          key={index}
          href={part}
          target="_blank"
          rel="noreferrer"
          className="message-link"
        >
          {part}
        </a>
      )
    }

    return <span key={index}>{part}</span>
  })
}

  const openDebugTrace = (trace) => {
    if (!trace) return
    setSelectedDebugTrace(trace)
    setDebugPanelOpen(true)
  }

  const makeTraceError = (message, detail = '') => ({
    version: 'V11_TRACE_FETCH_ERROR',
    input: { original_message: 'trace fetch', effective_question: 'trace fetch', language, user_role: userRole },
    selected_plan: { tool_name: 'trace_unavailable', selected_agent: 'frontend_trace_loader', arguments: {} },
    validation: { is_valid: false, problems: [message, detail].filter(Boolean), can_repair: false },
    tool_result_summary: { success: false, error: detail || message },
    answer_quality: { answer_preview: 'Trace could not be loaded. The answer may still be valid; check backend health/logs if this repeats.' },
    developer_hint: message
  })

  const loadLastDebugTrace = async () => {
    if (!sessionId) {
      const trace = makeTraceError('No active chat session yet.', 'Ask a question first, then open trace.')
      setSelectedDebugTrace(trace)
      setDebugPanelOpen(true)
      return
    }
    const params = new URLSearchParams(identityParams)
    params.set('session_id', sessionId)
    try {
      const res = await apiFetch(`${API_BASE}/chat/debug/last?${params.toString()}`)
      let data = null
      try { data = await res.json() } catch (_) { data = null }
      if (!res.ok) {
        const trace = makeTraceError('Backend rejected the debug trace request.', data?.detail || `HTTP ${res.status}`)
        setSelectedDebugTrace(trace)
        setDebugPanelOpen(true)
        return
      }
      if (data?.success && data.debug_trace) {
        openDebugTrace(data.debug_trace)
      } else {
        const trace = makeTraceError('No debug trace was stored for this session.', data?.message || 'This can happen after a hard refresh or with an older backend container.')
        setSelectedDebugTrace(trace)
        setDebugPanelOpen(true)
      }
    } catch (err) {
      const trace = makeTraceError('Failed to fetch debug trace from backend.', err.message)
      setSelectedDebugTrace(trace)
      setDebugPanelOpen(true)
    }
  }

  const prettyJson = (value) => JSON.stringify(value || {}, null, 2)

  const renderAiRouteTable = () => {
    const trace = selectedDebugTrace
    if (!trace) {
      return (
        <div className="ai-route-table-card empty-route">
          <strong>AI route table</strong>
          <small>Ask a question to see the purpose, selected data agent, query/filter, result count, and validation beside the chat.</small>
        </div>
      )
    }
    const plan = trace.selected_plan || {}
    const args = plan.arguments || {}
    const purpose = trace.purpose_analysis || {}
    const result = trace.tool_result_summary || {}
    const validation = trace.validation || {}
    const contract = trace.purpose_contract || {}
    const ranking = args.ranking || result.ranking_applied || purpose.ranking_query || {}
    const rows = [
      ['Purpose', purpose.user_purpose || purpose.target_domain || 'not detected'],
      ['Agent', plan.selected_agent || 'normal / fallback'],
      ['Tool', plan.tool_name || 'none'],
      ['Operation', args.operation || result.operation || 'none'],
      ['Scope', args.scope || result.scope || contract.scope || (args.study_term || result.study_term ? 'program / subject' : 'university')],
      ['Study term', args.study_term || result.study_term || '-'],
      ['Statistic', args.statistic || result.statistic || '-'],
      ['Metric / value', `${args.metric_field || result.field || result.metric_label || '-'}${result.value !== undefined && result.value !== null ? ' = ' + result.value : ''}`],
      ['Filter', Object.keys(args.query_filter || {}).length ? JSON.stringify(args.query_filter) : '-'],
      ['Sort / ranking', ranking && Object.keys(ranking).length ? JSON.stringify(ranking) : (Array.isArray(args.sort) && args.sort.length ? JSON.stringify(args.sort) : '-')],
      ['Result', result.count ?? result.total_records ?? result.row_count ?? result.students_count ?? '-'],
      ['Expected contract', contract.expected_operation || contract.statistic || contract.study_term || '-'],
      ['Validation', validation.is_valid === false ? `Mismatch: ${(validation.problems || []).join('; ')}` : 'Passed']
    ]
    return (
      <div className="ai-route-table-card">
        <div className="ai-route-head">
          <strong>AI route table</strong>
          <button type="button" className="tiny-trace-button" onClick={() => setDebugPanelOpen(true)}>Full trace</button>
        </div>
        <table className="ai-route-table">
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label}>
                <th>{label}</th>
                <td>{String(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  const renderDebugTracePanel = () => {
    const trace = selectedDebugTrace
    if (!debugPanelOpen || !trace) return null
    const plan = trace.selected_plan || {}
    const validation = trace.validation || {}
    const steps = Array.isArray(trace.execution_steps) ? trace.execution_steps : []
    return (
      <div className="debug-overlay">
        <div className="debug-panel">
          <header className="debug-header">
            <div>
              <p className="eyebrow">AI debug trace</p>
              <h2>Why did the AI answer this way?</h2>
              <p>{trace.developer_hint || 'Trace shows purpose, tool plan, database result, validation, and final answer.'}</p>
            </div>
            <button type="button" className="close-debug-button" onClick={() => setDebugPanelOpen(false)}>Close</button>
          </header>

          <div className="debug-summary-grid">
            <div className="debug-card"><strong>Tool</strong><span>{plan.tool_name || 'none'}</span></div>
            <div className="debug-card"><strong>Agent</strong><span>{plan.selected_agent || 'normal / fallback'}</span></div>
            <div className="debug-card"><strong>Validation</strong><span>{validation.is_valid === false ? 'Mismatch / needs repair' : 'Passed'}</span></div>
            <div className="debug-card"><strong>Memory</strong><span>{trace.learning_memory?.used ? `Used #${trace.learning_memory.memory_id}` : 'Not used'}</span></div>
          </div>

          <section className="debug-section">
            <h3>1. User purpose / context</h3>
            <pre>{prettyJson({ input: trace.input, purpose_analysis: trace.purpose_analysis, purpose_contract: trace.purpose_contract })}</pre>
          </section>

          <section className="debug-section">
            <h3>2. Tool plan</h3>
            <pre>{prettyJson(plan)}</pre>
          </section>

          <section className="debug-section">
            <h3>3. Execution steps</h3>
            {steps.length ? steps.map((step, idx) => (
              <details key={idx} className="debug-step" open={idx === 0}>
                <summary>{idx + 1}. {step.step || 'step'} {step.tool_name ? `→ ${step.tool_name}` : ''}</summary>
                <pre>{prettyJson(step)}</pre>
              </details>
            )) : <p>No execution steps were recorded.</p>}
          </section>

          <section className="debug-section">
            <h3>4. Tool result summary + validation</h3>
            <pre>{prettyJson({ tool_result_summary: trace.tool_result_summary, validation: trace.validation })}</pre>
          </section>

          <section className="debug-section">
            <h3>5. Final answer quality</h3>
            <pre>{prettyJson(trace.answer_quality)}</pre>
          </section>
        </div>
      </div>
    )
  }

  const sendMessage = async (e) => {
    e.preventDefault()
    if (!input.trim()) return

    const userMessage = input.trim()
    const documentContext = activeDocumentContext
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setInput('')
    // Keep a selected document pinned across follow-up messages. The user can
    // explicitly Clear it, or starting a new chat clears it automatically.
    setLoading(true)

    try {
      const res = await apiFetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage,
          language,
          user_role: userRole,
          requester_student_id: studentId || null,
          requester_advisor_id: advisorId || null,
          session_id: sessionId || null,
          document_id: documentContext?.id || null,
          document_scope: documentContext?.scope || null
        })
      })
      let data = null
      try { data = await res.json() } catch (_) { data = null }
      if (!res.ok || !data) {
        throw new Error(data?.detail || `Backend returned HTTP ${res.status}. Check /system/health and backend logs.`)
      }
      if (data.session_id) setSessionId(data.session_id)
      setMessages(data.history || [...messages, { role: 'assistant', content: data.ai_response || data.detail || 'No response', metadata: { debug_trace: data.debug_trace, answer_source: data.answer_source } }])
      if (data.debug_trace && Object.keys(data.debug_trace).length) {
        setSelectedDebugTrace(data.debug_trace)
      }
      await refreshSessions()
      await loadLearningMemories().catch(() => {})
    } catch (error) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${error.message}` }])
    } finally {
      setLoading(false)
    }
  }

  const submitAnswerFeedback = async (messageIndex, rating) => {
    const assistantMessage = messages[messageIndex]
    const previousUserMessage = [...messages.slice(0, messageIndex)].reverse().find((item) => item.role === 'user')
    if (!assistantMessage || !previousUserMessage) return
    const feedbackKey = `${messageIndex}:${rating}`
    setAnswerFeedbackState((current) => ({ ...current, [messageIndex]: { status: 'saving', rating } }))
    try {
      const res = await apiFetch(`${API_BASE}/ai/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId || null,
          user_role: userRole,
          requester_student_id: studentId || null,
          requester_advisor_id: advisorId || null,
          question: previousUserMessage.content || '',
          answer_excerpt: assistantMessage.content || '',
          rating,
          selected_tool: assistantMessage.metadata?.selected_tool || assistantMessage.metadata?.debug_trace?.selected_plan?.tool_name || null
        })
      })
      const data = await res.json()
      if (!res.ok || !data?.success) throw new Error(data?.detail || 'Could not save feedback')
      setAnswerFeedbackState((current) => ({ ...current, [messageIndex]: { status: 'saved', rating } }))
      if (userRole === 'admin') loadLearningControl().catch(() => {})
    } catch (err) {
      setAnswerFeedbackState((current) => ({ ...current, [messageIndex]: { status: 'error', rating, error: err.message } }))
    }
  }

  const uploadKnowledgeFile = async (e) => {
    e.preventDefault()
    const file = e.target.elements.knowledge_file.files[0]
    if (!file) return
    if (userRole === 'student') {
      setUploadMessage('Students can read allowed advisor PDF/Excel files, but cannot upload files.')
      return
    }
    if (userRole === 'advisor' && !selectedSubjectCode) {
      setUploadMessage('Please choose the subject for this advisor file.')
      return
    }

    const formData = new FormData()
    formData.append('file', file)
    formData.append('user_role', userRole)
    formData.append('storage_target', storageTarget)

    let endpoint = `${API_BASE}/admin/documents/upload`
    if (userRole === 'admin') {
      formData.append('uploaded_by', 'ADMIN')
    } else if (userRole === 'advisor') {
      endpoint = `${API_BASE}/advisor/documents/upload`
      formData.append('requester_advisor_id', advisorId)
      formData.append('subject_code', selectedSubjectCode)
      formData.append('uploaded_by', advisorId || 'ADVISOR')
    }

    setUploading(true)
    setUploadMessage('Reading file carefully. PDFs may use OCR; Excel/CSV files are converted into structured rows, columns, and sheet summaries...')
    try {
      const res = await apiFetch(endpoint, {
        method: 'POST',
        body: formData
      })
      const data = await res.json()
      if (!res.ok) {
        setUploadMessage(data.detail || 'Upload failed')
        return
      }
      const doc = data.document
      const neural = data.neural_data_agent
      setLastUploadedDocument(doc)
      setSelectedUploadFileName('')
      setUploadMessage(`${doc.filename} is ready. It was stored as searchable ${String(doc.source_type || 'file').toUpperCase()} knowledge in ${doc.storage_target || storageTarget}. ${neural?.indexed_chunk_count ? `${neural.indexed_chunk_count} searchable row/chunk(s) were indexed.` : 'A data agent was created.'}`)
      await loadDocuments()
      e.target.reset()
    } catch (err) {
      setUploadMessage(`Upload error: ${err.message}`)
    } finally {
      setUploading(false)
    }
  }

  const loadAdvisorSubjects = async () => {
    if (userRole !== 'advisor' || !advisorId) return
    const params = new URLSearchParams({ user_role: 'advisor', requester_advisor_id: advisorId })
    const res = await apiFetch(`${API_BASE}/advisor/subjects?${params.toString()}`)
    const data = await res.json()
    if (data.success) {
      const subjects = data.subjects || []
      setAdvisorSubjects(subjects)
      if (!selectedSubjectCode && subjects.length) setSelectedSubjectCode(subjects[0].subject_code)
    }
  }

  const loadAdminAccount = async () => {
    if (userRole !== 'admin') return
    const res = await apiFetch(`${API_BASE}/admin/account/me`)
    const data = await res.json()
    if (!res.ok || !data?.success) throw new Error(data?.detail || 'Could not load administrator account')
    setAdminAccount(data.account || null)
  }

  const changeAdminPassword = async (event) => {
    event.preventDefault()
    setAdminPasswordMessage('')
    if (adminPasswordForm.new_password !== adminPasswordForm.confirm_password) {
      setAdminPasswordMessage('New passwords do not match.')
      return
    }
    setAdminPasswordLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/admin/account/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: adminPasswordForm.current_password,
          new_password: adminPasswordForm.new_password
        })
      })
      const data = await res.json()
      if (!res.ok || !data?.success) throw new Error(data?.detail || 'Password could not be updated')
      setAdminAccount(data.account || adminAccount)
      setAdminPasswordForm({ current_password: '', new_password: '', confirm_password: '' })
      setAdminPasswordMessage('Password updated securely in PostgreSQL. Future project-folder changes will not affect this account.')
    } catch (err) {
      setAdminPasswordMessage(err.message || 'Password could not be updated.')
    } finally {
      setAdminPasswordLoading(false)
    }
  }

  const loadSystemHealth = async () => {
    setSystemLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/system/health`)
      const data = await res.json()
      setSystemHealth(data)
    } catch (err) {
      setSystemHealth({ success: false, status: 'unreachable', error: err.message })
    } finally {
      setSystemLoading(false)
    }
  }

  const loadEvaluationReport = async () => {
    if (userRole !== 'admin') return
    try {
      const res = await apiFetch(`${API_BASE}/admin/evaluation/latest?user_role=admin`)
      const data = await res.json()
      if (res.ok && data?.summary) setEvaluationReport(data)
    } catch (_) {
      // The evaluation card remains in a neutral state until the admin runs it.
    }
  }

  const runEvaluationReport = async () => {
    if (userRole !== 'admin') return
    setEvaluationLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/admin/evaluation/run?user_role=admin`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || !data?.summary) {
        setUploadMessage(data?.detail || 'AI evaluation could not run.')
        return
      }
      setEvaluationReport(data)
      const summary = data.summary || {}
      setUploadMessage(`AI evaluation completed: ${summary.passed || 0}/${summary.total || 0} contracts passed (${summary.pass_rate || 0}%).`)
    } catch (err) {
      setUploadMessage(`AI evaluation error: ${err.message}`)
    } finally {
      setEvaluationLoading(false)
    }
  }

  const loadQualityGateReport = async () => {
    if (userRole !== 'admin') return
    try {
      const res = await apiFetch(`${API_BASE}/admin/quality-gate/latest?user_role=admin`)
      const data = await res.json()
      if (res.ok && data?.summary) setQualityGateReport(data)
    } catch (_) {
      // Keep a neutral state when an older backend is running.
    }
  }

  const runQualityGate = async () => {
    if (userRole !== 'admin') return
    setQualityGateLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/admin/quality-gate/run?user_role=admin`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || !data?.summary) {
        setUploadMessage(data?.detail || 'Release quality checks could not run.')
        return
      }
      setQualityGateReport(data)
      const summary = data.summary || {}
      setUploadMessage(`Release quality checks completed: ${summary.passed || 0}/${summary.total || 0} checks passed (${summary.percentage || 0}%).`)
    } catch (err) {
      setUploadMessage(`Release quality check error: ${err.message}`)
    } finally {
      setQualityGateLoading(false)
    }
  }

  const loadDataTruth = async () => {
    if (userRole !== 'admin') return
    try {
      const res = await apiFetch(`${API_BASE}/system/data-truth?user_role=admin`)
      const data = await res.json()
      if (res.ok && data?.data_truth) setDataTruth(data.data_truth)
    } catch (_) {
      setDataTruth(null)
    }
  }

  const loadEndToEndReport = async () => {
    if (userRole !== 'admin') return
    const res = await apiFetch(`${API_BASE}/admin/end-to-end-gate/latest?user_role=admin`)
    const data = await res.json()
    if (res.ok) setEndToEndReport(data)
  }

  const runEndToEndGate = async () => {
    if (userRole !== 'admin') return
    setEndToEndLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/admin/end-to-end-gate/run?user_role=admin`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || !data?.success) {
        setEndToEndReport(data || null)
        setUploadMessage(data?.detail || `End-to-end gate found ${data?.summary?.failed || 'some'} issue(s).`)
        return
      }
      setEndToEndReport(data)
      setUploadMessage(`End-to-end gate completed: ${data.summary?.passed || 0}/${data.summary?.total || 0} complete flows passed. No Gemini tokens were used.`)
    } catch (err) {
      setUploadMessage(`End-to-end gate error: ${err.message}`)
    } finally {
      setEndToEndLoading(false)
    }
  }

  const loadLiveSmokeReport = async () => {
    if (userRole !== 'admin') return
    try {
      const res = await apiFetch(`${API_BASE}/admin/live-smoke-gate/latest?user_role=admin`)
      const data = await res.json()
      if (res.ok && data?.summary) setLiveSmokeReport(data)
    } catch (_) {
      // The System panel stays neutral while Docker services are unavailable.
    }
  }

  const runLiveSmokeGate = async () => {
    if (userRole !== 'admin') return
    setLiveSmokeLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/admin/live-smoke-gate/run?user_role=admin`, { method: 'POST' })
      const data = await res.json()
      setLiveSmokeReport(data || null)
      const summary = data?.summary || {}
      if (!res.ok || !data?.success) {
        const names = (data?.failed_case_ids || []).join(', ')
        setUploadMessage(data?.detail || `Live smoke test found ${summary.failed || 'some'} issue(s)${names ? `: ${names}` : ''}. No data was changed.`)
        return
      }
      setUploadMessage(`Live smoke test completed: ${summary.passed || 0}/${summary.total || 0} checks passed. It used only read-only aggregate checks and no Gemini tokens.`)
    } catch (err) {
      setUploadMessage(`Live smoke test error: ${err.message}`)
    } finally {
      setLiveSmokeLoading(false)
    }
  }

  const runSystemCheck = async () => {
  if (userRole !== "admin") return

  setSystemCheckRunning(true)
  setSystemCheckResult(null)

  try {
    const res = await apiFetch(
      `${API_BASE}/admin/system-check/run?user_role=admin`,
      { method: "POST" }
    )

    const data = await res.json()

    if (!res.ok || !data) {
      throw new Error(data?.detail || "System check could not run.")
    }

    setSystemCheckResult(data)
    setSystemHealth({
      success: data.success,
      status: data.status,
    })

    setUploadMessage(
      data.success
        ? `System check passed: ${data.summary.passed}/${data.summary.total} checks are ready.`
        : `System check found issues: ${data.summary.passed}/${data.summary.total} checks passed.`
    )
  } catch (err) {
    setSystemCheckResult({
      success: false,
      status: "error",
      summary: { passed: 0, total: 0 },
      checks: [
        {
          name: "System check",
          ok: false,
          message: err.message,
        },
      ],
    })
  } finally {
    setSystemCheckRunning(false)
  }
}

  const loadAutoTrainingStatus = async () => {
    if (userRole !== 'admin') return
    const res = await apiFetch(`${API_BASE}/ai/training/status?user_role=admin`)
    const data = await res.json()
    if (res.ok && data?.training) setAutoTrainingStatus(data.training)
  }

  const loadNeuralRouterStatus = async () => {
    if (userRole !== 'admin') return
    const res = await apiFetch(`${API_BASE}/ai/training/neural-router/status?user_role=admin`)
    const data = await res.json()
    if (res.ok && data?.neural_router) setNeuralRouterStatus(data.neural_router)
  }

  const trainNeuralRouter = async () => {
    if (userRole !== 'admin') return
    setNeuralRouterTraining(true)
    try {
      const res = await apiFetch(`${API_BASE}/ai/training/neural-router/run?user_role=admin&force=true`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || data?.success === false) {
        setUploadMessage(data?.detail || data?.error || 'Neural router training failed.')
      } else {
        const metrics = data?.metrics || data?.neural_router?.metrics || {}
        const accuracy = metrics?.validation_accuracy
        const displayAccuracy = typeof accuracy === 'number' ? ` Validation accuracy ${(accuracy * 100).toFixed(1)}%.` : ''
        setUploadMessage(`Neural router trained locally from ${data?.training_examples || data?.neural_router?.training_examples || 0} approved examples.${displayAccuracy} It does not fine-tune Gemini or use raw student records as training text.`)
      }
      await loadNeuralRouterStatus().catch(() => {})
    } catch (err) {
      setUploadMessage(`Neural router training error: ${err.message}`)
    } finally {
      setNeuralRouterTraining(false)
    }
  }

  const trainSemanticDataAgents = async () => {
    if (userRole !== 'admin') return
    setSemanticTraining(true)
    setAutoTrainingLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/ai/training/run-local?user_role=admin`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || data.success === false) {
        setUploadMessage(data.detail || data.error || data.errors?.join('; ') || 'Local automatic training failed')
      } else if (data.status === 'already_running') {
        setUploadMessage('Automatic local training is already running. No duplicate training job was started.')
      } else {
        setUploadMessage(`Local training completed: ${data.sources_changed || 0} changed source(s), ${data.sources_skipped || 0} unchanged source(s) skipped. No Gemini tokens were used.`)
      }
      await Promise.all([loadDataAgents().catch(() => {}), loadDataTruth().catch(() => {}), loadAutoTrainingStatus().catch(() => {})])
    } catch (err) {
      setUploadMessage(`Local training error: ${err.message}`)
    } finally {
      setSemanticTraining(false)
      setAutoTrainingLoading(false)
    }
  }

  const reindexExistingDataAgents = async () => {
    if (userRole !== 'admin') return
    setReindexingAgents(true)
    try {
      const res = await apiFetch(`${API_BASE}/ai/data-agents/reindex-existing?user_role=admin`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok || data.success === false) {
        setUploadMessage(data.detail || data.errors?.join('; ') || 'Reindex failed')
      } else {
        setUploadMessage(`Reindexed existing database agents: ${data.indexed_agent_count || 0} table/collection agent(s).`)
      }
      await loadDataAgents().catch(() => {})
      await loadSystemHealth().catch(() => {})
    } catch (err) {
      setUploadMessage(`Reindex error: ${err.message}`)
    } finally {
      setReindexingAgents(false)
    }
  }

  const loadLearningMemories = async () => {
    const params = new URLSearchParams(identityParams)
    const res = await apiFetch(`${API_BASE}/ai/learning/memories?${params.toString()}`)
    const data = await res.json()
    if (data.success) setLearningMemoryCount(data.count || 0)
  }


  const loadLearningControl = async () => {
    if (userRole !== 'admin') return
    const [overviewRes, memoriesRes, feedbackRes] = await Promise.all([
      apiFetch(`${API_BASE}/admin/learning-control/overview?user_role=admin`),
      apiFetch(`${API_BASE}/admin/learning-control/memories?user_role=admin&limit=12`),
      apiFetch(`${API_BASE}/admin/learning-control/feedback?user_role=admin&limit=8`)
    ])
    const [overview, memoryQueue, feedbackQueue] = await Promise.all([
      overviewRes.json().catch(() => null),
      memoriesRes.json().catch(() => null),
      feedbackRes.json().catch(() => null)
    ])
    if (overviewRes.ok && overview?.success) setLearningControl(overview)
    if (memoriesRes.ok && memoryQueue?.success) setLearningReviewMemories(memoryQueue.memories || [])
    if (feedbackRes.ok && feedbackQueue?.success) setLearningReviewFeedback(feedbackQueue.feedback || [])
  }

  const reviewLearningMemory = async (memoryId, action) => {
    if (userRole !== 'admin') return
    setLearningControlLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/admin/learning-control/memories/${memoryId}/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_role: 'admin' })
      })
      const data = await res.json()
      if (!res.ok || !data?.success) throw new Error(data?.detail || 'Could not update learning candidate')
      setUploadMessage(`Learning candidate ${action === 'publish' ? 'published for future routing' : action === 'pause' ? 'paused' : 'dismissed'}.`)
      await Promise.all([loadLearningControl(), loadLearningMemories().catch(() => {})])
    } catch (err) {
      setUploadMessage(`Learning review error: ${err.message}`)
    } finally {
      setLearningControlLoading(false)
    }
  }

  const reviewAnswerFeedback = async (feedbackId, action) => {
    if (userRole !== 'admin') return
    setLearningControlLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/admin/learning-control/feedback/${feedbackId}/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_role: 'admin' })
      })
      const data = await res.json()
      if (!res.ok || !data?.success) throw new Error(data?.detail || 'Could not update feedback')
      setUploadMessage(`Feedback marked ${action}. It has not changed any planner rule automatically.`)
      await loadLearningControl()
    } catch (err) {
      setUploadMessage(`Feedback review error: ${err.message}`)
    } finally {
      setLearningControlLoading(false)
    }
  }

  const runControlledLearningGate = async () => {
    if (userRole !== 'admin') return
    setLearningControlLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/admin/learning-control/gate/run?user_role=admin`, { method: 'POST' })
      const data = await res.json()
      const summary = data?.summary || {}
      if (!res.ok || !data?.success) throw new Error(data?.detail || 'Controlled learning gate found an issue')
      setUploadMessage(`Controlled-learning gate passed: ${summary.passed || 0}/${summary.total || 0}. No Gemini tokens were used.`)
    } catch (err) {
      setUploadMessage(`Controlled-learning gate error: ${err.message}`)
    } finally {
      setLearningControlLoading(false)
    }
  }


  const loadDataAgents = async () => {
    const params = new URLSearchParams(identityParams)
    try {
      const res = await apiFetch(`${API_BASE}/ai/data-agents?${params.toString()}`)
      const data = await res.json()
      if (data.success) setDataAgentCount((data.agents || []).length)
    } catch (_) {
      setDataAgentCount(0)
    }
  }

  const loadDocuments = async () => {
    let url = `${API_BASE}/admin/all-documents?user_role=admin`
    if (userRole === 'advisor') {
      const params = new URLSearchParams({ user_role: 'advisor', requester_advisor_id: advisorId || '' })
      url = `${API_BASE}/advisor/documents?${params.toString()}`
    } else if (userRole === 'student') {
      const params = new URLSearchParams({ user_role: 'student', requester_student_id: studentId || '' })
      url = `${API_BASE}/student/documents?${params.toString()}`
    }
    const res = await apiFetch(url)
    const data = await res.json()
    if (data.success) setDocuments(data.documents || [])
    await loadDataAgents().catch(() => {})
  }


const openDocumentTable = async (doc) => {
  setDocumentLoading(true)
  try {
    setSelectedDocument(doc)
    setTablePageDocument(doc)
    setActiveTableTab('overview')
    setTableSearch('')
  } finally {
    setDocumentLoading(false)
  }
}

  const closeDocumentTable = () => {
    setSelectedDocument(null)
    setTablePageDocument(null)
    setActiveTableTab('overview')
    setTableSearch('')
  }

  const deleteDocument = async (doc, e) => {
    if (e) e.stopPropagation()
    if (!doc || userRole === 'student') return
    if (!window.confirm(`Delete ${doc.filename}?`)) return

    let url = `${API_BASE}/admin/all-documents/${doc.document_scope || 'admin'}/${doc.id}?user_role=admin`
    if (userRole === 'advisor') {
      const params = new URLSearchParams({ user_role: 'advisor', requester_advisor_id: advisorId || '' })
      url = `${API_BASE}/advisor/documents/${doc.id}?${params.toString()}`
    }

    try {
      const res = await apiFetch(url, { method: 'DELETE' })
      const data = await res.json()
      if (!res.ok || !data.success) {
        setUploadMessage(data.detail || 'Could not delete document')
        return
      }
      if (selectedDocument?.id === doc.id) setSelectedDocument(null)
      if (tablePageDocument?.id === doc.id) setTablePageDocument(null)
      setUploadMessage('Document deleted.')
      await loadDocuments()
    } catch (err) {
      setUploadMessage(`Delete error: ${err.message}`)
    }
  }

  const renderValueList = (title, value) => {
    const items = Array.isArray(value) ? value.filter(Boolean) : (value ? [value] : [])
    if (!items.length) return null
    return (
      <div className="insight-card">
        <h4>{title}</h4>
        <ul>{items.map((item, idx) => <li key={idx}>{String(item)}</li>)}</ul>
      </div>
    )
  }

  const buildDocumentProfile = (doc) => {
    const table = doc?.conclusion_table || {}
    const structured = doc?.structured_data || {}
    const saved = table.data_profile || {}
    const sourceType = saved.source_type || doc?.source_type || structured?.source_type || 'file'
    const storageTarget = saved.storage?.target || doc?.storage_target || table.storage_target || 'postgres'
    const storageInfo = STORAGE_EXPLANATIONS[storageTarget] || { label: storageTarget, plain: 'Stored as a searchable knowledge source.' }
    const fallback = {
      title: doc?.filename || 'Knowledge file',
      source_type: sourceType,
      storage: { target: storageTarget, label: storageInfo.label, plain: storageInfo.plain, agent: doc?.cloned_agent_name || table.cloned_agent_name || 'knowledge agent', searchable: true },
      summary: table.short_summary || doc?.summary || 'The file was processed and stored as searchable knowledge.',
      main_topic: table.main_topic || doc?.filename?.replace(/\.[^.]+$/, '') || 'Knowledge file',
      document_type: table.document_type || sourceType,
      facts: [], schema_preview: [], numeric_highlights: [], search_capabilities: [], recommended_questions: table.recommended_questions || []
    }
    if (sourceType === 'pdf') {
      const pages = structured.total_pages || table.pdf_total_pages || 0
      const chunks = structured.stored_row_count || structured.total_rows || table.full_text_row_count || 0
      fallback.facts = [
        { label: 'Pages', value: pages || 'Unknown' },
        { label: 'Searchable chunks', value: chunks || 'No extracted chunks' },
        { label: 'Language', value: doc?.detected_language || table.detected_language || 'Unknown' },
        { label: 'Extraction', value: doc?.extraction_method || table.extraction_method || 'Text extraction' }
      ]
      fallback.search_capabilities = ['Search concepts and definitions', 'Open full text by page and chunk', 'Ask a question about this document']
    }
    if (sourceType === 'excel') {
      const sheets = structured.sheets || []
      fallback.facts = [
        { label: 'Sheets', value: structured.sheet_count || sheets.length || 0 },
        { label: 'Stored rows', value: structured.total_rows || 0 },
        { label: 'Columns', value: structured.total_columns || 0 },
        { label: 'Parsing', value: 'Structured spreadsheet rows' }
      ]
      fallback.schema_preview = sheets.slice(0, 6).map((sheet) => ({ sheet: sheet.sheet_name || 'Sheet', rows: sheet.row_count || 0, columns: (sheet.columns || []).slice(0, 8) }))
      fallback.numeric_highlights = sheets.flatMap((sheet) => Object.entries(sheet.numeric_summary || {}).map(([column, stats]) => ({ sheet: sheet.sheet_name || 'Sheet', column, min: stats?.min, max: stats?.max, average: stats?.mean ?? stats?.average }))).slice(0, 8)
      fallback.search_capabilities = ['Search individual rows and column values', 'Compare totals, averages, highs and lows', 'Ask which sheet contains a value or topic']
    }
    if (!fallback.recommended_questions.length) {
      fallback.recommended_questions = sourceType === 'excel'
        ? ['What sheets and columns are in this file?', 'Which rows match a condition?', 'What are the highest and lowest values?']
        : ['What is this file about?', 'Explain a key term from this file.', 'Which page discusses a topic?']
    }
    return { ...fallback, ...saved, storage: { ...fallback.storage, ...(saved.storage || {}) } }
  }

  const renderDocumentInsights = (doc) => {
    const profile = buildDocumentProfile(doc)
    const table = doc?.conclusion_table || {}
    return (
      <div className="document-workspace-overview">
        <section className="knowledge-hero-card">
          <div className="knowledge-hero-topline">
            <span className={`file-type-pill ${profile.source_type === 'excel' ? 'excel' : 'pdf'}`}>{String(profile.source_type || 'file').toUpperCase()}</span>
            <span className="storage-pill">{profile.storage?.label || profile.storage?.target || 'Stored knowledge'}</span>
          </div>
          <h2>{profile.main_topic || doc.filename}</h2>
          <p>{profile.summary || 'No summary stored yet.'}</p>
          <div className="knowledge-fact-grid">
            {(profile.facts || []).map((fact, idx) => <div className="knowledge-fact" key={`${fact.label}-${idx}`}><span>{fact.label}</span><strong>{String(fact.value ?? '-')}</strong></div>)}
          </div>
        </section>

        <section className="workspace-section source-truth-section">
          <div className="workspace-section-heading"><div><p className="eyebrow">Data source and trust</p><h3>Where this knowledge lives</h3></div></div>
          <div className="source-truth-grid">
            <article><span>Storage</span><strong>{profile.storage?.label || profile.storage?.target || 'Stored knowledge'}</strong><p>{profile.storage?.plain || 'This file is stored as a searchable knowledge source.'}</p></article>
            <article><span>Source of answers</span><strong>Stored file text and rows</strong><p>The assistant should answer file questions from the extracted PDF text or spreadsheet rows first.</p></article>
            <article><span>Reading guide</span><strong>Helpful, but not the source</strong><p>Reading guide notes are organized for revision. Use Data table to verify the underlying stored text or values.</p></article>
          </div>
        </section>

        <section className="workspace-section">
          <div className="workspace-section-heading"><div><p className="eyebrow">Stored understanding</p><h3>What the system can use from this file</h3></div></div>
          <div className="capability-grid">{(profile.search_capabilities || []).map((item, idx) => <div className="capability-item" key={idx}>✓ {item}</div>)}</div>
        </section>

        {profile.schema_preview?.length > 0 && <section className="workspace-section">
          <div className="workspace-section-heading"><div><p className="eyebrow">Data shape</p><h3>Sheets and important columns</h3></div></div>
          <div className="schema-card-grid">{profile.schema_preview.map((sheet, idx) => <article className="schema-card" key={`${sheet.sheet}-${idx}`}><strong>{sheet.sheet}</strong><small>{sheet.rows} row(s)</small><p>{(sheet.columns || []).join(' · ') || 'No visible columns'}</p></article>)}</div>
        </section>}

        {profile.numeric_highlights?.length > 0 && <section className="workspace-section">
          <div className="workspace-section-heading"><div><p className="eyebrow">Numeric highlights</p><h3>Values ready for comparison</h3></div></div>
          <div className="metric-card-grid">{profile.numeric_highlights.map((item, idx) => <article className="metric-card" key={`${item.sheet}-${item.column}-${idx}`}><span>{item.sheet} · {item.column}</span><strong>Avg {item.average ?? '—'}</strong><small>Min {item.min ?? '—'} · Max {item.max ?? '—'}</small></article>)}</div>
        </section>}

        <section className="workspace-section ask-section">
          <div className="workspace-section-heading"><div><p className="eyebrow">Ask better questions</p><h3>Useful questions for this knowledge source</h3></div></div>
          <div className="question-chip-list">{(profile.recommended_questions || []).slice(0, 6).map((question, idx) => <button key={idx} type="button" onClick={() => { closeDocumentTable(); askQuick(question, doc) }}>{question}</button>)}</div>
        </section>

        {(table.key_points?.length || table.detailed_information?.length || table.data_quality_notes?.length) && <details className="ai-notes-details"><summary>Preview reading guide and extraction details</summary><p className="notes-disclosure">This reading guide is organized from extracted file content. It helps with revision, but it is not the original source text.</p><div className="insight-grid">{renderValueList('Key points', table.key_points)}{renderValueList('Details', table.detailed_information)}{renderValueList('Data quality notes', table.data_quality_notes)}{renderValueList('Requirements / conditions', table.requirements_or_conditions)}</div></details>}
      </div>
    )
  }


  const renderTableBlock = (title, description, columns, rows, sourceLabel = 'Stored source data') => (
    <WorkspaceDataTable
      title={title}
      description={description}
      columns={columns}
      rows={rows}
      sourceLabel={sourceLabel}
      externalQuery={tableSearch}
    />
  )

  const renderConclusionTable = (doc) => {
    const table = doc?.conclusion_table || {}
    const rows = table.rows || []
    const notes = {
      keyPoints: table.key_points || [],
      details: table.detailed_information || [],
      actions: table.actions_or_next_steps || [],
      requirements: table.requirements_or_conditions || [],
      quality: table.data_quality_notes || []
    }
    const hasNotes = Object.values(notes).some(value => Array.isArray(value) && value.length)
    return (
      <div className="study-notes-page">
        <section className="study-notes-intro">
          <p className="eyebrow">Reading guide</p>
          <h3>Organized notes based on this file</h3>
          <p>These notes group definitions, key ideas, and details from the extracted file content to make revision easier. They are supporting notes, not the original source. Use <strong>Data table</strong> to inspect the stored PDF chunks or spreadsheet rows behind them.</p>
          <div className="reading-guide-evidence"><strong>Evidence rule:</strong> File questions should be answered from the selected file’s stored text first. The guide is never used as a replacement for the source.</div>
        </section>
        {hasNotes && <div className="study-notes-grid">
          {renderValueList('Key ideas', notes.keyPoints)}
          {renderValueList('Important details', notes.details)}
          {renderValueList('Requirements / conditions', notes.requirements)}
          {renderValueList('Actions / next steps', notes.actions)}
          {renderValueList('Extraction quality', notes.quality)}
        </div>}
        {rows.length ? renderTableBlock(
          'Supporting extracted notes',
          'These structured rows support the study notes. Use Data table for the complete raw extraction.',
          table.columns || ['No', 'Extracted Information'],
          rows
        ) : <div className="empty-docs">No separate study-note rows were generated. The Overview and Data table still show the stored file information.</div>}
      </div>
    )
  }

  const renderFullStoredDataTable = (doc) => {
    const table = doc?.conclusion_table || {}
    const structured = doc?.structured_data || {}
    const fullTable = table.full_extraction_table || null

    if (fullTable?.rows?.length) {
      return renderTableBlock(
        fullTable.title || 'Full stored extraction table',
        fullTable.description || 'This is the complete stored extraction data, not only the summary.',
        fullTable.columns,
        fullTable.rows,
        'Original stored extraction'
      )
    }

    if (structured?.source_type === 'pdf' && Array.isArray(structured.rows) && structured.rows.length) {
      return renderTableBlock(
        'Full PDF extracted data',
        'Every readable PDF paragraph/chunk stored as table rows.',
        structured.columns,
        structured.rows,
        'Original PDF text chunks'
      )
    }

    if (structured?.source_type === 'excel' && Array.isArray(structured.sheets) && structured.sheets.length) {
      return (
        <div className="stored-table-block">
          <div className="stored-table-heading">
            <h4>Full spreadsheet stored rows</h4>
            <p>These are the actual spreadsheet rows stored for the Excel/CSV agent.</p>
          </div>
          {structured.sheets.map((sheet, idx) => renderTableBlock(
            `Sheet: ${sheet.sheet_name || idx + 1}`,
            `${sheet.row_count || 0} original row(s), ${sheet.stored_row_count || (sheet.rows || []).length} stored row(s).`,
            sheet.columns,
            sheet.rows,
            `Original spreadsheet rows · ${sheet.sheet_name || idx + 1}`
          ))}
        </div>
      )
    }

    return null
  }

  const hasFullStoredData = (doc) => {
    const table = doc?.conclusion_table || {}
    const structured = doc?.structured_data || {}
    return Boolean(
      table.full_extraction_table?.rows?.length ||
      (structured?.source_type === 'pdf' && Array.isArray(structured.rows) && structured.rows.length) ||
      (structured?.source_type === 'excel' && Array.isArray(structured.sheets) && structured.sheets.some(sheet => Array.isArray(sheet.rows) && sheet.rows.length))
    )
  }

  const renderTablePage = (doc) => (
    <div className="table-page-shell">
      <header className="table-page-header">
        <div className="table-page-title">
          <button type="button" className="back-table-button" onClick={closeDocumentTable}>← Back to chat</button>
          <div>
            <p className="eyebrow">Knowledge workspace</p>
            <h1>{doc.filename}</h1>
            <p className="table-page-meta">
              {(doc.source_type || 'file').toUpperCase()} knowledge source · {STORAGE_EXPLANATIONS[doc.storage_target || 'postgres']?.label || doc.storage_target || 'stored knowledge'} · Status: {(doc.conclusion_table || {}).status || 'ready'}
            </p>
          </div>
        </div>
        <div className="table-page-actions">
          <button type="button" className="ask-doc-button" onClick={() => { closeDocumentTable(); askQuick('What is this file about?', doc) }}>Ask AI about this file</button>
          {userRole !== 'student' && <button type="button" className="delete-doc-button" onClick={(e) => deleteDocument(doc, e)}>Delete</button>}
        </div>
      </header>

      <div className="table-page-toolbar">
        <div className="table-tabs">
          <button type="button" className={activeTableTab === 'overview' ? 'active' : ''} onClick={() => setActiveTableTab('overview')}>Overview</button>
          <button type="button" className={activeTableTab === 'full' ? 'active' : ''} onClick={() => setActiveTableTab('full')} disabled={!hasFullStoredData(doc)}>Data table</button>
          <button type="button" className={activeTableTab === 'notes' ? 'active' : ''} onClick={() => setActiveTableTab('notes')}>Reading guide</button>
        </div>
        <div className="workspace-search-wrap">
          <input
            className="table-search-input"
            value={tableSearch}
            onChange={(e) => setTableSearch(e.target.value)}
            placeholder="Search all stored rows and text…"
          />
          {tableSearch && <button type="button" className="clear-workspace-search" onClick={() => setTableSearch('')}>Clear</button>}
        </div>
      </div>

      <main className="table-page-content">
        {activeTableTab === 'overview' && renderDocumentInsights(doc)}
        {activeTableTab === 'full' && (renderFullStoredDataTable(doc) || <div className="empty-docs"><strong>No full stored data table found.</strong><br />Upload the file again with the latest version to create full PDF/Excel rows.</div>)}
        {activeTableTab === 'notes' && renderConclusionTable(doc)}
      </main>
    </div>
  )
  const renderChatResultTable = (table) => {
  if (!table?.rows?.length) return null

  return (
    <section className="workspace-data-table chat-result-table">
      <header className="workspace-data-heading">
        <div>
          <p className="eyebrow">University database result</p>
          <h3>{table.title || "Table result"}</h3>
          <p>
            Showing {table.shown_records} of {table.total_records} records.
          </p>
        </div>

        {table.report?.download_url && (
          <a
            className="export-table-button"
            href={table.report.download_url}
            target="_blank"
            rel="noreferrer"
          >
            Download full PDF report
          </a>
        )}
      </header>

      <div className="table-scroll workspace-table-scroll">
        <table className="knowledge-table enhanced-knowledge-table">
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>

          <tbody>
            {table.rows.map((row, index) => (
              <tr key={index}>
                {table.columns.map((column) => (
                  <td key={column}>{row[column] || "—"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
  return (
    
    <>
      {!isLoggedIn ? (
        <LoginPage onLogin={handleLogin} />
      ) : tablePageDocument ? (
        renderTablePage(tablePageDocument)
      ) : (
        <div className="app-shell">
          <aside className="history-sidebar">
            <div className="sidebar-brand">🎓 University AI</div>
            <button className="new-chat-button" onClick={createNewChat}>+ New chat</button>
            <div className="history-title">Chat history</div>
            <div className="history-list">
              {sessions.map(item => (
                <div
                  key={item.session_id}
                  className={`history-row ${item.session_id === sessionId ? 'active' : ''}`}
                >
                  <button
                    className="history-item"
                    onClick={() => loadHistory(item.session_id)}
                    title={item.last_message}
                  >
                    <span className="history-item-title">{item.title || 'New chat'}</span>
                    <span className="history-item-subtitle">{item.last_message || 'No messages yet'}</span>
                  </button>
                  <button
                    type="button"
                    className="history-delete"
                    title="Delete chat"
                    onClick={(e) => deleteChatSession(item.session_id, e)}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <button className="logout-button sidebar-logout" onClick={handleLogout}>Logout</button>
          </aside>

          <main className="chat-panel">
            <header className="topbar">
              <div>
                <h1>MCP Agent University Chatbot</h1>
                <div className="config-row">
                  <span className="pill">Role: {userRole}</span>
                  <span className="pill">Name: {userName}</span>
                  {userRole === 'student' && <span className="pill">Student ID: {studentId}</span>}
                  {userRole === 'advisor' && <span className="pill">Advisor ID: {advisorId}</span>}
                </div>
              </div>
              <select value={language} onChange={(e) => setLanguage(e.target.value)} className="language-select">
                <option value="en">English</option>
                <option value="th">Thai</option>
              </select>
            </header>

            <section className="messages">
              {messages.length === 0 ? (
                <div className="welcome-card">
                  <h2>Welcome, {userName || userRole}</h2>
                  <p>Your conversations are saved in PostgreSQL. Use the left sidebar to continue an old chat or start a new one.</p>
                </div>
              ) : (
                messages.map((msg, i) => (
                  <div key={i} className={`message message-${msg.role}`}>
                    <div className="message-bubble">
                      <div className="message-role">{msg.role === 'user' ? 'You' : (userRole === 'admin' ? 'AI Assistant' : 'University AI')}</div>
                      <div className="message-content">{renderMessageContent(msg.content)}</div>
                      {msg.role === 'assistant' && renderChatResultTable(msg.metadata?.data_table)}
                      {msg.role === 'assistant' && msg.metadata?.answer_source?.visible && (
                        <div className={`answer-source answer-source-${msg.metadata.answer_source.kind || 'general_guidance'}`}>
                          <strong>{msg.metadata.answer_source.label}</strong>
                          {msg.metadata.answer_source.detail && <span>{msg.metadata.answer_source.detail}</span>}
                        </div>
                      )}
                      {msg.role === 'assistant' && (() => {
                        const feedback = answerFeedbackState[i]
                        if (feedback?.status === 'saved') return <div className="answer-feedback saved">{feedback.rating === 'helpful' ? '✓ Marked helpful' : '✓ Sent for review'}</div>
                        if (feedback?.status === 'saving') return <div className="answer-feedback saved">Saving feedback…</div>
                        if (feedback?.status === 'error') return <div className="answer-feedback error">Feedback was not saved. Try again.</div>
                        return <div className="answer-feedback"><span>Was this answer useful?</span><button type="button" onClick={() => submitAnswerFeedback(i, 'helpful')}>Helpful</button><button type="button" onClick={() => submitAnswerFeedback(i, 'needs_review')}>Needs review</button></div>
                      })()}
                    </div>
                  </div>
                ))
              )}
              {loading && <div className="message message-assistant"><div className="message-bubble typing-bubble"><span></span>Reading allowed data...</div></div>}
              <div ref={messagesEndRef} />
            </section>

            <form onSubmit={sendMessage} className="chat-form">
              <div className="input-wrap">
                <div className="quick-prompts">
                  {userRole === 'student' && <>
                    <button type="button" onClick={() => askQuick('what is my grade')}>My grades</button>
                    <button type="button" onClick={() => askQuick('what PDF or Excel files can I access?')}>My files</button>
                    <button type="button" onClick={() => askQuick('what is my profile?')}>My profile</button>
                  </>}
                  {userRole === 'advisor' && <>
                    <button type="button" onClick={() => askQuick('show students I teach')}>My students</button>
                    <button type="button" onClick={() => askQuick('what PDF or Excel files have I uploaded?')}>My files</button>
                  </>}
                  {userRole === 'admin' && <>
                    <button type="button" onClick={() => askQuick('explain machine learning simply')}>Normal chat</button>
                    <button type="button" onClick={() => askQuick('list all students')}>Students</button>
                    <button type="button" onClick={() => askQuick('what PDF or Excel files are uploaded?')}>Files</button>
                    <button type="button" onClick={() => askQuick('summarize everything in the university system')}>University overview</button>
                  </>}
                </div>
                {activeDocumentContext && <div className="active-document-context" role="status"><span><strong>📌 Pinned file:</strong> {activeDocumentContext.filename}</span><button type="button" onClick={() => setActiveDocumentContext(null)}>Clear file</button></div>}
                <input value={input} onChange={(e) => setInput(e.target.value)} placeholder={activeDocumentContext ? `Ask a question about ${activeDocumentContext.filename}` : (userRole === 'admin' ? "Ask anything, or ask the university database/PDF/Excel files..." : "Ask naturally — typos are okay, like 'wht is my gade'...")} disabled={loading} className="message-input" />
              </div>
              <button type="submit" disabled={loading} className="send-button">{loading ? 'Thinking...' : 'Send'}</button>
            </form>
          </main>

          {(userRole === 'admin' || userRole === 'advisor' || userRole === 'student') && (
            <aside className="admin-right-panel knowledge-rail">
              <div className="right-panel-header knowledge-rail-header">
                <div>
                  <p className="eyebrow">Knowledge workspace</p>
                  <h2>{userRole === 'admin' ? 'University knowledge' : userRole === 'advisor' ? 'My subject knowledge' : 'My learning files'}</h2>
                  <p className="panel-help compact-help">Upload, review, and ask questions about your stored PDF, Excel, and CSV knowledge.</p>
                </div>
                <span className="doc-count">{documents.length}</span>
              </div>
              <div className="knowledge-tabs" role="tablist" aria-label="Knowledge workspace tabs">
                <button type="button" className={knowledgeTab === 'files' ? 'active' : ''} onClick={() => setKnowledgeTab('files')}>Files</button>
                {userRole === 'admin' && <button type="button" className={knowledgeTab === 'system' ? 'active' : ''} onClick={() => setKnowledgeTab('system')}>System</button>}
              </div>
              {knowledgeTab === 'files' || userRole !== 'admin' ? (
                <div className="knowledge-files-pane">
                  {(userRole === 'admin' || userRole === 'advisor') && (
                    <form onSubmit={uploadKnowledgeFile} className="knowledge-upload-card">
                      <div className="upload-card-heading"><div><p className="eyebrow">Add knowledge</p><h3>Upload a PDF, Excel, or CSV</h3></div><span className="upload-agent-badge">Local index</span></div>
                      <p>Files become a searchable knowledge source with a clean data overview and a dedicated data agent.</p>
                      {userRole === 'advisor' && <label className="form-field"><span>Subject</span><select value={selectedSubjectCode} onChange={(e) => setSelectedSubjectCode(e.target.value)}>{advisorSubjects.length === 0 ? <option value="">No subjects available</option> : advisorSubjects.map(subject => <option key={subject.subject_code} value={subject.subject_code}>{subject.subject_name}</option>)}</select></label>}
                      <label className="form-field"><span>Store as</span><select value={storageTarget} onChange={(e) => setStorageTarget(e.target.value)}><option value="postgres">PostgreSQL knowledge record</option><option value="mongodb">MongoDB knowledge clone</option><option value="excel">Excel-agent structured store</option></select></label>
                      <label className="file-picker-label"><input name="knowledge_file" type="file" accept="application/pdf,.pdf,.xlsx,.xls,.csv" onChange={(e) => setSelectedUploadFileName(e.target.files?.[0]?.name || '')} /><span>{selectedUploadFileName || 'Choose a PDF, Excel, or CSV file'}</span></label>
                      <button type="submit" className="upload-primary-button" disabled={uploading || !selectedUploadFileName}>{uploading ? 'Processing knowledge…' : 'Create knowledge source'}</button>
                    </form>
                  )}
                  {uploading && <div className="upload-progress-card">Reading and structuring the file. Please wait.</div>}
                  {uploadMessage && <div className="upload-result-card"><strong>{lastUploadedDocument ? 'Knowledge source ready' : 'Workspace update'}</strong><p>{uploadMessage}</p>{lastUploadedDocument && <button type="button" onClick={() => openDocumentTable(lastUploadedDocument)}>Open workspace</button>}</div>}
                  <div className="file-library-toolbar"><div><p className="eyebrow">File library</p><h3>{filteredDocuments.length} matching file{filteredDocuments.length === 1 ? '' : 's'}</h3></div><button type="button" className="refresh-library-button" onClick={loadDocuments}>Refresh</button></div>
                  <div className="library-controls"><input value={librarySearch} onChange={(e) => { setLibrarySearch(e.target.value); setShowAllDocuments(false) }} placeholder="Search file names or topics" /><select value={libraryFilter} onChange={(e) => { setLibraryFilter(e.target.value); setShowAllDocuments(false) }}><option value="all">All file types</option><option value="pdf">PDF</option><option value="excel">Excel / CSV</option></select></div>
                  <div className="document-list compact-document-list">
                    {filteredDocuments.length === 0 ? <div className="empty-docs"><strong>No matching files.</strong><br />Upload a document or change the search/filter.</div> : (showAllDocuments ? filteredDocuments : filteredDocuments.slice(0, 5)).map(doc => {
                      const profile = buildDocumentProfile(doc)
                      return <article className="knowledge-file-card" key={doc.global_id || `${doc.document_scope || 'doc'}-${doc.id}`}><div className="knowledge-file-icon">{profile.source_type === 'excel' ? '▦' : '▤'}</div><div className="knowledge-file-main"><div className="knowledge-file-topline"><span className={`file-type-pill ${profile.source_type === 'excel' ? 'excel' : 'pdf'}`}>{String(profile.source_type || 'file').toUpperCase()}</span><span className="storage-pill mini">{profile.storage?.target || doc.storage_target || 'postgres'}</span>{doc.subject_name && <span className="subject-pill">{doc.subject_name}</span>}</div><h3 title={doc.filename}>{doc.filename}</h3><p>{profile.summary || doc.summary || 'Structured knowledge source ready for questions.'}</p><small>{(profile.facts || []).slice(0, 2).map(item => `${item.label}: ${item.value}`).join(' · ') || 'Searchable knowledge source'}</small><div className="knowledge-file-actions"><button type="button" className="open-workspace-button" onClick={() => openDocumentTable(doc)} disabled={documentLoading}>Open</button><button type="button" className="secondary-file-button" onClick={() => askQuick('What is this file about?', doc)}>Ask</button>{userRole !== 'student' && <button type="button" className="icon-delete-button" title={`Delete ${doc.filename}`} onClick={(e) => deleteDocument(doc, e)}>×</button>}</div></div></article>
                    })}
                  </div>
                  {filteredDocuments.length > 5 && <button type="button" className="show-more-files-button" onClick={() => setShowAllDocuments(value => !value)}>{showAllDocuments ? 'Show fewer files' : `Show all ${filteredDocuments.length} files`}</button>}
                </div>
              ) : (
                <div className="system-workspace-pane">
  <section className="system-check-card">
    <p className="eyebrow">System status</p>

    <h3>
      {systemCheckResult?.status === "ready"
        ? "University AI is ready"
        : systemCheckResult?.status === "needs_attention"
          ? "Needs attention"
          : "System check has not run"}
    </h3>

    <p>
      One check confirms backend health, database connections,
      AI routing rules, report flow, and data consistency.
    </p>

    <button
      type="button"
      className="upload-primary-button"
      onClick={runSystemCheck}
      disabled={systemCheckRunning}
    >
      {systemCheckRunning ? "Checking system…" : "Run system check"}
    </button>

    {systemCheckResult && (
      <div className="system-check-result">
        <strong>
          {systemCheckResult.summary?.passed || 0}/
          {systemCheckResult.summary?.total || 0} checks passed
        </strong>

        <div className="system-check-list">
          {(systemCheckResult.checks || []).map((check) => (
            <div
              key={check.name}
              className={`system-check-row ${check.ok ? "ok" : "failed"}`}
            >
              <span>{check.ok ? "✓" : "!"}</span>
              <div>
                <strong>{check.name}</strong>
                {!check.ok && check.message && (
                  <small>{check.message}</small>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    )}
  </section>

  <details className="system-accordion">
    <summary>
      <span>Advanced maintenance</span>
      <small>Admin only</small>
    </summary>

    <p>
      Use these only after a system check identifies a specific issue.
    </p>

    <button
      type="button"
      className="mini-action-button"
      onClick={trainSemanticDataAgents}
      disabled={semanticTraining}
    >
      {semanticTraining ? "Updating…" : "Refresh search index"}
    </button>

    <button
      type="button"
      className="mini-action-button"
      onClick={trainNeuralRouter}
      disabled={neuralRouterTraining}
    >
      {neuralRouterTraining ? "Training…" : "Train AI router"}
    </button>

    <button
      type="button"
      className="mini-action-button"
      onClick={reindexExistingDataAgents}
      disabled={reindexingAgents}
    >
      {reindexingAgents ? "Updating…" : "Repair data indexes"}
    </button>

    <button
      type="button"
      className="text-action-button"
      onClick={() => setDebugPanelOpen(true)}
    >
      Open technical trace
    </button>
  </details>
</div>
              )}
            </aside>
          )}
        </div>
      )}
      {userRole === 'admin' && renderDebugTracePanel()}
    </>
  )
}
