import { useState } from 'react'
import './login-style.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

export default function LoginPage({ onLogin }) {
    const [role, setRole] = useState('student')
    const [userId, setUserId] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError('')
        setLoading(true)

        // Validate inputs
        if (!userId.trim()) {
            setError('Please enter your ID')
            setLoading(false)
            return
        }
        if (!password.trim()) {
            setError('Please enter your password')
            setLoading(false)
            return
        }

        try {
            // Call authentication endpoint
            const res = await fetch(`${API_BASE}/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    role: role,
                    user_id: userId,
                    password: password
                })
            })

            const data = await res.json()

            if (!res.ok) {
                setError(data.detail || 'Login failed')
                setLoading(false)
                return
            }

            // Call parent onLogin with user info
            onLogin({
                role: data.role,
                studentId: data.student_id || '',
                advisorId: data.advisor_id || '',
                sessionId: data.session_id || '',
                name: data.name,
                accessToken: data.access_token || ''
            })
        } catch (error) {
            setError(`Connection error: ${error.message}`)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="login-container">
            <div className="login-box">
                <div className="login-header">
                    <h1>🎓 University Portal</h1>
                    <p>MCP Agent AI System</p>
                </div>

                <form onSubmit={handleSubmit} className="login-form">
                    <div className="form-group">
                        <label htmlFor="role">I am a:</label>
                        <select
                            id="role"
                            value={role}
                            onChange={(e) => setRole(e.target.value)}
                            className="form-input"
                        >
                            <option value="student">Student</option>
                            <option value="advisor">Advisor</option>
                            <option value="admin">Administrator</option>
                        </select>
                    </div>

                    <div className="form-group">
                        <label htmlFor="userId">
                            {role === 'student' ? 'Student ID' : role === 'advisor' ? 'Advisor ID' : 'Admin ID'}:
                        </label>
                        <input
                            id="userId"
                            type="text"
                            value={userId}
                            onChange={(e) => setUserId(e.target.value)}
                            placeholder="Enter your ID"
                            className="form-input"
                            disabled={loading}
                        />
                    </div>

                    <div className="form-group">
                        <label htmlFor="password">Password:</label>
                        <input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="Enter your password"
                            className="form-input"
                            disabled={loading}
                        />
                    </div>

                    {error && <div className="error-message">{error}</div>}

                    <button
                        type="submit"
                        className="login-button"
                        disabled={loading}
                    >
                        {loading ? 'Logging in...' : 'Login'}
                    </button>
                </form>

                <div className="login-footer">
                    <p><strong>V30 local demo only</strong></p>
                    <small>Student: S001 &nbsp; Password: demo1234</small>
                    <br />
                    <small>Advisor: A001 &nbsp; Password: demo1234</small>
                    <p>
                        <small>
                            Fresh V30 demo: Administrator ID <strong>ADMIN</strong> / password <strong>admin123</strong>.
                            Existing database administrator accounts keep their own password. Use
                            <strong> RECOVER_ADMIN_V30.bat</strong> only if you need to reset it.
                        </small>
                    </p>
                </div>
            </div>
        </div>
    )
}
