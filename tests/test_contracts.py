"""Contract multipliers are defined twice — Python (service/shared/contracts.py)
and the browser (frontend/src/utils/contractMultiplier.js). Keep them equal:
a root missing on one side silently values its P&L at 100 per point."""

import re
from pathlib import Path

from service.shared.contracts import CONTRACT_MULTIPLIER

JS = Path(__file__).resolve().parent.parent / "frontend/src/utils/contractMultiplier.js"


def test_python_and_browser_multipliers_match():
    body = re.search(r"FUTURES_MULTIPLIER_BY_ROOT\s*=\s*\{([^}]*)\}", JS.read_text()).group(1)
    js = {k: int(v) for k, v in re.findall(r"(\w+)\s*:\s*(\d+)", body)}
    assert js == CONTRACT_MULTIPLIER
