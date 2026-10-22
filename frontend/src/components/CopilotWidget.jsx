import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sendCopilotMessage, friendlyErrorMessage, isSystemError } from "../api/client";
import { copilotContext } from "../utils/copilotContext";
import { applyProposedLegs } from "../utils/copilotProposedLegs";

const MIN_WIDTH = 320;
const MAX_WIDTH = 1200;
const WIDTH_STORAGE_KEY = "copilot-width";

// Sparkle mark — the copilot's icon everywhere (title bar, message avatar,
// launcher). Same line style as the menu icons (NavIcons.jsx: 24×24 grid,
// stroke 2, currentColor); `size` defaults to their 18px.
export function CopilotIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M10 3l1.9 5.1L17 10l-5.1 1.9L10 17l-1.9-5.1L3 10l5.1-1.9z" />
      <path d="M18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9z" />
      <path d="M18 3v4M16 5h4" />
    </svg>
  )
}

function UserIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-4.4 3.6-7 8-7s8 2.6 8 7" />
    </svg>
  )
}

// Mounted once at the App level (see App.jsx), outside the routed <main> —
// it never unmounts on navigation, so conversation state just lives in this
// component's own state for as long as the tab is open. Resets on a full
// page reload, matching the "in-memory only" chat-history decision —
// nothing is persisted server-side.
// Shown instead of the widget to non-admin users: the same launcher,
// greyed out and inert. aria-disabled rather than `disabled` so the hover
// tooltip still appears (Chrome shows no title on a disabled button).
export function CopilotDisabledLauncher() {
  return (
    <div className="copilot-widget">
      <button
        type="button"
        className="copilot-launcher copilot-launcher--disabled"
        aria-disabled="true"
        aria-label="Copilot is available to admins only"
        title="Copilot is available to admins only"
      >
        <CopilotIcon size={22} />
        <span className="copilot-launcher-label">Ask Indu</span>
      </button>
    </div>
  );
}

