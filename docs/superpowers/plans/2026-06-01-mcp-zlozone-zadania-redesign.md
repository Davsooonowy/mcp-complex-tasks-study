# MCP — złożone zadania: redesign badania — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Przebudować badanie MCP w config-driven harness, który mierzy (a) wartość warstwy MCP przez porównanie z baseline bez MCP i lokalizację wiedzy schemat-vs-prompt (Część A), oraz (b) granicę zdolności agenta przy rosnącej liczbie narzędzi i złożoności zadania (Część B), z bogatymi metrykami i statystyką (N≥10, Wilson CI).

**Architecture:** Logika narzędzi i opisy (weak/rich) wydzielone do jednego modułu `tool_logic.py`, używanego zarówno przez serwisy FastMCP (transport stdio), jak i przez in-process narzędzia smolagents (baseline noMCP) — dzięki temu Część A izoluje *wyłącznie* warstwę transportu. Warunek eksperymentu to deklaratywny `Condition`; jeden runner uruchamia go N razy, liczy metryki z `agent.memory.steps` i zapisuje JSONL. Raport agreguje JSONL do tabel z przedziałami ufności.

**Tech Stack:** Python 3.13, smolagents 1.24.0 (`ToolCallingAgent`, `MCPClient`, `OpenAIServerModel`, `Tool`), FastMCP (stdio), pytest. Statystyka liczona ręcznie (math.erf) — bez scipy.

---

## Mapa plików

Katalog roboczy: `vulnerability_agent/`.

**Tworzone:**
- `tool_logic.py` — czysta logika 3 narzędzi + słowniki opisów weak/rich + inputs/schema. Źródło prawdy dla obu warstw dostarczania.
- `delivery/__init__.py`
- `delivery/local_tools.py` — fabryka in-process narzędzi smolagents (`Tool` subclass z dynamicznym `description`) — baseline noMCP.
- `delivery/mcp_tools.py` — budowa `StdioServerParameters` dla zadanego toolsetu i ich uruchomienie przez `MCPClient`.
- `metrics.py` — scoring odpowiedzi + ekstrakcja/agregacja metryk z `agent.memory.steps`.
- `stats.py` — Wilson CI, test dwóch proporcji (z), bez scipy.
- `config.py` — `Condition` (dataclass) + `TASK_TEMPLATES` + rejestry warunków A1/A2/A3/B1/B2 + `TOOLSETS`.
- `run_experiment.py` — `run_condition(cond, n)` → lista rekordów + zapis JSONL.
- `report.py` — czyta JSONL, generuje tabele z CI → `results_v3.md`.
- `services/distractors/*.py` — serwisy-dystraktory FastMCP (B1).
- `tests/` — testy jednostkowe (pytest).

**Modyfikowane:**
- `services/vulnerability_service.py`, `services/composition_service.py`, `services/project_service.py` — przepięte na `tool_logic` (DRY, usunięcie duplikacji opisów).
- `scenarios.py` — dodanie zestawu HARD + pól rozszerzonych metryk.
- `pyproject.toml` — dodanie `pytest` (dev).

**Archiwizowane:**
- `results.md` → `archive/results_v1_v2.md` (na końcu).

**Pozostają nietknięte (legacy, do usunięcia po migracji):** `agent.py`, `agent_mcp.py`, `agent_mcp_v2.py`, `run_*.py`, `stubs/`. Usunięcie w ostatnim zadaniu sprzątającym.

---

## Faza 0 — Przygotowanie

### Task 0: pytest jako zależność deweloperska

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Dodaj pytest do zależności dev**

W `pyproject.toml` dopisz po sekcji `dependencies`:

```toml
[dependency-groups]
dev = ["pytest>=8.0"]
```

- [ ] **Step 2: Zainstaluj**

Run: `uv sync --dev`
Expected: pytest zainstalowany w `.venv`.

- [ ] **Step 3: Zweryfikuj**

Run: `.venv/bin/python -c "import pytest; print(pytest.__version__)"`
Expected: wersja >= 8.0, brak błędu.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: dodaj pytest (dev)"
```

---

## Faza 1 — Czysta logika narzędzi (źródło prawdy)

### Task 1: Porównywanie wersji semver i severity

**Files:**
- Create: `vulnerability_agent/tool_logic.py`
- Test: `vulnerability_agent/tests/test_tool_logic.py`

- [ ] **Step 1: Test porównania wersji i severity**

```python
# vulnerability_agent/tests/test_tool_logic.py
from vulnerability_agent.tool_logic import version_below, severity_for


def test_version_below_true_when_lower():
    assert version_below("3.1.4", "3.2.0") is True

def test_version_below_false_when_equal_boundary():
    # próg "affected < 3.2.0": dokładnie 3.2.0 NIE jest podatna
    assert version_below("3.2.0", "3.2.0") is False

def test_version_below_false_when_higher():
    assert version_below("3.2.1", "3.2.0") is False

def test_version_below_handles_double_digit_segments():
    assert version_below("3.10.0", "3.9.0") is False
    assert version_below("3.2.0", "3.10.0") is True

def test_severity_thresholds():
    assert severity_for(9.8) == "CRITICAL"
    assert severity_for(9.0) == "CRITICAL"
    assert severity_for(7.5) == "HIGH"
    assert severity_for(4.0) == "MEDIUM"
    assert severity_for(2.0) == "LOW"
```

- [ ] **Step 2: Uruchom — ma nie przejść**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_tool_logic.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` (brak `tool_logic`).

- [ ] **Step 3: Implementacja**

```python
# vulnerability_agent/tool_logic.py
"""Czysta logika trzech narzędzi korelacji + opisy weak/rich.

Źródło prawdy współdzielone przez serwisy FastMCP (transport MCP/stdio)
oraz in-process narzędzia smolagents (baseline bez MCP). Dzięki temu
porównanie 'MCP vs nie-MCP' izoluje wyłącznie warstwę transportu —
logika i opisy są identyczne po obu stronach.
"""
from __future__ import annotations


def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def version_below(version: str, affected_below: str) -> bool:
    """True, gdy `version` < `affected_below` (czyli wersja podatna).

    Próg jest wyłączny: wersja równa progowi NIE jest podatna.
    """
    return _parse(version) < _parse(affected_below)


def severity_for(cvss: float) -> str:
    if cvss >= 9.0:
        return "CRITICAL"
    if cvss >= 7.0:
        return "HIGH"
    if cvss >= 4.0:
        return "MEDIUM"
    return "LOW"
```

- [ ] **Step 4: Uruchom — ma przejść**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_tool_logic.py -v`
Expected: PASS (wszystkie 6).

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/tool_logic.py vulnerability_agent/tests/test_tool_logic.py
git commit -m "feat: tool_logic — porównanie wersji semver i severity"
```

### Task 2: Implementacje trzech narzędzi (na słowniku scenariusza)

**Files:**
- Modify: `vulnerability_agent/tool_logic.py`
- Test: `vulnerability_agent/tests/test_tool_logic.py`

- [ ] **Step 1: Testy implementacji narzędzi**

Dopisz do `tests/test_tool_logic.py`:

```python
from vulnerability_agent.tool_logic import (
    vulnerability_data, projects_for_library, project_details,
)

BASE = {
    "cvss_score": 9.8, "library_version": "3.1.4",
    "project_in_inventory": True, "environment": "production",
    "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}],
}

def test_vulnerability_data_known_cve():
    d = vulnerability_data(BASE, "CVE-2024-9999")
    assert d["library"] == "lib-json-parser"
    assert d["affected_versions_below"] == "3.2.0"
    assert d["cvss_score"] == 9.8
    assert d["severity"] == "CRITICAL"

def test_vulnerability_data_unknown_cve():
    d = vulnerability_data(BASE, "CVE-0000-0000")
    assert "error" in d

def test_projects_for_library_respects_inventory_when_enabled():
    sc = {**BASE, "project_in_inventory": False}
    d = projects_for_library(sc, "lib-json-parser", respect_inventory=True)
    assert d["projects"] == []

def test_projects_for_library_ignores_inventory_when_disabled():
    # tryb niespójnego kontraktu (dawne COMP_VERSION=1)
    sc = {**BASE, "project_in_inventory": False}
    d = projects_for_library(sc, "lib-json-parser", respect_inventory=False)
    assert len(d["projects"]) == 1

def test_projects_for_library_unknown_lib_empty():
    d = projects_for_library(BASE, "other-lib", respect_inventory=True)
    assert d["projects"] == []

def test_project_details_known():
    d = project_details(BASE, "portal-abc")
    assert d["environment"] == "production"
    assert d["owner"] == "Jan Kowalski"

def test_project_details_not_in_inventory():
    sc = {**BASE, "project_in_inventory": False}
    d = project_details(sc, "portal-abc")
    assert "error" in d
```

- [ ] **Step 2: Uruchom — ma nie przejść**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_tool_logic.py -v`
Expected: FAIL — `ImportError` na nowych nazwach.

- [ ] **Step 3: Implementacja — dopisz do `tool_logic.py`**

```python
import json

CVE_ID = "CVE-2024-9999"
LIBRARY = "lib-json-parser"
AFFECTED_BELOW = "3.2.0"

_PROJECTS_DB = {
    "portal-abc": {"project_id": "portal-abc", "name": "Portal klienta ABC",
                   "client": "ABC Corp", "owner": "Jan Kowalski", "team": "Zespół Backend"},
    "api-xyz": {"project_id": "api-xyz", "name": "API Serwisowe XYZ",
                "client": "XYZ Ltd", "owner": "Anna Nowak", "team": "Zespół API"},
    "mobile-qrs": {"project_id": "mobile-qrs", "name": "Aplikacja mobilna QRS",
                   "client": "QRS S.A.", "owner": "Piotr Lis", "team": "Zespół Mobile"},
}


def vulnerability_data(scenario: dict, cve_id: str) -> dict:
    if cve_id != CVE_ID:
        return {"error": f"CVE {cve_id} not found in database"}
    cvss = scenario.get("cvss_score", 9.8)
    return {
        "cve_id": CVE_ID, "library": LIBRARY,
        "affected_versions_below": AFFECTED_BELOW,
        "cvss_score": cvss, "severity": severity_for(cvss),
        "description": "Remote code execution via malformed JSON input in lib-json-parser",
    }


def projects_for_library(scenario: dict, library_name: str, respect_inventory: bool = True) -> dict:
    if library_name != LIBRARY:
        return {"library": library_name, "projects": []}
    if respect_inventory and not scenario.get("project_in_inventory", True):
        return {"library": library_name, "projects": []}
    projects = scenario.get(
        "projects_using_lib",
        [{"project_id": "portal-abc", "library_version": scenario.get("library_version", "3.1.4")}],
    )
    return {"library": library_name, "projects": projects}


