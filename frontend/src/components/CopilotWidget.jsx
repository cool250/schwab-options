import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { sendCopilotMessage } from "../api/client";

// Mounted once at the App level (see App.jsx), outside the routed <main> —
// it never unmounts on navigation, so conversation state just lives in this
// component's own state for as long as the tab is open. Resets on a full
// page reload, matching the "in-memory only" chat-history decision —
// nothing is persisted server-side.
export default function CopilotWidget() {
  const [open, setOpen] = useState(false);
  const [fullPage, setFullPage] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, open]);

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
      const result = await sendCopilotMessage(nextMessages);
      setMessages([...nextMessages, { role: "assistant", content: result.reply, toolsUsed: result.tools_used }]);
    } catch (err) {
      console.error("Copilot request failed:", err);
      setError(err.message || "Copilot request failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      send(e);
    }
  };

  return (
    <div className={`copilot-widget${fullPage ? " full-page" : ""}`}>
      {open && fullPage && <div className="copilot-backdrop" onClick={() => setFullPage(false)} />}
      {open && (
        <div className="copilot-panel card">
          <div className="copilot-panel-header">
            <span>Copilot</span>
            <div className="copilot-panel-header-actions">
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
                  <div className="copilot-bubble">
                    {m.role === "assistant" ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                    ) : (
                      m.content
                    )}
                  </div>
                  {m.toolsUsed?.length > 0 && (
                    <div className="copilot-tools-used">
                      {m.toolsUsed.map((t, j) => (
                        <span key={j} className="copilot-tool-chip">{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
            {loading && (
              <div className="copilot-msg assistant">
                <div className="copilot-bubble">
                  <span className="spinner spinner-sm" title="Thinking…" />
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

      {!(open && fullPage) && (
      <button
        type="button"
        className="copilot-launcher"
        onClick={() => {
          if (open) setFullPage(false);
          setOpen((o) => !o);
        }}
        aria-label={open ? "Close copilot" : "Open copilot"}
      >
        {open ? "×" : "💬"}
      </button>
      )}
    </div>
  );
}
