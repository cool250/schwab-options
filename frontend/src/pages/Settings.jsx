import { useTheme } from '../context/ThemeContext'

const THEMES = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

export default function Settings() {
  const { theme, setTheme } = useTheme()

  return (
    <div className="page">
      <div className="card">
        <h3 className="section-title">Appearance</h3>
        {/* Applies immediately and is remembered on this browser
            (ThemeContext persists it to localStorage). */}
        <fieldset className="settings-field">
          <legend>Theme</legend>
          <div className="settings-options">
            {THEMES.map((t) => (
              <label key={t.value} className="toggle-label">
                <input
                  type="radio"
                  name="theme"
                  className="toggle-checkbox"
                  value={t.value}
                  checked={theme === t.value}
                  onChange={() => setTheme(t.value)}
                />
                <span>{t.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
    </div>
  )
}