def project_details(scenario: dict, project_id: str) -> dict:
    if not scenario.get("project_in_inventory", True):
        return {"error": f"Project '{project_id}' not found in project inventory"}
    if project_id not in _PROJECTS_DB:
        return {"error": f"Project '{project_id}' not found"}
    project = dict(_PROJECTS_DB[project_id])
    # środowisko per-projekt: scenariusz może nadpisać globalnie lub per-id
    env_overrides = scenario.get("project_environments", {})
    project["environment"] = env_overrides.get(project_id, scenario.get("environment", "production"))
    return project
```

- [ ] **Step 4: Uruchom — ma przejść**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_tool_logic.py -v`
Expected: PASS (wszystkie testy z Task 1 i 2).

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/tool_logic.py vulnerability_agent/tests/test_tool_logic.py
git commit -m "feat: tool_logic — implementacje trzech narzędzi na słowniku scenariusza"
```

### Task 3: Opisy weak/rich + schematy inputs

**Files:**
- Modify: `vulnerability_agent/tool_logic.py`
- Test: `vulnerability_agent/tests/test_descriptions.py`

- [ ] **Step 1: Test obecności i różnicy opisów**

```python
# vulnerability_agent/tests/test_descriptions.py
from vulnerability_agent.tool_logic import TOOL_DESCRIPTIONS, TOOL_INPUTS, TOOL_NAMES

def test_three_tool_names():
    assert TOOL_NAMES == ("get_vulnerability", "get_projects_using_library", "get_project_details")

def test_weak_and_rich_present_for_each():
    for name in TOOL_NAMES:
        assert name in TOOL_DESCRIPTIONS["weak"]
        assert name in TOOL_DESCRIPTIONS["rich"]

def test_rich_longer_than_weak():
    for name in TOOL_NAMES:
        assert len(TOOL_DESCRIPTIONS["rich"][name]) > len(TOOL_DESCRIPTIONS["weak"][name])

def test_rich_project_details_mentions_environment_priority():
    # nośnik wiedzy dziedzinowej w schemacie (kluczowe dla H-A2/H-A3)
    assert "priorit" in TOOL_DESCRIPTIONS["rich"]["get_project_details"].lower()

def test_inputs_schema_shape():
    for name in TOOL_NAMES:
        assert isinstance(TOOL_INPUTS[name], dict)
        # każde narzędzie ma dokładnie jeden argument typu string
        (arg, spec), = TOOL_INPUTS[name].items()
        assert spec["type"] == "string" and "description" in spec
```

- [ ] **Step 2: Uruchom — ma nie przejść**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_descriptions.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja — dopisz do `tool_logic.py`**

```python
TOOL_NAMES = ("get_vulnerability", "get_projects_using_library", "get_project_details")

TOOL_DESCRIPTIONS = {
    "weak": {
        "get_vulnerability": "Get vulnerability information.",
        "get_projects_using_library": "Get projects using this library.",
        "get_project_details": "Get project information.",
    },
    "rich": {
        "get_vulnerability": (
            "Get CVE details: affected library name, vulnerable version range, CVSS score and severity. "
            "Call this first to determine which library is affected and what version range is vulnerable. "
            "Returns: cve_id, library, affected_versions_below, cvss_score, severity, description."
        ),
        "get_projects_using_library": (
            "Get list of client projects using the specified library, including the version each project uses. "
            "Call this after get_vulnerability to identify which of our projects are potentially exposed. "
            "The returned version per project must be compared against affected_versions_below from the CVE "
            "to determine if a project is actually running a vulnerable version."
        ),
        "get_project_details": (
            "Get project details: client name, deployment environment (production/staging), technical owner and team. "
            "Call this for each project returned by get_projects_using_library. "
            "The environment field is critical for priority assessment: a vulnerable library in production "
            "requires immediate remediation, while staging allows a planned response window."
        ),
    },
}

TOOL_INPUTS = {
    "get_vulnerability": {"cve_id": {"type": "string", "description": "CVE identifier, e.g. CVE-2024-9999."}},
    "get_projects_using_library": {"library_name": {"type": "string", "description": "Exact library name, e.g. lib-json-parser."}},
    "get_project_details": {"project_id": {"type": "string", "description": "Project identifier, e.g. portal-abc."}},
}
```

- [ ] **Step 4: Uruchom — ma przejść**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_descriptions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/tool_logic.py vulnerability_agent/tests/test_descriptions.py
git commit -m "feat: tool_logic — opisy weak/rich i schematy inputs"
```

---

## Faza 2 — Metryki i statystyka

### Task 4: Scoring STATUS/PRIORYTET

**Files:**
- Create: `vulnerability_agent/metrics.py`
- Test: `vulnerability_agent/tests/test_metrics.py`

- [ ] **Step 1: Test scoringu**

```python
# vulnerability_agent/tests/test_metrics.py
from vulnerability_agent.metrics import score_response

RESP = """\
**STATUS:** NARAŻONY
**PRIORYTET:** KRYTYCZNY
**Uzasadnienie:** ...
"""

def test_score_extracts_status_and_priority():
    s = score_response(RESP, "NARAŻONY", "KRYTYCZNY")
    assert s["status_found"] == "NARAŻONY"
    assert s["priority_found"] == "KRYTYCZNY"
    assert s["status_ok"] and s["priority_ok"] and s["pass"]

def test_score_detects_wrong_priority():
    s = score_response(RESP, "NARAŻONY", "NISKI")
    assert s["status_ok"] and not s["priority_ok"] and not s["pass"]

def test_score_missing_fields():
    s = score_response("brak struktury", "NARAŻONY", "KRYTYCZNY")
    assert s["status_found"] == "NIEZNANY" and not s["pass"]
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_metrics.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja**

```python
# vulnerability_agent/metrics.py
"""Metryki biegu agenta: scoring odpowiedzi + agregacja z pamięci agenta."""
from __future__ import annotations
import re
from dataclasses import dataclass, field


def score_response(response: str, expected_status: str, expected_priority: str) -> dict:
    found_status, found_priority = "NIEZNANY", "NIEZNANY"
    for line in response.split("\n"):
        stripped = line.strip().lstrip("*").strip()
        if re.match(r"STATUS[:\*]", stripped, re.IGNORECASE):
            found_status = stripped.split(":", 1)[-1].strip().strip("*").strip()
        elif re.match(r"PRIORYTET[:\*]", stripped, re.IGNORECASE):
            found_priority = stripped.split(":", 1)[-1].strip().strip("*").strip()
    status_ok = expected_status.upper() in found_status.upper()
    priority_ok = expected_priority.upper() in found_priority.upper()
    return {
        "status_found": found_status, "priority_found": found_priority,
        "status_ok": status_ok, "priority_ok": priority_ok,
        "pass": status_ok and priority_ok,
    }
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/metrics.py vulnerability_agent/tests/test_metrics.py
git commit -m "feat: metrics — scoring STATUS/PRIORYTET"
```

### Task 5: Precision/recall wyboru narzędzi + false-positive na projektach

**Files:**
- Modify: `vulnerability_agent/metrics.py`
- Test: `vulnerability_agent/tests/test_metrics.py`

- [ ] **Step 1: Testy PR i FP**

Dopisz do `tests/test_metrics.py`:

```python
from vulnerability_agent.metrics import tool_selection_pr, project_coverage

def test_pr_perfect_when_exactly_expected():
    p, r = tool_selection_pr(called={"get_vulnerability", "get_projects_using_library", "get_project_details"},
                             expected={"get_vulnerability", "get_projects_using_library", "get_project_details"})
    assert p == 1.0 and r == 1.0

def test_pr_drops_with_distractor_calls():
    # wywołał 2 właściwe + 2 dystraktory; oczekiwane 3
    p, r = tool_selection_pr(called={"get_vulnerability", "get_weather", "get_invoice", "get_projects_using_library"},
                             expected={"get_vulnerability", "get_projects_using_library", "get_project_details"})
    assert p == 0.5      # 2 trafione / 4 wywołane
    assert round(r, 4) == round(2/3, 4)

def test_project_coverage_full_and_no_false_positive():
    cov = project_coverage(response="dotknięte: portal-abc, api-xyz",
                           expected_flagged={"portal-abc", "api-xyz"},
                           safe_projects={"mobile-qrs"})
    assert cov["recall"] == 1.0
    assert cov["false_positive"] is False

def test_project_coverage_flags_false_positive():
    cov = project_coverage(response="dotknięte: portal-abc, mobile-qrs",
                           expected_flagged={"portal-abc"},
                           safe_projects={"mobile-qrs"})
    assert cov["false_positive"] is True
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_metrics.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja — dopisz do `metrics.py`**

```python
def tool_selection_pr(called: set[str], expected: set[str]) -> tuple[float, float]:
    """Precision/recall doboru narzędzi. called = zbiór nazw faktycznie wywołanych."""
    if not called:
        return 0.0, 0.0
    hits = called & expected
    precision = len(hits) / len(called)
    recall = len(hits) / len(expected) if expected else 0.0
    return precision, recall


def project_coverage(response: str, expected_flagged: set[str], safe_projects: set[str]) -> dict:
    """Czy odpowiedź wymienia wszystkie dotknięte projekty i żadnego bezpiecznego."""
    text = response.lower()
    flagged = {pid for pid in (expected_flagged | safe_projects) if pid.lower() in text}
    recall = len(flagged & expected_flagged) / len(expected_flagged) if expected_flagged else 1.0
    false_positive = bool(flagged & safe_projects)
    return {"flagged": flagged, "recall": recall, "false_positive": false_positive}
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/metrics.py vulnerability_agent/tests/test_metrics.py
git commit -m "feat: metrics — precision/recall narzędzi + pokrycie i false-positive projektów"
```

### Task 6: Agregacja śladu agenta (narzędzia, tokeny, czas) z `agent.memory.steps`

**Files:**
- Modify: `vulnerability_agent/metrics.py`
- Test: `vulnerability_agent/tests/test_metrics_trace.py`

- [ ] **Step 1: Test agregacji na sztucznych ActionStep**

```python
# vulnerability_agent/tests/test_metrics_trace.py
from types import SimpleNamespace
from smolagents.memory import ActionStep, Timing
from smolagents.monitoring import TokenUsage
from vulnerability_agent.metrics import aggregate_trace, TRACKED_TOOLS


def _tc(name):
    return SimpleNamespace(name=name, arguments={})

def _step(n, tool_names, in_tok, out_tok, t0, t1):
    s = ActionStep(step_number=n, timing=Timing(start_time=t0, end_time=t1))
    s.tool_calls = [_tc(x) for x in tool_names]
    s.token_usage = TokenUsage(input_tokens=in_tok, output_tokens=out_tok)
    return s

def test_aggregate_counts_only_tracked_tools():
    steps = [
        _step(1, ["get_vulnerability"], 100, 20, 0.0, 1.0),
        _step(2, ["get_projects_using_library", "get_weather"], 150, 30, 1.0, 2.5),
        _step(3, ["final_answer"], 200, 40, 2.5, 3.0),
    ]
    agent = SimpleNamespace(memory=SimpleNamespace(steps=steps))
    agg = aggregate_trace(agent)
    assert agg["tools_called"] == {"get_vulnerability": 1, "get_projects_using_library": 1}
    assert agg["all_called"] == {"get_vulnerability", "get_projects_using_library", "get_weather"}
    assert agg["input_tokens"] == 450 and agg["output_tokens"] == 90
    assert agg["latency_s"] == 3.0

def test_aggregate_handles_missing_token_usage():
    s = ActionStep(step_number=1, timing=Timing(start_time=0.0, end_time=1.0))
    s.tool_calls = [_tc("get_vulnerability")]
    s.token_usage = None
    agent = SimpleNamespace(memory=SimpleNamespace(steps=[s]))
    agg = aggregate_trace(agent)
    assert agg["input_tokens"] == 0 and agg["output_tokens"] == 0
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_metrics_trace.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja — dopisz do `metrics.py`**

```python
from smolagents.memory import ActionStep

