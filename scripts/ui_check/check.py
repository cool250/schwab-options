"""Screenshot every page at phone, tablet and desktop widths, in light and
dark, and fail if any page scrolls sideways.

    cd frontend && npm run build && cd ..
    uv run python -m scripts.ui_check.demo_server &      # sample data, port 8765
    uv run python -m scripts.ui_check.check --out /tmp/ui-check

Runs against scripts/ui_check/demo_server.py (the real app on sample
brokers), so the screenshots never show a real account. A page "scrolls
sideways" when the document is wider than the window; the report names the
elements sticking out past the right edge (anything inside its own
horizontally scrolling box, like a wide table's wrapper, doesn't count).

First run: uv run playwright install chromium
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.ui_check.demo_server import DEMO_PASSWORD, DEMO_USER

SUBMIT = "form button[type=submit]:visible >> nth=0"
# (name, path, clicks): each view is a page plus the clicks that fill it in
# (a tab, a search) — the clicks run in order after the page loads.
VIEWS = [
    ("home", "/home", []),
    ("positions-futures", "/positions", []),
    ("positions-equity", "/positions", [".tab-item:has-text('Equity')"]),
    ("transactions-options", "/transactions", [SUBMIT]),
    ("transactions-equity", "/transactions", [".tab-item:has-text('Equity')", SUBMIT]),
    ("reports", "/allocation", []),
    ("analyze", "/analyze", []),
    ("charts", "/charts", []),
    ("screener", "/screener", [SUBMIT]),
    ("settings", "/settings", []),
]
PUBLIC_VIEWS = [("landing", "/", []), ("login", "/login", [])]
WIDTHS = [375, 390, 768, 1280, 1440]
THEMES = ["light", "dark"]

# Elements whose right edge passes the window's, skipping any inside a box
# that scrolls sideways itself — that's contained, not page overflow.
OVERFLOW_JS = """() => {
  const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth <= vw) return null;
  const clipped = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') return true;
    }
    return false;
  };
  const name = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    [...el.classList].slice(0, 3).map((c) => '.' + c).join('');
  const out = [];
  for (const el of document.body.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width && r.right > vw + 1 && !clipped(el)) {
      // Report the outermost offender only, not every child inside it.
      if (!out.some((o) => o.el.contains(el))) out.push({ el, right: Math.round(r.right) });
    }
  }
  return { width: document.documentElement.scrollWidth, viewport: vw,
           offenders: out.slice(0, 6).map((o) => `${name(o.el)} (to ${o.right}px)`) };
}"""


def login(base: str) -> str:
    req = urllib.request.Request(
        f"{base}/api/auth/login", data=json.dumps({"username": DEMO_USER, "password": DEMO_PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as res:
        return json.load(res)["token"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, help="Folder for screenshots (none taken without it)")
    parser.add_argument("--widths", default=",".join(map(str, WIDTHS)))
    parser.add_argument("--themes", default=",".join(THEMES))
    parser.add_argument("--views", help="Comma-separated view names (default: all) — " +
                        ", ".join(n for n, _, _ in VIEWS + PUBLIC_VIEWS))
    parser.add_argument("--settle-ms", type=int, default=1500, help="Wait after load for data and charts")
    args = parser.parse_args()

    widths = [int(w) for w in args.widths.split(",")]
    themes = args.themes.split(",")
    wanted = set(args.views.split(",")) if args.views else None
    token = login(args.base)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in themes:
            for width in widths:
                for public in (False, True):
                    views = [v for v in (PUBLIC_VIEWS if public else VIEWS) if wanted is None or v[0] in wanted]
                    if not views:
                        continue
                    ctx = browser.new_context(viewport={"width": width, "height": 844 if width < 768 else 1000},
                                              device_scale_factor=2 if width < 768 else 1,
                                              is_mobile=width < 768, has_touch=width < 1024)
                    setup = f"localStorage.setItem('theme', {json.dumps(theme)});"
                    if not public:
                        setup += (f"sessionStorage.setItem('auth_token', {json.dumps(token)});"
                                  "sessionStorage.setItem('auth_token_issued', String(Date.now()));")
                    ctx.add_init_script(setup)
                    page = ctx.new_page()
                    for name, path, clicks in views:
                        page.goto(args.base + path, wait_until="networkidle")
                        page.wait_for_timeout(args.settle_ms)
                        for selector in clicks:
                            page.locator(selector).first.click()
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(args.settle_ms)
                        overflow = page.evaluate(OVERFLOW_JS)
                        label = f"{name} @ {width}px {theme}"
                        if overflow:
                            failures.append((label, overflow))
                        if args.out:
                            page.screenshot(path=args.out / f"{name}-{width}-{theme}.png", full_page=True)
                        print(("SCROLLS SIDEWAYS  " if overflow else "ok                ") + label)
                    ctx.close()
        browser.close()

    if failures:
        print(f"\n{len(failures)} page view(s) scroll sideways:")
        for label, o in failures:
            print(f"  {label}: {o['width']}px wide in a {o['viewport']}px window — {', '.join(o['offenders']) or 'no single element'}")
        return 1
    print("\nNo page scrolls sideways.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
