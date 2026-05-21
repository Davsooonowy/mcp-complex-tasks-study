# Design: Complex MCP Scenarios for Vulnerability Correlation Agent

**Date:** 2026-05-22  
**Research question:** Czy agent LLM wyposażony w MCP radzi sobie ze złożonymi zadaniami agentowymi — warunkowymi wywołaniami narzędzi, partial failures, sprzecznymi sygnałami między serwisami?  
**Model:** gpt-4.1-mini  
**Framework:** smolagents + FastMCP + MCPClient

---

## Kontekst

Poprzedni eksperyment (iter_1–4 w `scenarios.py`) wykazał 100% stabilność na prostych scenariuszach (jedna zmienna naraz). Wnioski: spójność serwisów + reguły w task prompt = determinizm. Ale scenariusze były za łatwe, by odróżnić modele lub znaleźć granicę reasoning agenta.

Nowy eksperyment testuje dwie osie trudności jednocześnie:
- **MCP orchestration**: agent musi warunkowo wybierać narzędzia, obsługiwać partial failures, agregować dane z N projektów
- **Reasoning z niejednoznacznych danych**: null CVSS, patch_applied vs podatna wersja, wielokrotne CVE

---

## Scenariusze (6 przypadków)

### C1 — Zależność pośrednia (transitive dependency)
**Typ:** MCP orchestration — conditional tool call  
**Mechanizm:** `get_projects_using_library("lib-json-parser")` zwraca pustą listę (brak bezpośrednich zależności). Podatność istnieje tylko przez `lib-http-client@2.3.0`, który bundluje lib-json-parser 3.1.4.  
**Nowe narzędzie:** `get_transitive_dependencies(project_id)` w composition_service  
**Kluczowe pytanie:** Czy agent wywoła `get_transitive_dependencies` gdy bezpośrednia lista jest pusta?  
**Expected:** `STATUS=NARAŻONY, PRIORYTET=KRYTYCZNY`

### C2 — Brak CVSS (NVD pending)
**Typ:** Reasoning z niekompletnych danych  
**Mechanizm:** `vulnerability_service` zwraca `cvss_score: null`, `severity: "CRITICAL"`, `cvss_status: "RESERVED"`.  
**Kluczowe pytanie:** Czy agent użyje pola `severity` gdy `cvss_score` jest null? Czy eskaluje do KRYTYCZNY (błąd) czy zostaje na WYSOKI (reguła: unconfirmed = nie eskaluj)?  
**Expected:** `STATUS=NARAŻONY, PRIORYTET=WYSOKI`

### C3 — Błąd serwisu dla jednego projektu
**Typ:** MCP orchestration — partial failure recovery  
**Mechanizm:** `get_projects_using_library` zwraca [portal-abc, api-xyz]. `get_project_details("api-xyz")` zwraca `{"error": "Service temporarily unavailable: DB connection timeout"}`.  
**Kluczowe pytanie:** Czy agent raportuje wynik na podstawie częściowych danych (portal-abc OK = NARAŻONY) i oznacza api-xyz jako "dane niedostępne"?  
**Expected:** `STATUS=NARAŻONY, PRIORYTET=KRYTYCZNY` + wzmianka o api-xyz niedostępnym

### C4 — Patch override (sprzeczny sygnał między serwisami)
**Typ:** Reasoning — reconciling conflicting MCP data  
**Mechanizm:** Wersja biblioteki 3.1.4 (podatna < 3.2.0). Ale `composition_service` zwraca `patch_applied: true`, a `project_service` zawiera `cve_exceptions: ["CVE-2024-9999"]`. Dwa niezależne serwisy MCP potwierdzają: patch zaaplikowany.  
**Kluczowe pytanie:** Czy agent rozumie, że patch_applied + cve_exceptions override'ują wersję? Czy ufa danym z obu serwisów?  
**Expected:** `STATUS=NIE NARAŻONY, PRIORYTET=NISKI`

### C5 — 3 projekty, mieszane stany
**Typ:** MCP orchestration — multi-project aggregation  
**Mechanizm:** Trzy projekty z `get_projects_using_library`: portal-abc (3.1.4, production), api-xyz (3.1.4, staging), admin-panel (3.2.1, production). Agent musi wywołać `get_project_details` dla każdego i wybrać worst-case priority.  
**Kluczowe pytanie:** Czy agent wywołuje get_project_details dla wszystkich 3 projektów? Czy poprawnie agreguje (portal-abc prod = KRYTYCZNY dominuje)?  
**Expected:** `STATUS=NARAŻONY, PRIORYTET=KRYTYCZNY`

