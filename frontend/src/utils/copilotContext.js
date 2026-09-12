// Shared "what is the user currently looking at" context, read by
// CopilotWidget when sending a message so the agent can answer questions
// about the position/page in front of the user (e.g. "explain this spread",
// "is this a good risk/reward" on StrikeLab) without them having to restate
// every strike and price by hand.
//
// Plain module state, not React context: CopilotWidget is mounted once at
// the App level outside the routed content (see App.jsx) and has no natural
// prop path down into a page's own state — same rationale as symbolStore.
// A page sets this whenever its relevant state changes and clears it on
// unmount; CopilotWidget just reads whatever's here at send-time.
export const copilotContext = { page: null, data: null };

export function setCopilotContext(page, data) {
  copilotContext.page = page;
  copilotContext.data = data;
}

// Guarded by page so an unmounting page can't clobber context a newer page
// already set (e.g. a delayed cleanup effect racing a fast navigation).
export function clearCopilotContext(page) {
  if (copilotContext.page === page) {
    copilotContext.page = null;
    copilotContext.data = null;
  }
}
