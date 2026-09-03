// Shared "currently selected symbol" between Analyze (StrikeLab) and Charts,
// so picking a symbol on one page carries over to the other next time it's
// visited, instead of each page drifting independently. Plain module state,
// not React context: each page already keeps its own remount-persistence
// cache this same way, and the two pages are never mounted at once (routes
// are exclusive) so nothing needs to react live to a change here.
//
// Starts empty rather than defaulting to some ticker — neither page should
// ever show or fetch data for a symbol the user didn't actually enter.
export const symbolStore = { symbol: "" };