TRACKED_TOOLS = {"get_vulnerability", "get_projects_using_library", "get_project_details"}


def aggregate_trace(agent) -> dict:
    """Zbiera z pamięci agenta: liczbę wywołań śledzonych narzędzi, zbiór WSZYSTKICH
    wywołanych narzędzi (do precision/recall z dystraktorami), tokeny i łączny czas."""
    tools_called: dict[str, int] = {}
    all_called: set[str] = set()
    in_tok = out_tok = 0
    start = end = None
    for step in getattr(agent.memory, "steps", []):
        if not isinstance(step, ActionStep):
            continue
        for tc in (step.tool_calls or []):
            all_called.add(tc.name)
            if tc.name in TRACKED_TOOLS:
                tools_called[tc.name] = tools_called.get(tc.name, 0) + 1
        tu = getattr(step, "token_usage", None)
        if tu is not None:
            in_tok += tu.input_tokens or 0
            out_tok += tu.output_tokens or 0
        tm = getattr(step, "timing", None)
        if tm is not None:
            if start is None or tm.start_time < start:
                start = tm.start_time
            if end is None or tm.end_time > end:
                end = tm.end_time
    latency = (end - start) if (start is not None and end is not None) else 0.0
    return {
        "tools_called": tools_called, "all_called": all_called,
        "tools_called_count": len(tools_called),
        "input_tokens": in_tok, "output_tokens": out_tok,
        "latency_s": round(latency, 4),
    }
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_metrics_trace.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/metrics.py vulnerability_agent/tests/test_metrics_trace.py
git commit -m "feat: metrics — agregacja śladu agenta (narzędzia, tokeny, czas)"
```

### Task 7: Statystyka — Wilson CI i test dwóch proporcji

**Files:**
- Create: `vulnerability_agent/stats.py`
- Test: `vulnerability_agent/tests/test_stats.py`

- [ ] **Step 1: Testy statystyki**

```python
# vulnerability_agent/tests/test_stats.py
from vulnerability_agent.stats import wilson_ci, two_proportion_z

def test_wilson_full_success():
    low, high = wilson_ci(10, 10)
    assert high == 1.0 or high > 0.99   # górny kres przy 10/10
    assert low < 1.0                     # Wilson nie daje [1,1] przy n=10

def test_wilson_half():
    low, high = wilson_ci(5, 10)
    assert low < 0.5 < high
    assert 0.0 < low and high < 1.0

def test_wilson_zero_n_returns_zero_one():
    assert wilson_ci(0, 0) == (0.0, 0.0)

def test_two_proportion_z_detects_difference():
    # 10/10 vs 2/10 — wyraźna różnica, |z| duże, p małe
    z, p = two_proportion_z(10, 10, 2, 10)
    assert abs(z) > 2.0 and p < 0.05

def test_two_proportion_z_no_difference():
    z, p = two_proportion_z(5, 10, 5, 10)
    assert abs(z) < 1e-9 and p > 0.9
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_stats.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja**

```python
# vulnerability_agent/stats.py
"""Statystyka bez scipy: Wilson score interval i test dwóch proporcji (z)."""
from __future__ import annotations
import math

Z95 = 1.959963984540054  # kwantyl 0.975 standardowego rozkładu normalnego


def wilson_ci(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _normal_sf(x: float) -> float:
    """P(Z > x) dla standardowego rozkładu normalnego."""
    return 0.5 * math.erfc(x / math.sqrt(2))


def two_proportion_z(s1: int, n1: int, s2: int, n2: int) -> tuple[float, float]:
    """Dwustronny test z dla dwóch proporcji. Zwraca (z, p_value)."""
    if n1 == 0 or n2 == 0:
        return (0.0, 1.0)
    p1, p2 = s1 / n1, s2 / n2
    p_pool = (s1 + s2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return (0.0, 1.0)
    z = (p1 - p2) / se
    p_value = 2 * _normal_sf(abs(z))
    return (z, p_value)
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_stats.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/stats.py vulnerability_agent/tests/test_stats.py
git commit -m "feat: stats — Wilson CI i test dwóch proporcji"
```

---

## Faza 3 — Scenariusze

### Task 8: Zestaw BASIC z polami rozszerzonymi

**Files:**
- Modify: `vulnerability_agent/scenarios.py`
- Test: `vulnerability_agent/tests/test_scenarios.py`

- [ ] **Step 1: Test integralności BASIC**

```python
# vulnerability_agent/tests/test_scenarios.py
from vulnerability_agent.scenarios import BASIC, HARD

REQUIRED = {"name", "expected_status", "expected_priority",
            "expected_flagged", "safe_projects",
            "cvss_score", "project_in_inventory", "environment",
            "projects_using_lib", "respect_inventory"}

def test_basic_has_six_cases():
    assert len(BASIC) == 6

def test_basic_cases_have_required_fields():
    for key, sc in BASIC.items():
        missing = REQUIRED - set(sc)
        assert not missing, f"{key}: brak pól {missing}"

def test_basic_expected_values_consistent():
    assert BASIC["case_1_vulnerable"]["expected_status"] == "NARAŻONY"
    assert BASIC["case_1_vulnerable"]["expected_priority"] == "KRYTYCZNY"
    assert BASIC["case_3_not_in_inventory"]["expected_status"] == "BRAK AKTYWÓW"
    assert BASIC["case_5_staging"]["expected_priority"] == "WYSOKI"
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_scenarios.py -v`
Expected: FAIL — `ImportError` (`BASIC`/`HARD` nie istnieją; obecnie `SCENARIOS`).

- [ ] **Step 3: Przepisz `scenarios.py` — zostaw 6 przypadków jako `BASIC`, dodaj pola `expected_flagged`, `safe_projects`, `respect_inventory`**

Zamień zawartość `scenarios.py` tak, by `SCENARIOS` → `BASIC`, a każdy przypadek zyskał trzy nowe pola. Przykład dwóch przypadków (pozostałe analogicznie, kopiując z dotychczasowego pliku i dodając trzy pola):

```python
# vulnerability_agent/scenarios.py
"""Scenariusze testowe. BASIC = 6 przypadków jednoczynnikowych (Część A/B1).
HARD = przypadki wieloetapowe (Część B2). Pola:
  expected_flagged: set[str]  — projekty, które MUSZĄ być oznaczone jako narażone
  safe_projects:    set[str]  — projekty, których oznaczenie = false positive
  respect_inventory: bool     — czy serwis składu honoruje project_in_inventory
                                (False = niespójny kontrakt, dawne COMP_VERSION=1)
"""

BASIC: dict[str, dict] = {
    "case_1_vulnerable": {
        "name": "Przypadek 1: Wersja podatna w produkcji",
        "expected_status": "NARAŻONY", "expected_priority": "KRYTYCZNY",
        "expected_flagged": {"portal-abc"}, "safe_projects": set(),
        "cvss_score": 9.8, "library_version": "3.1.4",
        "project_in_inventory": True, "environment": "production",
        "respect_inventory": True,
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}],
    },
    "case_2_safe_version": {
        "name": "Przypadek 2: Wersja bezpieczna",
        "expected_status": "NIE NARAŻONY", "expected_priority": "NISKI",
        "expected_flagged": set(), "safe_projects": {"portal-abc"},
        "cvss_score": 9.8, "library_version": "3.2.1",
        "project_in_inventory": True, "environment": "production",
        "respect_inventory": True,
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.2.1"}],
    },
    "case_3_not_in_inventory": {
        "name": "Przypadek 3: Projekt nie istnieje w inwentarzu",
        "expected_status": "BRAK AKTYWÓW", "expected_priority": "NISKI",
        "expected_flagged": set(), "safe_projects": set(),
        "cvss_score": 9.8, "library_version": "3.1.4",
        "project_in_inventory": False, "environment": "production",
        "respect_inventory": True,
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}],
    },
    "case_4_low_cvss": {
        "name": "Przypadek 4: Niski CVSS (2.0)",
        "expected_status": "NARAŻONY", "expected_priority": "NISKI",
        "expected_flagged": {"portal-abc"}, "safe_projects": set(),
        "cvss_score": 2.0, "library_version": "3.1.4",
        "project_in_inventory": True, "environment": "production",
        "respect_inventory": True,
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}],
    },
    "case_5_staging": {
        "name": "Przypadek 5: Środowisko staging",
        "expected_status": "NARAŻONY", "expected_priority": "WYSOKI",
        "expected_flagged": {"portal-abc"}, "safe_projects": set(),
        "cvss_score": 9.8, "library_version": "3.1.4",
        "project_in_inventory": True, "environment": "staging",
        "respect_inventory": True,
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}],
    },
    "case_6_multi_project": {
        "name": "Przypadek 6: CVE dotyka dwóch projektów jednocześnie",
        "expected_status": "NARAŻONY", "expected_priority": "KRYTYCZNY",
        "expected_flagged": {"portal-abc", "api-xyz"}, "safe_projects": set(),
        "cvss_score": 9.8, "library_version": "3.1.4",
        "project_in_inventory": True, "environment": "production",
        "respect_inventory": True,
        "projects_using_lib": [
            {"project_id": "portal-abc", "library_version": "3.1.4"},
            {"project_id": "api-xyz", "library_version": "3.1.4"},
        ],
    },
}

HARD: dict[str, dict] = {}  # wypełniane w Task 9
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_scenarios.py -v`
Expected: PASS (testy BASIC; testy HARD dodane w Task 9).

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/scenarios.py vulnerability_agent/tests/test_scenarios.py
git commit -m "refactor: scenarios — BASIC z polami expected_flagged/safe_projects/respect_inventory"
```

### Task 9: Zestaw HARD (B2)

**Files:**
- Modify: `vulnerability_agent/scenarios.py`
- Test: `vulnerability_agent/tests/test_scenarios.py`

- [ ] **Step 1: Testy HARD**

Dopisz do `tests/test_scenarios.py`:

```python
def test_hard_has_expected_cases():
    assert set(HARD) == {
        "hard_fleet", "hard_multi_lib", "hard_multi_cve",
        "hard_conflict", "hard_decoy", "hard_boundary",
    }

def test_hard_fleet_flags_only_vulnerable():
    sc = HARD["hard_fleet"]
    # 2 podatne (prod+staging), reszta bezpieczna/poza inwentarzem
    assert sc["expected_flagged"] == {"portal-abc", "api-xyz"}
    assert "mobile-qrs" in sc["safe_projects"]

