import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  changePassword, updateProfile, listUsers, createUser, resetUserPassword, setUserDisabled, deleteUser,
} from '../api/client'
import DataTable from './DataTable'

const MIN_PASSWORD = 8 // matches api/users.py MIN_PASSWORD_LENGTH

// A random 14-character password for the admin to hand to a friend
// (no look-alike characters: 0/O, 1/l/I).
function generatePassword() {
  const chars = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  const bytes = crypto.getRandomValues(new Uint8Array(14))
  return Array.from(bytes, (b) => chars[b % chars.length]).join('')
}

// "Ada Lovelace", or whichever part is set; null when neither is.
function fullName(u) {
  return [u?.firstName, u?.lastName].filter(Boolean).join(' ') || null
}

/** Settings → Account: who's signed in, your optional profile, and change
 *  your own password. */
export function AccountCard() {
  const { user, login, updateUser } = useAuth()
  const [profile, setProfile] = useState({ firstName: '', lastName: '', email: '' })
  const [savingProfile, setSavingProfile] = useState(false)
  const [profileMessage, setProfileMessage] = useState(null) // {tone, text}
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null) // {tone, text}

  // Fill the form once the signed-in user has loaded (AuthContext fetches it).
  useEffect(() => {
    if (user) setProfile({ firstName: user.firstName ?? '', lastName: user.lastName ?? '', email: user.email ?? '' })
  }, [user?.id])

  async function handleProfileSubmit(e) {
    e.preventDefault()
    setSavingProfile(true)
    setProfileMessage(null)
    try {
      const updated = await updateProfile(profile)
      updateUser(updated)
      setProfileMessage({ tone: 'success', text: 'Profile saved.' })
    } catch (err) {
      setProfileMessage({ tone: 'error', text: err.message || 'Could not save profile.' })
    } finally {
      setSavingProfile(false)
    }
  }

  const setField = (field) => (e) => setProfile((p) => ({ ...p, [field]: e.target.value }))

  async function handleSubmit(e) {
    e.preventDefault()
    if (next.length < MIN_PASSWORD) return setMessage({ tone: 'error', text: `New password must be at least ${MIN_PASSWORD} characters.` })
    if (next !== confirm) return setMessage({ tone: 'error', text: "New passwords don't match." })
    setSaving(true)
    setMessage(null)
    try {
      // Changing it signs out other sessions; the response carries a fresh
      // token so this one stays signed in.
      const { token } = await changePassword(current, next)
      login(token, user)
      setCurrent(''); setNext(''); setConfirm('')
      setMessage({ tone: 'success', text: 'Password changed. Other sessions have been signed out.' })
    } catch (err) {
      setMessage({ tone: 'error', text: err.message || 'Could not change password.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <h3 className="section-title">Account</h3>
      {user && (
        <p className="summary-line">
          Signed in as <strong>{user.username}</strong>{fullName(user) ? ` (${fullName(user)})` : ''}{user.isAdmin ? ' · Admin' : ''}
        </p>
      )}

      <h4 className="settings-subtitle">Profile <span className="text-muted">(optional)</span></h4>
      <form onSubmit={handleProfileSubmit} className="settings-password-form">
        <div className="form-group">
          <label htmlFor="profile-first">First name</label>
          <input id="profile-first" className="input" autoComplete="given-name" maxLength={50}
            value={profile.firstName} onChange={setField('firstName')} />
        </div>
        <div className="form-group">
          <label htmlFor="profile-last">Last name</label>
          <input id="profile-last" className="input" autoComplete="family-name" maxLength={50}
            value={profile.lastName} onChange={setField('lastName')} />
        </div>
        <div className="form-group">
          <label htmlFor="profile-email">Email</label>
          <input id="profile-email" type="email" className="input" autoComplete="email" maxLength={254}
            value={profile.email} onChange={setField('email')} />
        </div>
        <div>
          <button type="submit" className="btn btn-primary" disabled={savingProfile || !user}>
            {savingProfile ? 'Saving…' : 'Save profile'}
          </button>
        </div>
      </form>
      {profileMessage && <div className={`alert ${profileMessage.tone}`}>{profileMessage.text}</div>}

      <h4 className="settings-subtitle">Change password</h4>
      <form onSubmit={handleSubmit} className="settings-password-form">
        <div className="form-group">
          <label htmlFor="pw-current">Current password</label>
          <input id="pw-current" type="password" className="input" autoComplete="current-password"
            value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </div>
        <div className="form-group">
          <label htmlFor="pw-new">New password</label>
          <input id="pw-new" type="password" className="input" autoComplete="new-password"
            value={next} onChange={(e) => setNext(e.target.value)} required />
        </div>
        <div className="form-group">
          <label htmlFor="pw-confirm">Confirm new password</label>
          <input id="pw-confirm" type="password" className="input" autoComplete="new-password"
            value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </div>
        <div>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Saving…' : 'Change password'}
          </button>
        </div>
      </form>
      {message && <div className={`alert ${message.tone}`}>{message.text}</div>}
    </div>
  )
}

/** Settings → Users (admins only): create accounts, reset passwords,
 *  enable/disable, delete. There's no self-service sign-up. */
export function UsersCard() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newIsAdmin, setNewIsAdmin] = useState(false)
  const [newProfile, setNewProfile] = useState({ firstName: '', lastName: '', email: '' })
  const [resetting, setResetting] = useState(null) // user being given a new password
  const [resetPassword, setResetPassword] = useState('')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    try {
      setUsers(await listUsers())
    } catch (err) {
      setError(err.message || 'Could not load users.')
    }
  }

  useEffect(() => { refresh() }, [])

  async function run(action, successText) {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await action()
      if (successText) setNotice(successText)
      await refresh()
      return true
    } catch (err) {
      setError(err.message || 'Something went wrong.')
      return false
    } finally {
      setBusy(false)
    }
  }

  async function handleCreate(e) {
    e.preventDefault()
    const username = newUsername.trim()
    const password = newPassword
    const created = await run(
      () => createUser(username, password, newIsAdmin, newProfile),
      `Created ${username}. Send them their username and password: ${password}`,
    )
    if (created) {
      setNewUsername(''); setNewPassword(''); setNewIsAdmin(false)
      setNewProfile({ firstName: '', lastName: '', email: '' })
    }
  }

  async function handleReset(e) {
    e.preventDefault()
    const target = resetting
    const password = resetPassword
    const done = await run(
      () => resetUserPassword(target.id, password),
      `New password for ${target.username}: ${password} — they've been signed out.`,
    )
    if (done) { setResetting(null); setResetPassword('') }
  }

  function handleDelete(u) {
    if (!window.confirm(`Delete ${u.username}? This removes their account and their Schwab connection.`)) return
    run(() => deleteUser(u.id), `Deleted ${u.username}.`)
  }

  const columns = [
    { key: 'username', label: 'Username', render: (u) => <strong>{u.username}</strong> },
    { key: 'name', label: 'Name', render: (u) => u.name ?? <span className="text-muted">—</span> },
    { key: 'email', label: 'Email', render: (u) => u.email ?? <span className="text-muted">—</span> },
    { key: 'isAdmin', label: 'Role', render: (u) => (u.isAdmin ? 'Admin' : 'User') },
    {
      key: 'disabled',
      label: 'Status',
      render: (u) => <span className={u.disabled ? 'settings-status--error' : 'settings-status--ok'}>{u.disabled ? 'Disabled' : 'Active'}</span>,
    },
    { key: 'createdAt', label: 'Created', render: (u) => new Date(u.createdAt * 1000).toLocaleDateString('en-US') },
    {
      // Not a row field, so DataTable leaves it unsortable.
      key: 'actions',
      label: '',
      render: (u) => (
        <div className="settings-user-actions">
          <button type="button" className="btn btn-secondary settings-btn-sm" disabled={busy}
            onClick={() => { setResetting(u); setResetPassword(generatePassword()); setNotice(null) }}>
            Reset password
          </button>
          {u.id !== me?.id && (
            <>
              <button type="button" className="btn btn-secondary settings-btn-sm" disabled={busy}
                onClick={() => run(() => setUserDisabled(u.id, !u.disabled), `${u.disabled ? 'Enabled' : 'Disabled'} ${u.username}.`)}>
                {u.disabled ? 'Enable' : 'Disable'}
              </button>
              {u.id !== 1 && (
                <button type="button" className="btn btn-secondary settings-btn-sm settings-btn-danger" disabled={busy}
                  onClick={() => handleDelete(u)}>
                  Delete
                </button>
              )}
            </>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="card">
      <h3 className="section-title">Users</h3>
      <p className="summary-line">
        Friends get their own login and connect their own Schwab account; market data is shared. Only admins see
        this section and the Copilot.
      </p>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert success">{notice}</div>}

      <form onSubmit={handleCreate} className="settings-user-form">
        <div className="form-group">
          <label htmlFor="new-username">New username</label>
          <input id="new-username" className="input" autoComplete="off" value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)} required />
        </div>
        <div className="form-group">
          <label htmlFor="new-password">Password</label>
          <div className="settings-password-row">
            <input id="new-password" className="input" autoComplete="new-password" value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)} minLength={MIN_PASSWORD} required />
            <button type="button" className="btn btn-secondary settings-btn-sm" onClick={() => setNewPassword(generatePassword())}>
              Generate
            </button>
          </div>
        </div>
        <div className="form-group">
          <label htmlFor="new-first">First name <span className="text-muted">(optional)</span></label>
          <input id="new-first" className="input" autoComplete="off" maxLength={50} value={newProfile.firstName}
            onChange={(e) => setNewProfile((p) => ({ ...p, firstName: e.target.value }))} />
        </div>
        <div className="form-group">
          <label htmlFor="new-last">Last name <span className="text-muted">(optional)</span></label>
          <input id="new-last" className="input" autoComplete="off" maxLength={50} value={newProfile.lastName}
            onChange={(e) => setNewProfile((p) => ({ ...p, lastName: e.target.value }))} />
        </div>
        <div className="form-group">
          <label htmlFor="new-email">Email <span className="text-muted">(optional)</span></label>
          <input id="new-email" type="email" className="input" autoComplete="off" maxLength={254} value={newProfile.email}
            onChange={(e) => setNewProfile((p) => ({ ...p, email: e.target.value }))} />
        </div>
        <label className="toggle-label">
          <input type="checkbox" className="toggle-checkbox" checked={newIsAdmin} onChange={(e) => setNewIsAdmin(e.target.checked)} />
          <span>Admin</span>
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy}>Create user</button>
      </form>

      {resetting && (
        <form onSubmit={handleReset} className="settings-user-form settings-reset-form">
          <div className="form-group">
            <label htmlFor="reset-password">New password for {resetting.username}</label>
            <div className="settings-password-row">
              <input id="reset-password" className="input" value={resetPassword}
                onChange={(e) => setResetPassword(e.target.value)} minLength={MIN_PASSWORD} required />
              <button type="button" className="btn btn-secondary settings-btn-sm" onClick={() => setResetPassword(generatePassword())}>
                Generate
              </button>
            </div>
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy}>Set password</button>
          <button type="button" className="btn btn-secondary" onClick={() => setResetting(null)}>Cancel</button>
        </form>
      )}

      {users && (
        <DataTable
          // `name` is a real field so the Name column sorts.
          data={users.map((u) => ({ ...u, name: fullName(u) }))}
          columns={columns}
          defaultSortKey="username"
        />
      )}
    </div>
  )
}
