"""Portfolio code must never reach Tastytrade. Prices Schwab can't provide
come from the Market quotes endpoint and are combined in the page (see
docs/portfolio-market-separation-plan.md). Checked statically, by parsing
every Portfolio module's imports."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_DIRS = ["service/portfolio", "api/portfolio"]
# `service` itself re-exports MarketService, so `from service import …`
# would load Market code too.
FORBIDDEN = ("broker.tastytrade", "service.market", "api.market")


def _imports(path: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
            if node.module in ("service", "api", "broker"):
                names += [f"{node.module}.{a.name}" for a in node.names]
    return names


PORTFOLIO_FILES = sorted(p for d in PORTFOLIO_DIRS for p in (ROOT / d).rglob("*.py"))


def test_portfolio_files_found():
    assert len(PORTFOLIO_FILES) > 5


@pytest.mark.parametrize("path", PORTFOLIO_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_portfolio_never_imports_market(path):
    bad = [n for n in _imports(path) if n == "service" or any(n == f or n.startswith(f + ".") for f in FORBIDDEN)]
    assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_market_never_imports_portfolio():
    for path in sorted((ROOT / "service/market").rglob("*.py")) + sorted((ROOT / "api/market").rglob("*.py")):
        bad = [n for n in _imports(path) if n.startswith(("service.portfolio", "api.portfolio", "broker.schwab"))]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"