def test_hard_conflict_marks_inconsistent_contract():
    assert HARD["hard_conflict"]["respect_inventory"] is False
    assert HARD["hard_conflict"]["project_in_inventory"] is False

def test_hard_boundary_is_safe_at_exact_threshold():
    sc = HARD["hard_boundary"]
    assert sc["library_version"] == "3.2.0"
    assert sc["expected_status"] == "NIE NARAŻONY"
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_scenarios.py -v`
Expected: FAIL — `HARD` puste.

- [ ] **Step 3: Wypełnij `HARD` w `scenarios.py`**

```python
HARD = {
    # 5 projektów: portal-abc (prod, podatny) i api-xyz (staging, podatny) -> flagged;
    # mobile-qrs (prod, bezpieczna wersja) -> safe; pozostałe nie używają biblioteki.
    "hard_fleet": {
        "name": "HARD: Flota — 5 projektów, mieszane środowiska i wersje",
        "expected_status": "NARAŻONY", "expected_priority": "KRYTYCZNY",
        "expected_flagged": {"portal-abc", "api-xyz"}, "safe_projects": {"mobile-qrs"},
        "cvss_score": 9.8, "project_in_inventory": True, "respect_inventory": True,
        "environment": "production",
        "project_environments": {"portal-abc": "production", "api-xyz": "staging", "mobile-qrs": "production"},
        "projects_using_lib": [
            {"project_id": "portal-abc", "library_version": "3.1.4"},
            {"project_id": "api-xyz", "library_version": "3.0.9"},
            {"project_id": "mobile-qrs", "library_version": "3.2.5"},
        ],
    },
    # Projekt używa kilku bibliotek; tylko lib-json-parser podatna.
    "hard_multi_lib": {
        "name": "HARD: Multi-library — projekt z wieloma zależnościami",
        "expected_status": "NARAŻONY", "expected_priority": "KRYTYCZNY",
        "expected_flagged": {"portal-abc"}, "safe_projects": set(),
        "cvss_score": 9.8, "project_in_inventory": True, "respect_inventory": True,
        "environment": "production",
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}],
        # informacyjnie: w prompcie agent zobaczy też inne biblioteki, ale serwis
        # zwraca tylko użytkowników lib-json-parser — kluczowe: brak false-positive.
    },
    # Dwa CVE w jednym zadaniu (drugie nie dotyczy nas) — patrz config: zadanie multi-cve.
    "hard_multi_cve": {
        "name": "HARD: Multi-CVE — dwa zgłoszenia naraz",
        "expected_status": "NARAŻONY", "expected_priority": "KRYTYCZNY",
        "expected_flagged": {"portal-abc"}, "safe_projects": set(),
        "cvss_score": 9.8, "project_in_inventory": True, "respect_inventory": True,
        "environment": "production",
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}],
        "extra_cve": "CVE-0000-0000",  # nieznane -> agent musi je odrzucić
    },
    # Niespójny kontrakt: skład zgłasza projekt, serwis projektów go nie zna.
    "hard_conflict": {
        "name": "HARD: Konflikt kontraktów — skład vs inwentarz",
        "expected_status": "BRAK AKTYWÓW", "expected_priority": "NISKI",
        "expected_flagged": set(), "safe_projects": set(),
        "cvss_score": 9.8, "project_in_inventory": False, "respect_inventory": False,
        "environment": "production",
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}],
        "conflict_expected": True,
    },
    # CVE nie dotyczy żadnego naszego projektu (biblioteka nieużywana).
    "hard_decoy": {
        "name": "HARD: Decoy CVE — biblioteka nieużywana u nas",
        "expected_status": "BRAK AKTYWÓW", "expected_priority": "NISKI",
        "expected_flagged": set(), "safe_projects": set(),
        "cvss_score": 9.8, "project_in_inventory": True, "respect_inventory": True,
        "environment": "production",
        "projects_using_lib": [],  # nikt nie używa
    },
    # Wersja dokładnie na progu 3.2.0 — NIE jest podatna.
    "hard_boundary": {
        "name": "HARD: Wersja graniczna 3.2.0",
        "expected_status": "NIE NARAŻONY", "expected_priority": "NISKI",
        "expected_flagged": set(), "safe_projects": {"portal-abc"},
        "cvss_score": 9.8, "library_version": "3.2.0",
        "project_in_inventory": True, "respect_inventory": True,
        "environment": "production",
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.2.0"}],
    },
}
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_scenarios.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/scenarios.py vulnerability_agent/tests/test_scenarios.py
git commit -m "feat: scenarios — zestaw HARD (flota, multi-lib, multi-cve, konflikt, decoy, granica)"
```

---

## Faza 4 — Serwisy MCP przepięte na tool_logic + dystraktory

### Task 10: Przepnij trzy serwisy na `tool_logic` (DRY)

**Files:**
- Modify: `vulnerability_agent/services/vulnerability_service.py`
- Modify: `vulnerability_agent/services/composition_service.py`
- Modify: `vulnerability_agent/services/project_service.py`
- Test: `vulnerability_agent/tests/test_services_smoke.py`

- [ ] **Step 1: Test smoke serwisu jako podprocesu (lista narzędzi + jedno wywołanie)**

```python
# vulnerability_agent/tests/test_services_smoke.py
import json, os, sys, subprocess
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[1] / "services"

def _run_list_tools(script: str, desc: str) -> list[str]:
    """Uruchamia serwis stdio, wykonuje MCP initialize + tools/list, zwraca nazwy narzędzi."""
    env = {**os.environ, "DESC_VERSION": desc, "SCENARIO": json.dumps({})}
    proc = subprocess.Popen([sys.executable, str(SERVICES / script)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True)
    def send(obj): proc.stdin.write(json.dumps(obj) + "\n"); proc.stdin.flush()
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "t", "version": "0"}}})
    proc.stdout.readline()
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    line = proc.stdout.readline()
    proc.terminate()
    tools = json.loads(line)["result"]["tools"]
    return [t["name"] for t in tools]

def test_vulnerability_service_exposes_tool():
    assert "get_vulnerability" in _run_list_tools("vulnerability_service.py", "rich")

