# mcp-complex-tasks-study

**Badanie możliwości wykonywania złożonych zadań z wykorzystaniem agentów AI i protokołu MCP.**

Eksperymentalny harness mierzący, *co* protokół MCP wnosi do agenta LLM realizującego wieloetapowe zadanie korelacji — i *gdzie* leży ta wartość (w schemacie narzędzia czy w prompcie). Domeną testową jest agent korelacji podatności bezpieczeństwa, ale to tylko poligon: deterministyczne, parametryzowane dane pozwalają z góry znać poprawną odpowiedź i mierzyć zachowanie agenta z przedziałami ufności.

Pełny raport z wynikami i wnioskami: [`vulnerability_agent/results.md`](vulnerability_agent/results.md).

## Pytania badawcze

- **RQ1 — mechanizm i lokalizacja wartości.** Czy warstwa MCP zmienia zachowanie agenta ponad to, co wynika z samej informacji docierającej do modelu — a jeśli wnosi wartość, to gdzie ona mieszka: w schemacie narzędzia czy w prompcie?
- **RQ2 — granica zdolności przy złożoności i skali.** Jak wraz ze wzrostem liczby dostępnych narzędzi i złożoności zadania zmienia się zdolność agenta do poprawnej korelacji — i które właściwości projektu MCP przesuwają tę granicę?

## Najważniejsze ustalenia (skrót)

Pomiar: N=10 powtórzeń × 6 scenariuszy na warunek, 21 warunków, przedziały ufności Wilsona, test dwóch proporcji.

- **MCP to warstwa transportu.** Ten sam agent z narzędziami in-process vs przez MCP daje identyczną poprawność (100% vs 100%, p=1.0) i znikomy narzut tokenów/latencji.
- **Dominują jawne reguły w zadaniu** (+50 pp, p<0.001), nie jakość opisów narzędzi (efekt schematu na poprawność nieistotny, +10 pp, p=0.27). Bogaty schemat poprawia za to *kompletność zbierania danych* i znosi false-positive.
- **Discovery MCP jest odporne na dystraktory** — precyzja wyboru narzędzi 1.00 nawet przy 9 dostępnych serwisach; tryb porażki to niekompletność przy słabych opisach, nie błędny wybór.
- **Granica zdolności to spójność kontraktów**, nie złożoność zadania: jedyny systematyczny upadek to scenariusz sprzecznych serwisów.

## Architektura

```
                 ┌──────────────────────────────────────────┐
                 │            run_experiment.py               │
                 │   ToolCallingAgent (smolagents) × N biegów │
                 │   delivery: "mcp" (stdio)  |  "direct"      │
                 └───────┬───────────────────────────┬────────┘
       delivery=mcp      │                            │  delivery=direct
       (FastMCP/stdio)   ▼                            ▼  (in-process tools)
            ┌────────────────────────┐      ┌────────────────────────┐
            │ services/*.py          │      │ delivery/local_tools.py │
            │  get_vulnerability     │      │  te same funkcje +      │
            │  get_projects_…library │◄─────│  te same opisy z…       │
            │  get_project_details   │      │                         │
            │  + services/distractors│      └───────────┬─────────────┘
            └───────────┬────────────┘                  │
                        └──────────────┬─────────────────┘
                                       ▼
                              tool_logic.py
                     (źródło prawdy: logika + opisy weak/rich)
```

Kluczowa decyzja projektowa: logika i opisy narzędzi żyją w jednym module `tool_logic.py`, współdzielonym przez serwisy MCP i narzędzia in-process. Dzięki temu porównanie „MCP vs nie-MCP" izoluje **wyłącznie warstwę transportu** — wiedza i kod są po obu stronach identyczne.

## Struktura

```
vulnerability_agent/
├── tool_logic.py          # źródło prawdy: 3 funkcje narzędzi + opisy weak/rich
├── scenarios.py           # BASIC (6 przypadków) + HARD (6 trudnych) z oczekiwanymi wynikami
├── config.py              # Condition (warunek eksperymentu) + rejestry PART_A / PART_B
├── delivery/
│   ├── local_tools.py     # narzędzia in-process (baseline bez MCP)
│   └── mcp_tools.py        # toolsety MCP 3/6/9 (rdzeń + dystraktory)
├── services/              # 3 serwisy FastMCP (stdio) + distractors/ (6 dystraktorów)
├── metrics.py             # scoring + precision/recall + kompletność + tokeny/latencja
├── stats.py               # Wilson CI, test dwóch proporcji (bez scipy)
├── run_experiment.py      # uruchamia warunek N razy → JSONL (wznawialny)
├── report.py              # agregacja JSONL → tabele z przedziałami ufności
├── experiments/           # orkiestratory CLI: run_part_a.py, run_part_b.py
├── results.md             # RAPORT z wynikami i wnioskami
└── tests/                 # testy jednostkowe (pytest)
```

## Wymagania

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Klucz OpenAI API (do biegów eksperymentów; testy jednostkowe go nie wymagają)

## Setup

```bash
uv sync --dev
cp .env.example .env          # i wpisz OPENAI_API_KEY=sk-...
```

## Testy (bez API)

```bash
uv run pytest vulnerability_agent/tests -q
```

Testy live (`test_live_smoke.py`) uruchamiają się tylko, gdy ustawiony jest `OPENAI_API_KEY` — w przeciwnym razie są pomijane.

## Uruchamianie eksperymentów (zużywa API)

```bash
# Część A — wartość MCP i lokalizacja wiedzy (A1 baseline, A2 2×2, A3, --large = drugi model)
uv run python -m vulnerability_agent.experiments.run_part_a --n 10 --portability --large

# Część B — złożoność i skala (krzywa 3/6/9 narzędzi + trudne scenariusze)
uv run python -m vulnerability_agent.experiments.run_part_b --n 10

# Tabela zbiorcza z surowych JSONL
uv run python -m vulnerability_agent.report
```

Surowe wyniki trafiają do `vulnerability_agent/results/*.jsonl` (poza kontrolą wersji). Runner jest **wznawialny** — ponowne uruchomienie pomija już policzone biegi `(run_idx, scenariusz)`, więc przerwany przebieg nie traci (ani nie powtarza) zapłaconych wywołań.

## Stack

| Komponent | Biblioteka |
|---|---|
| Framework agenta | [smolagents](https://github.com/huggingface/smolagents) (`ToolCallingAgent`, `MCPClient`) |
| Protokół MCP | [mcp](https://github.com/modelcontextprotocol/python-sdk) (FastMCP, transport stdio) |
| Modele | OpenAI `gpt-4.1-mini` (główny), `gpt-5.2` (kluczowe komórki) |
| Statystyka | własna (Wilson CI, test dwóch proporcji) — bez scipy |
| Menedżer pakietów | [uv](https://docs.astral.sh/uv/) |