### C6 — Wielokrotne CVE dla tej samej biblioteki
**Typ:** Reasoning + MCP — rozszerzony kontrakt serwisu  
**Mechanizm:** `get_vulnerability("CVE-2024-9999")` zwraca główne CVE (CVSS 9.8) + pole `related_cves` wskazujące na CVE-2024-8888 (CVSS 3.1, all versions). Projekt używa 3.1.4.  
**Kluczowe pytanie:** Czy agent wspomni w rekomendacji o CVE-2024-8888 (niskie ryzyko, ale zawsze obecne)? Czy poprawnie nie eskaluje priorytetu przez niego?  
**Expected:** `STATUS=NARAŻONY, PRIORYTET=KRYTYCZNY` + wzmianka o CVE-2024-8888

---

## Iteracje (2)

### Iter C1 — Baseline: minimalne zadanie, bogate opisy narzędzi

**Task template:** Tylko format odpowiedzi — zero instrukcji o edge case'ach.  
**Tool descriptions:** Maksymalnie informatywne — `get_transitive_dependencies` ma w opisie "Call this when get_projects_using_library returns an empty list".  
**Hipoteza:** C1 i C3 zawiodą (agent nie zadba o transitive/error recovery bez explicit hints). C2 da KRYTYCZNY zamiast WYSOKI. C4 i C6 mogą przejść (model "rozumie" patch i wielokrotne CVE z danych).

### Iter C2 — Full instruktaż: explicit rules w task prompt

**Dodane do task prompt:**
```
- Jeśli get_projects_using_library zwróci pustą listę → wywołaj get_transitive_dependencies dla znanych projektów
- cvss_score = null → użyj pola severity; CRITICAL/HIGH + production → WYSOKI (nie KRYTYCZNY — brak potwierdzenia)  
- patch_applied=True lub cve_exceptions zawiera CVE ID → NIE NARAŻONY mimo podatnej wersji
- Błąd serwisu → raportuj częściowy wynik + oznacz projekt jako "dane niedostępne"
- Wiele projektów: użyj najwyższego priorytetu (worst-case)
```
**Hipoteza:** 6/6

---

## Zmiany w serwisach MCP

### composition_service.py
Nowe narzędzie:
```python
@mcp.tool()
def get_transitive_dependencies(project_id: str) -> str:
    """Check for indirect library usage through bundled dependencies.
    Call this when get_projects_using_library returns an empty list 
    to ensure no transitive exposure is missed."""
```
Scenario field: `transitive_dependencies: [{"library": "lib-json-parser", "version": "3.1.4", "via": "lib-http-client@2.3.0"}]`

Rozszerzenie `get_projects_using_library`:
- `projects_using_lib: []` → zwraca pustą listę (C1, gdzie brak bezpośrednich)
- `patch_applied` propagowany per projekt w zwracanej liście

### vulnerability_service.py
- `cvss_score` może być `None`
- Nowe pole `cvss_status`: "FINAL" | "RESERVED"  
- Nowe pole `related_cves`: lista powiązanych CVE z ich CVSS (dla C6)
- `severity` obliczany z `cvss_score` lub z `cvss_severity` w scenariuszu gdy score=null

### project_service.py
- Nowy wpis w `_PROJECTS_DB`: `admin-panel` (Internal, Marek Wiśniewski, Zespół DevOps)
- Nowe pole `service_errors: {project_id: error_message}` w scenariuszu → zwraca `{"error": ...}`
- Nowe pole `cve_exceptions: ["CVE-ID"]` przekazywane do odpowiedzi projekt

---

## Nowe pliki

```
vulnerability_agent/
  scenarios_complex.py          ← 6 scenariuszy C1-C6 z expected_status/expected_priority
  agent_mcp_complex.py          ← TASK_C1, TASK_C2, ITERATIONS_COMPLEX, MODEL="gpt-4.1-mini"
  run_iterations_complex.py     ← runner analogiczny do run_iterations_mcp.py
```

Stare pliki (`scenarios.py`, `agent_mcp.py`, `run_iterations_mcp.py`) zostają niezmienione — to punkt odniesienia.

---

## Metryki sukcesu

- Iter C1: oczekiwane ≤4/6 (baseline failures dokumentują trudność)
- Iter C2: oczekiwane 6/6  
- Kluczowe odkrycia do udokumentowania w `results.md`:
  - Które edge case'y model obsługuje bez instrukcji (z samych danych)?
  - Które wymagają explicit rules?
  - Czy gpt-4.1-mini zachowuje się inaczej niż gpt-5.2 przy tych trudnych przypadkach?

## Scoring (ważne: co liczy się jako PASS)

Automatyczny scoring parsuje `**STATUS:**` i `**PRIORYTET:**` — identycznie jak w `run_experiments_mcp.py`. Dla każdego przypadku:

- **PASS:** STATUS i PRIORYTET zgadzają się z `expected_status` / `expected_priority`
- **FAIL:** którykolwiek nie zgadza się

Dodatkowe elementy (nota o niedostępnym projekcie w C3, wzmianka o CVE-2024-8888 w C6) są **nice-to-have** — odnotowane w obserwacjach, ale nie wpływają na wynik PASS/FAIL. Dzięki temu metryki pozostają porównywalne ze starym eksperymentem.
