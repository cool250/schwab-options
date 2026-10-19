// Per-user, in-memory page state that must not outlive the user's session.
//
// Several pages keep a module-level cache so navigating away and back is
// instant (positionsCache, transactionsCache, …). Module state lives as long
// as the browser tab — so without this, signing out and signing in as a
// different user on the same tab would show the previous user's positions,
// transactions and reports. Every such cache is created through
// createSessionCache() (or registers a reset with registerSessionReset()),
// and AuthContext calls clearSessionCaches() on every login and logout.

const resets = new Set()

/** A cache object for page state, reset to `init()` whenever the session
 *  changes. `init` is a function so each reset builds fresh values (no Map
 *  or array shared with the previous user). */
export function createSessionCache(init) {
  const cache = init()
  resets.add(() => {
    for (const key of Object.keys(cache)) delete cache[key]
    Object.assign(cache, init())
  })
  return cache
}

/** For module state that isn't a plain cache object (a store, a pending
 *  value): register how to clear it. */
export function registerSessionReset(reset) {
  resets.add(reset)
}

export function clearSessionCaches() {
  for (const reset of resets) {
    try {
      reset()
    } catch {
      // never let one cache's reset block clearing the rest
    }
  }
}