export default function CopilotWidget() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [fullPage, setFullPage] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [resizing, setResizing] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, open]);

  // Docked (non-full-page) mode reserves space at the right edge so the
  // panel sits beside the app instead of over it; full-page mode is a
  // dimmed overlay instead, so it doesn't need the push.
  useEffect(() => {
    document.body.classList.toggle("copilot-open", open && !fullPage);
    return () => document.body.classList.remove("copilot-open");
  }, [open, fullPage]);

  // Restore a previously-dragged width — --copilot-width otherwise always
  // starts back at its CSS default (400px) on every page load.
  useEffect(() => {
    const stored = localStorage.getItem(WIDTH_STORAGE_KEY);
    if (stored) document.documentElement.style.setProperty("--copilot-width", `${stored}px`);
  }, []);

  // Dragging the panel's left edge to resize (docked mode only — see
  // .copilot-resize-handle in copilot.css). Updates the --copilot-width CSS
  // variable directly rather than component state, since both the panel's
  // own width and body's padding-right (which reserves space beside it)
  // already read from that one variable — no need to plumb a width prop
  // through both.
  useEffect(() => {
    if (!resizing) return;

    function handleMove(e) {
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, window.innerWidth - clientX));
      document.documentElement.style.setProperty("--copilot-width", `${width}px`);
    }
    function handleUp() {
      setResizing(false);
      const width = getComputedStyle(document.documentElement).getPropertyValue("--copilot-width").trim();
      if (width) localStorage.setItem(WIDTH_STORAGE_KEY, parseInt(width, 10));
    }

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    window.addEventListener("touchmove", handleMove);
    window.addEventListener("touchend", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
      window.removeEventListener("touchmove", handleMove);
      window.removeEventListener("touchend", handleUp);
    };
  }, [resizing]);

  useEffect(() => {
    document.body.classList.toggle("copilot-resizing", resizing);
    return () => document.body.classList.remove("copilot-resizing");
  }, [resizing]);

  const send = async (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    const nextMessages = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      // Read fresh at send-time (not captured earlier) so it reflects
      // whatever the user is looking at right now, even if they navigated
      // or edited the page since the widget was opened.
      const result = await sendCopilotMessage(nextMessages, copilotContext);
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: result.reply,
          toolsUsed: result.tools_used,
          proposedLegs: result.proposed_legs,
        },
      ]);
    } catch (err) {
      console.error("Copilot request failed:", err);
      // A 502 here is almost never a broker outage — /copilot/chat wraps every
      // failure (OpenAI quota, bad key, a tool error) as 502 with the real
      // cause in `detail`, so show that rather than the generic broker
      // "System error" message friendlyErrorMessage maps 502 to.
      setError(
        isSystemError(err) && err.message
          ? err.message
          : friendlyErrorMessage(err, err.message || "Copilot request failed.")
      );
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      send(e);
    }
  };

  // Drops the whole conversation so the next message starts with no prior
  // context — disabled while a request is in flight rather than aborting
  // it, since there's no AbortController wired up here and clearing
  // mid-request would otherwise let that response reappear afterward and
  // silently repopulate the "cleared" conversation.
  const handleNewChat = () => {
    setMessages([]);
    setError(null);
    setInput("");
  };

  // Hands the recommended legs to StrikeLab (see copilotProposedLegs.js)
  // and navigates there — works whether the user is already on StrikeLab
  // (the module's event listener picks it up directly) or somewhere else
  // (StrikeLab consumes the pending value once it mounts).
  const handleApplyLegs = (legs) => {
    applyProposedLegs(legs);
    navigate("/analyze");
  };

  return (
    <div className={`copilot-widget${fullPage ? " full-page" : ""}`}>
      {open && fullPage && <div className="copilot-backdrop" onClick={() => setFullPage(false)} />}
      {open && (
        <div className="copilot-panel card">
          {!fullPage && (
            <div
              className={`copilot-resize-handle${resizing ? " resizing" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); setResizing(true); }}
              onTouchStart={() => setResizing(true)}
              title="Drag to resize"
            />
          )}
          <div className="copilot-panel-header">
            <span className="copilot-panel-title"><CopilotIcon /> Copilot</span>
            <div className="copilot-panel-header-actions">
              <button
                type="button"
                className="copilot-panel-close"
                onClick={handleNewChat}
                disabled={loading || messages.length === 0}
                aria-label="Start new chat"
                title="Start new chat (clears this conversation)"
              >
                ＋
              </button>
              <button
                type="button"
                className="copilot-panel-close"
                onClick={() => setFullPage((f) => !f)}
                aria-label={fullPage ? "Exit full page" : "Open full page"}
                title={fullPage ? "Exit full page" : "Open full page"}
              >
                {fullPage ? "⤡" : "⤢"}
              </button>
              <button
                type="button"
                className="copilot-panel-close"
                onClick={() => {
                  setOpen(false);
                  setFullPage(false);
                }}
                aria-label="Close copilot"
              >
                ×
              </button>
            </div>
          </div>

          {error && <div className="alert error">{error}</div>}

          <div className="copilot-messages">
            {messages.length === 0 ? (
              <div className="copilot-empty">
                Ask about your positions, balances, recent trades, market prices, or options
                strategies — read-only, it can't place or change any trade.
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={`copilot-msg ${m.role}`}>
                  <div className="copilot-msg-row">
                    {m.role === "assistant" && (
                      <span className="copilot-msg-icon" aria-hidden="true"><CopilotIcon size={14} /></span>
                    )}
                    <div className="copilot-bubble">
                      {m.role === "assistant" ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                      ) : (
                        m.content
                      )}
                    </div>
                    {m.role === "user" && (
                      <span className="copilot-msg-icon" aria-hidden="true"><UserIcon /></span>
                    )}
                  </div>
                  {m.toolsUsed?.length > 0 && (
                    <div className="copilot-tools-used">
                      {m.toolsUsed.map((t, j) => (
                        <span key={j} className="copilot-tool-chip">{t}</span>
                      ))}
                    </div>
                  )}
                  {m.proposedLegs?.length > 0 && (
                    <button
                      type="button"
                      className="btn btn-primary copilot-apply-legs"
                      onClick={() => handleApplyLegs(m.proposedLegs)}
                    >
                      Apply Trade
                    </button>
                  )}
                </div>
              ))
            )}
            {loading && (
              <div className="copilot-msg assistant">
                <div className="copilot-msg-row">
                  <span className="copilot-msg-icon" aria-hidden="true"><CopilotIcon size={14} /></span>
                  <div className="copilot-bubble">
                    <span className="copilot-typing" title="Thinking…">
                      <span />
                      <span />
                      <span />
                    </span>
                  </div>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <form className="copilot-input-row" onSubmit={send}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your portfolio, the market, or an options strategy…"
              disabled={loading}
            />
            <button type="submit" className="btn btn-primary" disabled={loading || !input.trim()}>
              Send
            </button>
          </form>
        </div>
      )}

      {!open && (
      <button
        type="button"
        className="copilot-launcher"
        onClick={() => setOpen(true)}
        aria-label="Ask Indu"
      >
        <CopilotIcon size={22} />
        <span className="copilot-launcher-label">Ask Indu</span>
      </button>
      )}
    </div>
  );
}
