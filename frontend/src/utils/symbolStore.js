import { registerSessionReset } from "./sessionCaches";

// Shared "currently selected symbol" between Analyze (StrikeLab) and Charts,
// so picking a symbol on one page carries over to the other next time it's
// visited, instead of each page drifting independently. Plain module state,
// not React context: each page already keeps its own remount-persistence
// cache this same way, and the two pages are never mounted at once (routes
// are exclusive) so nothing needs to react live to a change here.
//
// Starts at SPY (and goes back to it on sign-in/out) so neither page opens
// blank; the user's own pick replaces it from then on.
export const DEFAULT_SYMBOL = "SPY";

export const symbolStore = { symbol: DEFAULT_SYMBOL };

registerSessionReset(() => { symbolStore.symbol = DEFAULT_SYMBOL; });
