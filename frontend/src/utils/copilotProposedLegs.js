// One-way bridge FROM the copilot chat TO StrikeLab — the mirror of
// copilotContext.js, which flows the other way (page -> copilot). Plain
// module state rather than React context, same reasoning as
// copilotContext.js: CopilotWidget is mounted once at the App level,
// outside the routed content (see App.jsx), with no natural prop path down
// into StrikeLab.
//
// Two ways StrikeLab picks up an applied set of legs, covering both cases
// clicking "Apply" can hit:
//  - Already on StrikeLab: the "applied" event, listened for while mounted.
//  - Navigating to StrikeLab (from another page, or opening it fresh) after
//    applying: consumePendingLegs(), checked once on mount — the event
//    above would otherwise have already fired before StrikeLab's listener
//    existed to hear it.
const EVENT = "copilot-legs-applied";
let pending = null;

export function applyProposedLegs(legs) {
  pending = legs;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: legs }));
}

export function consumePendingLegs() {
  const legs = pending;
  pending = null;
  return legs;
}

export function onLegsApplied(handler) {
  const listener = (e) => handler(e.detail);
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