def test_rich_description_carries_priority_knowledge():
    env = {**os.environ, "DESC_VERSION": "rich", "SCENARIO": json.dumps({})}
    proc = subprocess.Popen([sys.executable, str(SERVICES / "project_service.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True)
    def send(obj): proc.stdin.write(json.dumps(obj) + "\n"); proc.stdin.flush()
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
    proc.stdout.readline()
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    desc = json.loads(proc.stdout.readline())["result"]["tools"][0]["description"]
    proc.terminate()
    assert "priority" in desc.lower()
```

- [ ] **Step 2: Uruchom — FAIL lub błąd**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_services_smoke.py -v`
Expected: FAIL — obecne serwisy mają wbudowane opisy/logikę, ale po refaktorze importują z `tool_logic`; test sprawdza zachowanie po zmianie. (Jeśli przed zmianą przejdzie częściowo, i tak wykonaj Step 3.)

- [ ] **Step 3: Przepisz każdy serwis na wzór — wybór opisu z `tool_logic.TOOL_DESCRIPTIONS`**

`services/vulnerability_service.py`:

```python
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mcp.server.fastmcp import FastMCP
from vulnerability_agent.tool_logic import vulnerability_data, TOOL_DESCRIPTIONS

mcp = FastMCP("vulnerability-service")
_DESC = os.environ.get("DESC_VERSION", "rich")

def _scenario() -> dict:
    return json.loads(os.environ.get("SCENARIO", "{}"))

@mcp.tool(description=TOOL_DESCRIPTIONS[_DESC]["get_vulnerability"])
def get_vulnerability(cve_id: str) -> str:
    return json.dumps(vulnerability_data(_scenario(), cve_id))

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

`services/composition_service.py`:

```python
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mcp.server.fastmcp import FastMCP
from vulnerability_agent.tool_logic import projects_for_library, TOOL_DESCRIPTIONS

mcp = FastMCP("composition-service")
_DESC = os.environ.get("DESC_VERSION", "rich")

def _scenario() -> dict:
    return json.loads(os.environ.get("SCENARIO", "{}"))

@mcp.tool(description=TOOL_DESCRIPTIONS[_DESC]["get_projects_using_library"])
def get_projects_using_library(library_name: str) -> str:
    sc = _scenario()
    respect = sc.get("respect_inventory", True)
    return json.dumps(projects_for_library(sc, library_name, respect_inventory=respect))

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

`services/project_service.py`:

```python
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mcp.server.fastmcp import FastMCP
from vulnerability_agent.tool_logic import project_details, TOOL_DESCRIPTIONS

mcp = FastMCP("project-service")
_DESC = os.environ.get("DESC_VERSION", "rich")

def _scenario() -> dict:
    return json.loads(os.environ.get("SCENARIO", "{}"))

@mcp.tool(description=TOOL_DESCRIPTIONS[_DESC]["get_project_details"])
def get_project_details(project_id: str) -> str:
    return json.dumps(project_details(_scenario(), project_id))

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

> Uwaga: `respect_inventory` jest teraz cechą scenariusza (pole), nie zmienną `COMP_VERSION`. To upraszcza konfigurację i czyni niespójny kontrakt właściwością danych testowych.

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_services_smoke.py -v`
Expected: PASS. Jeśli `@mcp.tool(description=...)` nie wspiera nadpisania opisu w tej wersji FastMCP, ustaw opis przez docstring dynamicznie nie jest możliwe — wtedy zachowaj dwie funkcje (weak/rich) jak w obecnym kodzie, ale ciało obu wywołuje `tool_logic`. (Weryfikacja: `.venv/bin/python -c "from mcp.server.fastmcp import FastMCP; import inspect; print('description' in inspect.signature(FastMCP().tool).parameters)"` — jeśli `True`, użyj wariantu z `description=`.)

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/services/*.py vulnerability_agent/tests/test_services_smoke.py
git commit -m "refactor: serwisy MCP korzystają z tool_logic (DRY), respect_inventory z scenariusza"
```

### Task 11: Serwisy-dystraktory (B1)

**Files:**
- Create: `vulnerability_agent/services/distractors/weather_service.py`
- Create: `vulnerability_agent/services/distractors/invoice_service.py`
- Create: `vulnerability_agent/services/distractors/employee_service.py`
- Create: `vulnerability_agent/services/distractors/license_service.py`
- Create: `vulnerability_agent/services/distractors/incident_service.py`
- Create: `vulnerability_agent/services/distractors/deployment_service.py`
- Create: `vulnerability_agent/services/distractors/__init__.py`
- Test: `vulnerability_agent/tests/test_distractors_smoke.py`

- [ ] **Step 1: Test smoke jednego dystraktora**

```python
# vulnerability_agent/tests/test_distractors_smoke.py
import json, os, sys, subprocess
from pathlib import Path
DISTR = Path(__file__).resolve().parents[1] / "services" / "distractors"

def _tool_names(script):
    env = {**os.environ, "DESC_VERSION": "rich"}
    proc = subprocess.Popen([sys.executable, str(DISTR / script)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True)
    def send(o): proc.stdin.write(json.dumps(o)+"\n"); proc.stdin.flush()
    send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"0"}}})
    proc.stdout.readline()
    send({"jsonrpc":"2.0","method":"notifications/initialized"})
    send({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
    names = [t["name"] for t in json.loads(proc.stdout.readline())["result"]["tools"]]
    proc.terminate()
    return names

def test_weather_distractor_exposes_get_weather():
    assert "get_weather" in _tool_names("weather_service.py")
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_distractors_smoke.py -v`
Expected: FAIL — brak pliku.

- [ ] **Step 3: Utwórz 6 dystraktorów wg jednego wzoru**

`services/distractors/__init__.py`: pusty plik.

`services/distractors/weather_service.py` (pozostałe analogicznie, z innymi nazwami/opisami):

```python
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather-service")
_DESC = os.environ.get("DESC_VERSION", "rich")

_WEAK = "Get weather."
_RICH = ("Get current weather for a city: temperature, conditions, humidity. "
         "Use for travel and logistics planning. Unrelated to software security.")

@mcp.tool(description=_RICH if _DESC == "rich" else _WEAK)
def get_weather(city: str) -> str:
    return '{"city": "%s", "temp_c": 18, "conditions": "cloudy"}' % city

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

Pozostałe pliki — analogiczny szablon, podmień: nazwę serwisu, nazwę narzędzia, argument, opisy i zwracany JSON:

- `invoice_service.py` → `get_invoice(invoice_id)` — "Get invoice: amount, status, due date. Finance domain."
- `employee_service.py` → `get_employee(employee_id)` — "Get employee: name, department, role. HR domain."
- `license_service.py` → `get_license(software_id)` — "Get software license: seats, expiry, vendor. Procurement domain."
- `incident_service.py` → `get_incident(incident_id)` — "Get IT incident: severity, status, assignee. ITSM domain."
- `deployment_service.py` → `get_deployment_log(service_name)` — "Get recent deployment log entries: version, timestamp, result. DevOps domain."

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_distractors_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/services/distractors/ vulnerability_agent/tests/test_distractors_smoke.py
git commit -m "feat: 6 serwisów-dystraktorów MCP dla testu wyboru narzędzi przy skali"
```

---

## Faza 5 — Warstwa dostarczania i konfiguracja

### Task 12: In-process narzędzia smolagents (baseline noMCP)

**Files:**
- Create: `vulnerability_agent/delivery/__init__.py`
- Create: `vulnerability_agent/delivery/local_tools.py`
- Test: `vulnerability_agent/tests/test_local_tools.py`

- [ ] **Step 1: Test budowy i wywołania narzędzia lokalnego**

```python
# vulnerability_agent/tests/test_local_tools.py
from vulnerability_agent.delivery.local_tools import build_local_tools

SCEN = {"cvss_score": 9.8, "library_version": "3.1.4", "project_in_inventory": True,
        "environment": "production", "respect_inventory": True,
        "projects_using_lib": [{"project_id": "portal-abc", "library_version": "3.1.4"}]}

def test_build_three_tools_with_chosen_description():
    tools = build_local_tools(SCEN, desc_version="rich")
    names = {t.name for t in tools}
    assert names == {"get_vulnerability", "get_projects_using_library", "get_project_details"}
    gv = next(t for t in tools if t.name == "get_vulnerability")
    assert "CVSS" in gv.description  # rich

def test_local_tool_forward_returns_json_string():
    tools = build_local_tools(SCEN, desc_version="weak")
    gv = next(t for t in tools if t.name == "get_vulnerability")
    out = gv.forward("CVE-2024-9999")
    assert "lib-json-parser" in out

def test_weak_description_is_short():
    tools = build_local_tools(SCEN, desc_version="weak")
    gv = next(t for t in tools if t.name == "get_vulnerability")
    assert gv.description == "Get vulnerability information."
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_local_tools.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja**

```python
# vulnerability_agent/delivery/local_tools.py
"""In-process narzędzia smolagents — baseline bez MCP.

Te same opisy i ta sama logika co serwisy FastMCP (z tool_logic), ale bez
transportu stdio: narzędzia żyją w procesie agenta. Porównanie z wariantem MCP
izoluje WYŁĄCZNIE warstwę transportu.
"""
from __future__ import annotations
import json
from smolagents import Tool
from vulnerability_agent.tool_logic import (
    vulnerability_data, projects_for_library, project_details,
    TOOL_DESCRIPTIONS, TOOL_INPUTS,
)


class _LogicTool(Tool):
    output_type = "string"

    def __init__(self, name: str, description: str, inputs: dict, fn, scenario: dict):
        self.name = name
        self.description = description
        self.inputs = inputs
        self._fn = fn
        self._scenario = scenario
        super().__init__()

    def forward(self, **kwargs) -> str:
        return json.dumps(self._fn(self._scenario, **kwargs))


def build_local_tools(scenario: dict, desc_version: str = "rich") -> list[Tool]:
    respect = scenario.get("respect_inventory", True)

    def _projects(sc, library_name):
        return projects_for_library(sc, library_name, respect_inventory=respect)

    specs = [
        ("get_vulnerability", vulnerability_data),
        ("get_projects_using_library", _projects),
        ("get_project_details", project_details),
    ]
    desc = TOOL_DESCRIPTIONS[desc_version]
    tools: list[Tool] = []
    for name, fn in specs:
        tools.append(_LogicTool(name, desc[name], dict(TOOL_INPUTS[name]), fn, scenario))
    return tools
```

> Uwaga: `forward(**kwargs)` przyjmuje argument po nazwie zgodnej z `inputs` (np. `cve_id`). Test wywołuje `gv.forward("CVE-2024-9999")` pozycyjnie — smolagents wywołuje przez nazwę, więc dla zgodności testu zmień wywołanie testu na `gv.forward(cve_id="CVE-2024-9999")` LUB dodaj obsługę pozycyjną. Wybierz wariant nazwany: zmodyfikuj test Step 1 → `gv.forward(cve_id="CVE-2024-9999")`.

- [ ] **Step 4: Popraw test na wywołanie nazwane i uruchom — PASS**

W `tests/test_local_tools.py` zmień `gv.forward("CVE-2024-9999")` → `gv.forward(cve_id="CVE-2024-9999")`.

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_local_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/delivery/__init__.py vulnerability_agent/delivery/local_tools.py vulnerability_agent/tests/test_local_tools.py
git commit -m "feat: delivery/local_tools — in-process narzędzia smolagents (baseline noMCP)"
```

### Task 13: Toolsety MCP i budowa parametrów serwerów

**Files:**
- Create: `vulnerability_agent/delivery/mcp_tools.py`
- Test: `vulnerability_agent/tests/test_mcp_tools.py`

- [ ] **Step 1: Test składania listy serwerów wg toolsetu**

```python
# vulnerability_agent/tests/test_mcp_tools.py
from vulnerability_agent.delivery.mcp_tools import server_params_for, TOOLSETS

def test_core_toolset_has_three_servers():
    sp = server_params_for("core", scenario={}, desc_version="rich")
    assert len(sp) == 3

def test_plus3_has_six_servers():
    assert len(server_params_for("plus3", scenario={}, desc_version="rich")) == 6

def test_plus9_has_twelve_servers():
    assert len(server_params_for("plus9", scenario={}, desc_version="rich")) == 12

def test_env_carries_scenario_and_desc():
    sp = server_params_for("core", scenario={"cvss_score": 2.0}, desc_version="weak")
    assert sp[0].env["DESC_VERSION"] == "weak"
    assert "2.0" in sp[0].env["SCENARIO"]

def test_toolsets_sizes_registry():
    assert TOOLSETS["core"] == 3 and TOOLSETS["plus3"] == 6 and TOOLSETS["plus9"] == 12
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_mcp_tools.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja**

```python
# vulnerability_agent/delivery/mcp_tools.py
"""Budowa parametrów serwerów MCP (stdio) dla zadanego toolsetu.

Toolset = rdzeń (3 serwisy korelacji) + N dystraktorów. Służy do testu wyboru
narzędzia przy skali (Część B1).
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from mcp import StdioServerParameters

_SERVICES = Path(__file__).resolve().parents[1] / "services"
_DISTR = _SERVICES / "distractors"

_CORE = ["vulnerability_service.py", "composition_service.py", "project_service.py"]
_DISTRACTORS = [
    "weather_service.py", "invoice_service.py", "employee_service.py",
    "license_service.py", "incident_service.py", "deployment_service.py",
]

# rozmiar toolsetu -> liczba dystraktorów dołączanych do rdzenia
TOOLSETS = {"core": 3, "plus3": 6, "plus9": 12}
_DISTRACTOR_COUNT = {"core": 0, "plus3": 3, "plus9": 9}


def _distractor_scripts(n: int) -> list[str]:
    # 6 fizycznych dystraktorów; dla n>6 powielamy nie jest możliwe (różne nazwy narzędzi).
    if n > len(_DISTRACTORS):
        raise ValueError(f"Maksymalnie {len(_DISTRACTORS)} dystraktorów, zażądano {n}")
    return _DISTRACTORS[:n]


def server_params_for(toolset: str, scenario: dict, desc_version: str) -> list[StdioServerParameters]:
    env = {**os.environ, "SCENARIO": json.dumps(scenario, ensure_ascii=False), "DESC_VERSION": desc_version}
    params = [StdioServerParameters(command=sys.executable, args=[str(_SERVICES / s)], env=env) for s in _CORE]
    for s in _distractor_scripts(_DISTRACTOR_COUNT[toolset]):
        params.append(StdioServerParameters(command=sys.executable, args=[str(_DISTR / s)], env=env))
    return params
```

> Uwaga projektowa: `plus9` wymaga 9 dystraktorów, a mamy 6. Rozwiązanie: rozszerz `_DISTRACTORS` do 9 plików w Task 11 LUB ogranicz krzywą B1 do punktów 3/6/9 z `_DISTRACTOR_COUNT = {"core":0,"plus3":3,"plus6":6}` i `TOOLSETS={"core":3,"plus3":6,"plus6":9}`. **Decyzja przyjęta: krzywa 3/6/9 narzędzi** (mniej API, wystarcza do pokazania trendu). Zmień rejestry odpowiednio i dodaj brakujące 3 dystraktory w Task 11 nie jest konieczne — 6 dystraktorów pokrywa max 9 narzędzi (3 rdzeń + 6).

**Korekta rejestrów (użyj tej wersji):**

```python
TOOLSETS = {"core": 3, "plus3": 6, "plus6": 9}
_DISTRACTOR_COUNT = {"core": 0, "plus3": 3, "plus6": 6}
```

I popraw testy Step 1: `plus6` → 9 serwerów; usuń test `plus9`.

- [ ] **Step 4: Uruchom — PASS**

Po korekcie rejestrów i testów (`core`=3, `plus3`=6, `plus6`=9 serwerów).
Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_mcp_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/delivery/mcp_tools.py vulnerability_agent/tests/test_mcp_tools.py
git commit -m "feat: delivery/mcp_tools — toolsety core/plus3/plus6 (3/6/9 narzędzi)"
```

### Task 14: Model warunku i szablony zadań

**Files:**
- Create: `vulnerability_agent/config.py`
- Test: `vulnerability_agent/tests/test_config.py`

- [ ] **Step 1: Test struktury Condition i rejestrów**

```python
# vulnerability_agent/tests/test_config.py
from vulnerability_agent.config import Condition, TASK_TEMPLATES, PART_A, PART_B

def test_condition_defaults():
    c = Condition(name="x")
    assert c.delivery == "mcp" and c.desc_version == "rich"
    assert c.task_version == "full" and c.toolset == "core"
    assert c.scenario_suite == "basic"

def test_task_templates_present():
    for k in ("trigger", "goal", "steps", "full"):
        assert "{cve_id}" in TASK_TEMPLATES[k]

def test_part_a_has_baseline_and_2x2_and_portability():
    # A1: noMCP vs MCP-equiv ; A2: 2x2 ; A3: portability variants
    assert "a1_nomcp" in PART_A and "a1_mcp_equiv" in PART_A
    assert {"a2_weak_min", "a2_rich_min", "a2_weak_full", "a2_rich_full"} <= set(PART_A)

def test_part_b_has_scaling_and_hard():
    assert {"b1_core_weak", "b1_core_rich", "b1_plus6_weak", "b1_plus6_rich"} <= set(PART_B)
    assert "b2_hard_rich_full" in PART_B
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_config.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja**

```python
# vulnerability_agent/config.py
"""Deklaratywne warunki eksperymentu + szablony zadań."""
from __future__ import annotations
from dataclasses import dataclass

SMALL_MODEL = "gpt-4.1-mini"
LARGE_MODEL = "gpt-5.2"


@dataclass
class Condition:
    name: str
    delivery: str = "mcp"          # "mcp" | "direct"
    desc_version: str = "rich"     # "weak" | "rich"
    task_version: str = "full"     # "trigger" | "goal" | "steps" | "full"
    toolset: str = "core"          # "core" | "plus3" | "plus6"
    model_id: str = SMALL_MODEL
    scenario_suite: str = "basic"  # "basic" | "hard"
    prompt_variant: str = "base"   # dla A3: "base" | "persona" | "paraphrase" | "trigger"


TASK_TRIGGER = """\
Nowa podatność zgłoszona: {cve_id}.
Czy nasza organizacja jest narażona? Odpowiedz w formacie:
**STATUS:** NARAŻONY / NIE NARAŻONY / BRAK AKTYWÓW
**PRIORYTET:** KRYTYCZNY / WYSOKI / NISKI
**Dotknięte projekty:** [lista project_id]"""

TASK_GOAL = """\
Przeanalizuj podatność {cve_id} i oceń narażenie naszej organizacji.
Zanim wydasz ocenę, zbierz kompletne dane ze wszystkich dostępnych źródeł.
Uwzględnij: szczegóły CVE, które projekty używają biblioteki i w jakich środowiskach.

Odpowiedź:
**STATUS:** NARAŻONY / NIE NARAŻONY / BRAK AKTYWÓW
**PRIORYTET:** KRYTYCZNY / WYSOKI / NISKI
**Dotknięte projekty:** [lista project_id z wersją, środowiskiem]
**Uzasadnienie:** [odwołanie do danych z każdego źródła]"""

TASK_STEPS = """\
Przeanalizuj podatność {cve_id} i oceń narażenie organizacji.
Wykonaj kroki: 1) get_vulnerability 2) get_projects_using_library (porównaj wersje) 3) get_project_details dla każdego projektu.

Odpowiedź:
**STATUS:** NARAŻONY / NIE NARAŻONY / BRAK AKTYWÓW
**PRIORYTET:** KRYTYCZNY / WYSOKI / NISKI
**Dotknięte projekty:** [lista project_id]
**Uzasadnienie:** [krok po kroku]"""

TASK_FULL = """\
Przeanalizuj podatność {cve_id} i oceń narażenie organizacji.
Wykonaj kroki: 1) get_vulnerability 2) get_projects_using_library 3) get_project_details dla każdego projektu.

Reguły PRIORYTETU — stosuj TYLKO gdy STATUS = NARAŻONY:
- CVSS >= 9.0 i production → KRYTYCZNY
- CVSS >= 9.0 i staging    → WYSOKI
- CVSS >= 7.0 i production → WYSOKI
- CVSS >= 7.0 i staging    → NISKI
- CVSS < 7.0               → NISKI
Dla STATUS != NARAŻONY → PRIORYTET = NISKI.

Reguły STATUSU:
- NARAŻONY: istnieje projekt z podatną wersją (poniżej affected_versions_below)
- NIE NARAŻONY: wszystkie projekty mają wersję bezpieczną
- BRAK AKTYWÓW: żaden projekt nie używa tej biblioteki

Odpowiedź:
**STATUS:** NARAŻONY / NIE NARAŻONY / BRAK AKTYWÓW
**PRIORYTET:** KRYTYCZNY / WYSOKI / NISKI
**Dotknięte projekty:** [lista project_id z wersją i środowiskiem]
**Uzasadnienie:** [krok po kroku]"""

TASK_TEMPLATES = {"trigger": TASK_TRIGGER, "goal": TASK_GOAL, "steps": TASK_STEPS, "full": TASK_FULL}

# Prefiksy person/parafraz dla testu przenośności A3 (doklejane przed szablonem)
PROMPT_VARIANTS = {
    "base": "",
    "persona": "Jesteś znudzonym stażystą. Odpowiadaj zdawkowo, ale w wymaganym formacie.\n\n",
    "paraphrase": "Zadanie operacyjne dla zespołu bezpieczeństwa — proszę o ocenę ekspozycji.\n\n",
    "trigger": "",  # w A3 łączone z task_version='trigger'
}

# ── Część A ───────────────────────────────────────────────────────────────────
PART_A = {
    # A1 — efekt samego transportu (identyczna wiedza: słaby opis + pełne reguły w prompcie)
    "a1_nomcp":     Condition("a1_nomcp",     delivery="direct", desc_version="weak", task_version="full"),
    "a1_mcp_equiv": Condition("a1_mcp_equiv", delivery="mcp",    desc_version="weak", task_version="full"),
    # A2 — 2x2 lokalizacja wiedzy (zawsze MCP)
    "a2_weak_min":  Condition("a2_weak_min",  desc_version="weak", task_version="trigger"),
    "a2_rich_min":  Condition("a2_rich_min",  desc_version="rich", task_version="trigger"),
    "a2_weak_full": Condition("a2_weak_full", desc_version="weak", task_version="full"),
    "a2_rich_full": Condition("a2_rich_full", desc_version="rich", task_version="full"),
}

# ── Część B ───────────────────────────────────────────────────────────────────
PART_B = {
    # B1 — wybór narzędzia przy skali (krzywa 3/6/9 × weak/rich), zadanie = goal (bez sztywnych kroków)
    "b1_core_weak":  Condition("b1_core_weak",  toolset="core",  desc_version="weak", task_version="goal"),
    "b1_core_rich":  Condition("b1_core_rich",  toolset="core",  desc_version="rich", task_version="goal"),
    "b1_plus3_weak": Condition("b1_plus3_weak", toolset="plus3", desc_version="weak", task_version="goal"),
    "b1_plus3_rich": Condition("b1_plus3_rich", toolset="plus3", desc_version="rich", task_version="goal"),
    "b1_plus6_weak": Condition("b1_plus6_weak", toolset="plus6", desc_version="weak", task_version="goal"),
    "b1_plus6_rich": Condition("b1_plus6_rich", toolset="plus6", desc_version="rich", task_version="goal"),
    # B2 — trudne scenariusze na konfiguracji referencyjnej + degradacja (weak/trigger)
    "b2_hard_rich_full": Condition("b2_hard_rich_full", desc_version="rich", task_version="full", scenario_suite="hard"),
    "b2_hard_weak_trig": Condition("b2_hard_weak_trig", desc_version="weak", task_version="trigger", scenario_suite="hard"),
}
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/config.py vulnerability_agent/tests/test_config.py
git commit -m "feat: config — Condition, szablony zadań, rejestry Część A i B"
```

---

## Faza 6 — Runner i raport

### Task 15: Runner pojedynczego biegu (orkiestracja delivery + metryki)

**Files:**
- Create: `vulnerability_agent/run_experiment.py`
- Test: `vulnerability_agent/tests/test_runner_assembly.py`

> Uwaga: faktyczny `agent.run()` uderza w API OpenAI i nie jest testowany jednostkowo. Testujemy **składanie** rekordu wyniku (`build_record`) z gotowych danych biegu — to deterministyczne i pokrywa scoring + PR + coverage + ślad.

- [ ] **Step 1: Test build_record**

```python
# vulnerability_agent/tests/test_runner_assembly.py
from vulnerability_agent.run_experiment import build_record
from vulnerability_agent.config import Condition

SCEN = {"name": "X", "expected_status": "NARAŻONY", "expected_priority": "KRYTYCZNY",
        "expected_flagged": {"portal-abc"}, "safe_projects": set()}

RESP = "**STATUS:** NARAŻONY\n**PRIORYTET:** KRYTYCZNY\n**Dotknięte projekty:** portal-abc\n"

TRACE = {"tools_called": {"get_vulnerability": 1, "get_projects_using_library": 1, "get_project_details": 1},
         "all_called": {"get_vulnerability", "get_projects_using_library", "get_project_details"},
         "tools_called_count": 3, "input_tokens": 500, "output_tokens": 80, "latency_s": 2.1}

def test_build_record_pass_and_metrics():
    cond = Condition(name="t")
    rec = build_record(cond, "case_x", SCEN, RESP, TRACE, run_idx=0)
    assert rec["pass"] is True
    assert rec["status_ok"] and rec["priority_ok"]
    assert rec["tool_precision"] == 1.0 and rec["tool_recall"] == 1.0
    assert rec["project_recall"] == 1.0 and rec["false_positive"] is False
    assert rec["input_tokens"] == 500 and rec["latency_s"] == 2.1
    assert rec["condition"] == "t" and rec["case"] == "case_x" and rec["run_idx"] == 0

def test_build_record_detects_false_positive():
    scen = {**SCEN, "expected_flagged": {"portal-abc"}, "safe_projects": {"mobile-qrs"}}
    resp = RESP + "oraz mobile-qrs\n"
    rec = build_record(Condition(name="t"), "case_x", scen, resp, TRACE, run_idx=1)
    assert rec["false_positive"] is True
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_runner_assembly.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja**

```python
# vulnerability_agent/run_experiment.py
"""Uruchamia warunek N razy i zapisuje rekordy do JSONL.

build_record() — czyste składanie metryk (testowane).
run_once()     — jeden bieg agenta (MCP lub direct) [uderza w API].
run_condition()— pętla N biegów × scenariusze, zapis JSONL.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

from smolagents import MCPClient, ToolCallingAgent
from smolagents.models import OpenAIServerModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vulnerability_agent.config import Condition, TASK_TEMPLATES, PROMPT_VARIANTS
from vulnerability_agent.scenarios import BASIC, HARD
from vulnerability_agent.metrics import (
    score_response, tool_selection_pr, project_coverage, aggregate_trace, TRACKED_TOOLS,
)
from vulnerability_agent.delivery.local_tools import build_local_tools
from vulnerability_agent.delivery.mcp_tools import server_params_for

CVE_ID = "CVE-2024-9999"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _suite(name: str) -> dict:
    return {"basic": BASIC, "hard": HARD}[name]


def _task_for(cond: Condition) -> str:
    template = TASK_TEMPLATES[cond.task_version]
    prefix = PROMPT_VARIANTS.get(cond.prompt_variant, "")
    return prefix + template.format(cve_id=CVE_ID)


def build_record(cond: Condition, case_key: str, scenario: dict,
                 response: str, trace: dict, run_idx: int) -> dict:
    s = score_response(response, scenario["expected_status"], scenario["expected_priority"])
    precision, recall = tool_selection_pr(trace["all_called"], TRACKED_TOOLS)
    cov = project_coverage(response, set(scenario.get("expected_flagged", set())),
                           set(scenario.get("safe_projects", set())))
    return {
        "condition": cond.name, "delivery": cond.delivery, "desc_version": cond.desc_version,
        "task_version": cond.task_version, "toolset": cond.toolset, "model_id": cond.model_id,
        "scenario_suite": cond.scenario_suite, "prompt_variant": cond.prompt_variant,
        "case": case_key, "run_idx": run_idx,
        "status_found": s["status_found"], "priority_found": s["priority_found"],
        "status_ok": s["status_ok"], "priority_ok": s["priority_ok"], "pass": s["pass"],
        "tools_called": trace["tools_called"], "tools_called_count": trace["tools_called_count"],
        "tool_precision": precision, "tool_recall": recall,
        "project_recall": cov["recall"], "false_positive": cov["false_positive"],
        "input_tokens": trace["input_tokens"], "output_tokens": trace["output_tokens"],
        "latency_s": trace["latency_s"],
        "response": response,
    }


def run_once(cond: Condition, scenario: dict) -> tuple[str, dict]:
    model = OpenAIServerModel(model_id=cond.model_id)
    task = _task_for(cond)
    if cond.delivery == "direct":
        tools = build_local_tools(scenario, desc_version=cond.desc_version)
        agent = ToolCallingAgent(tools=tools, model=model, verbosity_level=0)
        result = agent.run(task)
        return str(result), aggregate_trace(agent)
    # MCP
    server_params = server_params_for(cond.toolset, scenario, cond.desc_version)
    with MCPClient(server_params, structured_output=True) as tools:
        agent = ToolCallingAgent(tools=tools, model=model, verbosity_level=0)
        result = agent.run(task)
        trace = aggregate_trace(agent)
    return str(result), trace


def run_condition(cond: Condition, n: int, out_dir: Path = RESULTS_DIR) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    suite = _suite(cond.scenario_suite)
    out_path = out_dir / f"{cond.name}.jsonl"
    records: list[dict] = []
    with out_path.open("w", encoding="utf-8") as f:
        for run_idx in range(n):
            for case_key, scenario in suite.items():
                response, trace = run_once(cond, scenario)
                rec = build_record(cond, case_key, scenario, response, trace, run_idx)
                f.write(json.dumps(rec, ensure_ascii=False, default=list) + "\n")
                f.flush()
                records.append(rec)
                print(f"[{cond.name}] run {run_idx} {case_key}: {'PASS' if rec['pass'] else 'FAIL'}")
    return records
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_runner_assembly.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/run_experiment.py vulnerability_agent/tests/test_runner_assembly.py
git commit -m "feat: run_experiment — build_record (testowane) + run_once/run_condition (MCP+direct)"
```

### Task 16: Live smoke test (gated) — jeden bieg end-to-end

**Files:**
- Create: `vulnerability_agent/tests/test_live_smoke.py`

- [ ] **Step 1: Test gated kluczem API**

```python
# vulnerability_agent/tests/test_live_smoke.py
import os
import pytest
from vulnerability_agent.config import Condition
from vulnerability_agent.run_experiment import run_once
from vulnerability_agent.scenarios import BASIC

pytestmark = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"),
                                reason="brak OPENAI_API_KEY — pomijam test live")

def test_mcp_baseline_case_runs_and_calls_three_tools():
    cond = Condition(name="smoke", delivery="mcp", desc_version="rich", task_version="full")
    response, trace = run_once(cond, BASIC["case_1_vulnerable"])
    assert "STATUS" in response.upper()
    assert trace["tools_called_count"] >= 2  # zwykle 3

def test_direct_baseline_runs():
    cond = Condition(name="smoke_direct", delivery="direct", desc_version="rich", task_version="full")
    response, trace = run_once(cond, BASIC["case_1_vulnerable"])
    assert "STATUS" in response.upper()
```

- [ ] **Step 2: Uruchom z kluczem — PASS (lub SKIP bez klucza)**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_live_smoke.py -v`
Expected: 2 PASSED (z kluczem; każdy bieg to realne wywołanie API) lub 2 SKIPPED (bez klucza). Jeśli FAIL — to prawdziwy problem integracji (np. import ścieżek, MCPClient) do naprawienia przed dalszymi zadaniami.

- [ ] **Step 3: Commit**

```bash
git add vulnerability_agent/tests/test_live_smoke.py
git commit -m "test: live smoke (gated OPENAI_API_KEY) — MCP i direct end-to-end"
```

### Task 17: Generator raportu z JSONL (agregacja + CI + testy proporcji)

**Files:**
- Create: `vulnerability_agent/report.py`
- Test: `vulnerability_agent/tests/test_report.py`

- [ ] **Step 1: Test agregacji rekordów**

```python
# vulnerability_agent/tests/test_report.py
from vulnerability_agent.report import aggregate_records

def _rec(cond, case, passed, fp=False, prec=1.0, run=0):
    return {"condition": cond, "case": case, "run_idx": run, "pass": passed,
            "status_ok": passed, "priority_ok": passed, "false_positive": fp,
            "tool_precision": prec, "tool_recall": 1.0, "project_recall": 1.0,
            "input_tokens": 100, "output_tokens": 20, "latency_s": 1.0,
            "tools_called_count": 3}

def test_aggregate_pass_rate_and_ci():
    recs = [_rec("c", "case_1", True), _rec("c", "case_1", True),
            _rec("c", "case_1", False), _rec("c", "case_1", True)]
    agg = aggregate_records(recs)["c"]
    assert agg["n"] == 4 and agg["passed"] == 3
    assert 0.0 < agg["ci_low"] <= 0.75 <= agg["ci_high"] <= 1.0
    assert abs(agg["pass_rate"] - 0.75) < 1e-9

def test_aggregate_tracks_false_positive_rate():
    recs = [_rec("c", "k", True, fp=True), _rec("c", "k", True, fp=False)]
    assert aggregate_records(recs)["c"]["fp_rate"] == 0.5

def test_aggregate_mean_precision_and_tokens():
    recs = [_rec("c", "k", True, prec=0.5), _rec("c", "k", True, prec=1.0)]
    agg = aggregate_records(recs)["c"]
    assert agg["mean_tool_precision"] == 0.75
    assert agg["mean_input_tokens"] == 100
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_report.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja**

```python
# vulnerability_agent/report.py
"""Czyta JSONL z results/, agreguje per warunek, generuje tabele Markdown z CI."""
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict

from vulnerability_agent.stats import wilson_ci, two_proportion_z

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def aggregate_records(records: list[dict]) -> dict:
    by_cond: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cond[r["condition"]].append(r)
    out: dict[str, dict] = {}
    for cond, recs in by_cond.items():
        n = len(recs)
        passed = sum(1 for r in recs if r["pass"])
        low, high = wilson_ci(passed, n)
        out[cond] = {
            "n": n, "passed": passed, "pass_rate": passed / n if n else 0.0,
            "ci_low": low, "ci_high": high,
            "fp_rate": _mean([1.0 if r["false_positive"] else 0.0 for r in recs]),
            "mean_tool_precision": _mean([r["tool_precision"] for r in recs]),
            "mean_tool_recall": _mean([r["tool_recall"] for r in recs]),
            "mean_project_recall": _mean([r["project_recall"] for r in recs]),
            "mean_input_tokens": _mean([r["input_tokens"] for r in recs]),
            "mean_output_tokens": _mean([r["output_tokens"] for r in recs]),
            "mean_latency_s": _mean([r["latency_s"] for r in recs]),
            "mean_tools_called": _mean([r["tools_called_count"] for r in recs]),
        }
    return out


def compare(agg: dict, cond_a: str, cond_b: str) -> dict:
    a, b = agg[cond_a], agg[cond_b]
    z, p = two_proportion_z(a["passed"], a["n"], b["passed"], b["n"])
    return {"a": cond_a, "b": cond_b, "z": z, "p_value": p,
            "rate_a": a["pass_rate"], "rate_b": b["pass_rate"]}


def render_table(agg: dict, order: list[str] | None = None) -> str:
    conds = order or list(agg)
    rows = ["| Warunek | n | pass-rate | 95% CI | FP-rate | śr. precision | śr. tokeny in | śr. latencja [s] |",
            "|---|---|---|---|---|---|---|---|"]
    for c in conds:
        a = agg[c]
        rows.append(
            f"| {c} | {a['n']} | {a['pass_rate']:.2f} | "
            f"[{a['ci_low']:.2f}, {a['ci_high']:.2f}] | {a['fp_rate']:.2f} | "
            f"{a['mean_tool_precision']:.2f} | {a['mean_input_tokens']:.0f} | {a['mean_latency_s']:.2f} |"
        )
    return "\n".join(rows)


def build_report(results_dir: Path = RESULTS_DIR) -> str:
    all_records: list[dict] = []
    for p in sorted(results_dir.glob("*.jsonl")):
        all_records.extend(load_jsonl(p))
    agg = aggregate_records(all_records)
    parts = ["# Wyniki eksperymentu (auto-generated)\n", render_table(agg)]
    return "\n".join(parts)


if __name__ == "__main__":
    out = build_report()
    target = RESULTS_DIR.parent / "results_v3.md"
    target.write_text(out, encoding="utf-8")
    print(f"Zapisano {target}")
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/report.py vulnerability_agent/tests/test_report.py
git commit -m "feat: report — agregacja JSONL, Wilson CI, test proporcji, tabele Markdown"
```

### Task 18: Orkiestrator eksperymentów (CLI Część A i B)

**Files:**
- Create: `vulnerability_agent/experiments/__init__.py`
- Create: `vulnerability_agent/experiments/run_part_a.py`
- Create: `vulnerability_agent/experiments/run_part_b.py`
- Test: `vulnerability_agent/tests/test_experiments_cli.py`

- [ ] **Step 1: Test, że moduły wystawiają listę warunków i parametr N**

```python
# vulnerability_agent/tests/test_experiments_cli.py
from vulnerability_agent.experiments.run_part_a import CONDITIONS_A, DEFAULT_N
from vulnerability_agent.experiments.run_part_b import CONDITIONS_B

def test_part_a_conditions_nonempty_and_have_baseline():
    names = {c.name for c in CONDITIONS_A}
    assert "a1_nomcp" in names and "a1_mcp_equiv" in names
    assert DEFAULT_N >= 10

def test_part_b_conditions_include_scaling_curve():
    names = {c.name for c in CONDITIONS_B}
    assert {"b1_core_rich", "b1_plus6_rich"} <= names
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_experiments_cli.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementacja**

`experiments/__init__.py`: pusty.

`experiments/run_part_a.py`:

```python
"""Część A — wartość MCP i lokalizacja wiedzy. Uruchamia warunki A1/A2 (+A3 przenośność).

Użycie:
    .venv/bin/python -m vulnerability_agent.experiments.run_part_a            # N=DEFAULT_N
    .venv/bin/python -m vulnerability_agent.experiments.run_part_a --n 12
    .venv/bin/python -m vulnerability_agent.experiments.run_part_a --large    # drugi model na kluczowych komórkach
"""
from __future__ import annotations
import argparse, dataclasses
from vulnerability_agent.config import PART_A, Condition, LARGE_MODEL
from vulnerability_agent.run_experiment import run_condition

DEFAULT_N = 12

CONDITIONS_A: list[Condition] = list(PART_A.values())

# A3 — przenośność: bierzemy dwie komórki i podmieniamy prompt_variant
_PORT_BASE = [PART_A["a2_rich_min"], PART_A["a2_weak_full"]]
A3_PORTABILITY: list[Condition] = []
for base in _PORT_BASE:
    for variant in ("persona", "paraphrase"):
        A3_PORTABILITY.append(dataclasses.replace(base, name=f"{base.name}__{variant}", prompt_variant=variant))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--large", action="store_true", help="dodaj drugi (większy) model na kluczowych komórkach")
    ap.add_argument("--portability", action="store_true", help="uruchom warianty A3")
    args = ap.parse_args()

    conditions = list(CONDITIONS_A)
    if args.portability:
        conditions += A3_PORTABILITY
    if args.large:
        key_cells = ["a2_weak_full", "a2_rich_full", "a1_mcp_equiv"]
        for k in key_cells:
            conditions.append(dataclasses.replace(PART_A[k], name=f"{k}__large", model_id=LARGE_MODEL))

    for cond in conditions:
        run_condition(cond, n=args.n)


if __name__ == "__main__":
    main()
```

`experiments/run_part_b.py`:

```python
"""Część B — złożoność i skala. B1 (krzywa narzędzi) + B2 (trudne scenariusze).

Użycie:
    .venv/bin/python -m vulnerability_agent.experiments.run_part_b --n 12
"""
from __future__ import annotations
import argparse
from vulnerability_agent.config import PART_B, Condition
from vulnerability_agent.run_experiment import run_condition

DEFAULT_N = 12
CONDITIONS_B: list[Condition] = list(PART_B.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--only", nargs="*", help="ogranicz do wskazanych warunków po nazwie")
    args = ap.parse_args()
    conditions = [c for c in CONDITIONS_B if not args.only or c.name in set(args.only)]
    for cond in conditions:
        run_condition(cond, n=args.n)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Uruchom — PASS**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests/test_experiments_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vulnerability_agent/experiments/ vulnerability_agent/tests/test_experiments_cli.py
git commit -m "feat: orkiestrator eksperymentów — CLI Część A (z A3 i --large) i Część B"
```

---

## Faza 7 — Uruchomienie, raport, sprzątanie

### Task 19: Pełny przebieg testów + mała próba na żywo

**Files:** brak nowych (weryfikacja)

- [ ] **Step 1: Cała sucha bateria testów**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests -v`
Expected: wszystkie PASS; live-smoke SKIPPED bez klucza / PASSED z kluczem.

- [ ] **Step 2: Mała próba na żywo (1 warunek, N=2) dla weryfikacji integracji i kosztu**

Run:
```bash
.venv/bin/python - <<'PY'
from vulnerability_agent.config import PART_A
from vulnerability_agent.run_experiment import run_condition
recs = run_condition(PART_A["a2_rich_full"], n=2)
print("biegów:", len(recs), "| pass:", sum(r["pass"] for r in recs))
PY
```
Expected: 12 rekordów (2×6), powstaje `vulnerability_agent/results/a2_rich_full.jsonl`. Zanotuj sumaryczne tokeny (z rekordów) → ekstrapolacja kosztu pełnego przebiegu.

- [ ] **Step 3: Commit artefaktu próbnego (opcjonalnie) lub dopisanie results/ do .gitignore**

```bash
echo "vulnerability_agent/results/*.jsonl" >> .gitignore
git add .gitignore
git commit -m "chore: results JSONL poza kontrolą wersji (artefakty przebiegu)"
```

### Task 20: Pełny przebieg eksperymentów (wymaga klucza i budżetu)

**Files:** generuje `vulnerability_agent/results/*.jsonl`

> To zadanie zużywa API. Uruchom świadomie. Budżet umiarkowany: 2 modele tylko na kluczowych komórkach, N=12.

- [ ] **Step 1: Część A**

Run: `.venv/bin/python -m vulnerability_agent.experiments.run_part_a --n 12 --portability --large`
Expected: pliki JSONL dla wszystkich warunków A1/A2 + A3 + kluczowe komórki na dużym modelu.

- [ ] **Step 2: Część B**

Run: `.venv/bin/python -m vulnerability_agent.experiments.run_part_b --n 12`
Expected: JSONL dla B1 (6 warunków) + B2 (2 warunki).

- [ ] **Step 3: Sanity — liczba rekordów**

Run: `wc -l vulnerability_agent/results/*.jsonl`
Expected: każdy plik = N × liczba przypadków w suite (basic=6, hard=6).

### Task 21: Wygeneruj raport i napisz interpretację

**Files:**
- Create: `vulnerability_agent/results_v3.md` (część auto + część pisana ręcznie)
- Modify: przenieś stary `vulnerability_agent/results.md` → `vulnerability_agent/archive/results_v1_v2.md`

- [ ] **Step 1: Auto-tabele**

Run: `.venv/bin/python -m vulnerability_agent.report`
Expected: powstaje `vulnerability_agent/results_v3.md` z tabelą zbiorczą.

- [ ] **Step 2: Dopisz sekcje interpretacyjne pod RQ1/RQ2**

Dopisz ręcznie do `results_v3.md` (po auto-tabeli) sekcje: A1 (z testem proporcji `compare(agg,"a1_nomcp","a1_mcp_equiv")` + narzut tokenów/latencji), A2 (2×2 z CI), A3 (retencja po podmianie promptu), B1 (krzywa precision vs liczba narzędzi), B2 (kompletność/FP/konflikt), oraz wnioski pod RQ1 i RQ2. Każde twierdzenie odwołuj do liczby z CI, nie do n=1.

- [ ] **Step 3: Archiwizuj stary raport**

```bash
mkdir -p vulnerability_agent/archive
git mv vulnerability_agent/results.md vulnerability_agent/archive/results_v1_v2.md
```

- [ ] **Step 4: Commit**

```bash
git add vulnerability_agent/results_v3.md vulnerability_agent/archive/results_v1_v2.md
git commit -m "docs: raport v3 (RQ1/RQ2) + archiwizacja poprzedniego raportu"
```

### Task 22: Sprzątanie legacy

**Files:**
- Delete: `agent.py`, `agent_mcp.py`, `agent_mcp_v2.py`, `run_tests.py`, `run_tests_mcp.py`, `run_iterations_mcp.py`, `run_iterations_v2.py`, `run_experiments_mcp.py`, katalog `stubs/`

- [ ] **Step 1: Potwierdź brak importów do legacy**

Run: `grep -rn "from stubs\|import stubs\|agent_mcp\|run_iterations\|run_experiments_mcp" vulnerability_agent --include='*.py' | grep -v archive`
Expected: brak wyników (poza ewentualnie samymi plikami legacy).

- [ ] **Step 2: Usuń legacy**

```bash
cd vulnerability_agent
git rm agent.py agent_mcp.py agent_mcp_v2.py run_tests.py run_tests_mcp.py \
       run_iterations_mcp.py run_iterations_v2.py run_experiments_mcp.py
git rm -r stubs
cd ..
```

- [ ] **Step 3: Pełna bateria testów po usunięciu**

Run: `.venv/bin/python -m pytest vulnerability_agent/tests -v`
Expected: wszystkie PASS/SKIP.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: usuń legacy (stare runnery, agenci, stubs) po migracji do harness"
```

---

## Self-review (wykonane przy pisaniu planu)

**Pokrycie specyfikacji:**
- §4 A1 (transport+narzut) → Task 14 (warunki `a1_*`), Task 15 (run_once direct+mcp, tokeny/latencja), Task 17 (compare + narzut), Task 21.
- §4 A2 (2×2 wiedza) → Task 14 (`a2_*`), Task 21.
- §4 A3 (przenośność) → Task 14 (`PROMPT_VARIANTS`), Task 18 (`A3_PORTABILITY`).
- §5 B1 (dystraktory/skala) → Task 11, 13 (toolsety), 14 (`b1_*`), metryka PR Task 5.
- §5 B2 (trudne scenariusze) → Task 9 (HARD), Task 14 (`b2_*`), metryki coverage/FP Task 5.
- §6 metryki → Task 4–6; statystyka → Task 7; CI/raport → Task 17.
- §7 modele → Task 14 (`SMALL/LARGE`), Task 18 (`--large`).
- §8 struktura repo → Task 1–18; archiwizacja/sprzątanie → Task 21–22.

**Spójność typów:** `Condition` (Task 14) — pola używane identycznie w Task 15/18. `aggregate_trace` zwraca `all_called`/`tools_called` (Task 6) — konsumowane w `build_record` (Task 15). `tool_selection_pr`/`project_coverage` sygnatury (Task 5) zgodne z wywołaniem w `build_record`. `wilson_ci`/`two_proportion_z` (Task 7) zgodne z `report.py` (Task 17).

**Znane ryzyka do rozstrzygnięcia w trakcie (oznaczone w zadaniach):**
- FastMCP `@mcp.tool(description=...)` — weryfikacja w Task 10 Step 4 (fallback: dwie funkcje weak/rich z ciałem na `tool_logic`).
- smolagents `Tool.forward(**kwargs)` po nazwie argumentu — test poprawiony w Task 12 Step 4.
- `plus9` → korekta na krzywą 3/6/9 (`plus6`) w Task 13 Step 3.

---

## Handoff wykonania

Po zatwierdzeniu planu — dwie opcje wykonania (patrz niżej).
