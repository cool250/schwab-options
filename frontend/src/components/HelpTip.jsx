import { useState, useEffect, useRef, useId } from 'react'

/**
 * Small "?" button that opens an explanatory pop-up beside a form label —
 * for help text that would otherwise sit as a paragraph under the form.
 * Click to toggle; closes on an outside click or Escape.
 *
 * Props:
 *   label    — accessible name for the button (e.g. "About moneyness")
 *   children — the pop-up's content
 */
export default function HelpTip({ label, children }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const popupId = useId()

  useEffect(() => {
    if (!open) return
    function onPointerDown(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    function onKeyDown(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <span className="help-tip" ref={ref}>
      <button
        type="button"
        className="help-tip-button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={popupId}
        onClick={() => setOpen((o) => !o)}
      >
        ?
      </button>
      {open && (
        <span id={popupId} role="tooltip" className="help-tip-popup">
          {children}
        </span>
      )}
    </span>
  )
}
