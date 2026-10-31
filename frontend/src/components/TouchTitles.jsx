import { useEffect, useState } from 'react'

const NO_HOVER = '(hover: none)'
// A tap on one of these does something already; its title stays a hint for
// a mouse and screen readers.
const INTERACTIVE = 'a, button, input, select, textarea, label, summary, [role="button"], [role="tab"]'

/**
 * Shows an element's `title` text when it's tapped, on screens without
 * hover — where the browser never shows a title at all. Mounted once
 * (App.jsx); does nothing with a mouse, so desktop keeps the native hover
 * tooltip. Closes on the next tap, a scroll, or after a few seconds.
 */
export default function TouchTitles() {
  const [tip, setTip] = useState(null) // { text, top, left }

  useEffect(() => {
    const media = window.matchMedia?.(NO_HOVER)
    if (!media?.matches) return

    let timer = null
    function close() {
      clearTimeout(timer)
      setTip(null)
    }
    function onClick(e) {
      const el = e.target.closest?.('[title]')
      if (!el || !el.getAttribute('title') || e.target.closest(INTERACTIVE)) return
      const r = el.getBoundingClientRect()
      const left = Math.min(Math.max(12, r.left), window.innerWidth - 332)
      const below = r.bottom + 8
      setTip({ text: el.getAttribute('title'), top: below > window.innerHeight - 120 ? null : below, bottom: window.innerHeight - r.top + 8, left: Math.max(12, left) })
      clearTimeout(timer)
      timer = setTimeout(close, 6000)
    }
    function onPointerDown(e) {
      if (!e.target.closest?.('[title]')) close()
    }
    document.addEventListener('click', onClick)
    document.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('scroll', close, { passive: true })
    return () => {
      clearTimeout(timer)
      document.removeEventListener('click', onClick)
      document.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('scroll', close)
    }
  }, [])

  if (!tip) return null
  const style = tip.top != null ? { top: tip.top, left: tip.left } : { bottom: tip.bottom, left: tip.left }
  return <div className="touch-title" role="tooltip" style={style}>{tip.text}</div>
}
