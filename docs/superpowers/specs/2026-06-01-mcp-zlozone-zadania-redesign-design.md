# Badanie możliwości wykonywania złożonych zadań z wykorzystaniem agentów AI i protokołu MCP — projekt badania (redesign)

Data: 2026-06-01
Status: zaakceptowany do implementacji

---

## 1. Kontekst i motywacja

Istniejące badanie (`vulnerability_agent/results.md`, Eksperyment I + II) ma trzy wady metodologiczne, które uniemożliwiają wyciągnięcie obronionych wniosków na pracownię problemową:

1. **Główna teza nie jest mierzona.** Wniosek „MCP nie zmienia mechanizmu reasoning" wymaga warunku *bez MCP* do porównania, a wszystkie dotychczasowe eksperymenty biegną wyłącznie przez MCP. Manipulowane czynniki (jakość opisów, framing zadania) nie są specyficzne dla MCP — działają identycznie w zwykłym function-callingu. Istniejące `agent.py` (function-calling, gpt-5.2) vs `agent_mcp.py` (MCP, gpt-4.1-mini) różnią się modelem i promptem → porównanie skonfundowane.
2. **Metryka wysycona (ceiling effect).** Binarne pass/fail na 6 przypadkach; przy 6/6 i 18/18 pomiar nie różnicuje niczego. Metryka `tools_called` (max 3, waha się 2.7–2.8) również martwa.
3. **Atrybucje przyczynowe z n=1.** Eksperyment I przypisuje poprawę konkretnym czynnikom na podstawie pojedynczych uruchomień; przy niedeterminizmie LLM to może być szum. Powtarzano tylko konfigurację finalną.

Dodatkowo „złożone zadania agentowe" z tytułu są w istocie sztywnym 3-hop lookupem — brak wyboru narzędzi spośród wielu, danych sprzecznych/brakujących, wielu CVE.

Redesign naprawia wszystkie cztery punkty: wprowadza prawdziwy baseline, utrudnia zadania do poziomu generującego wariancję, wymienia metryki na bogatsze i wprowadza powtórzenia ze statystyką.

## 2. Pytania badawcze

- **RQ1 (mechanizm i lokalizacja wartości).** Czy warstwa MCP zmienia zachowanie agenta ponad to, co wynika z samej informacji docierającej do modelu — a jeśli wnosi wartość, to gdzie ona mieszka: w schemacie narzędzia czy w prompcie?
- **RQ2 (granica zdolności przy złożoności i skali).** Jak wraz ze wzrostem liczby dostępnych narzędzi i złożoności zadania zmienia się zdolność agenta do poprawnej korelacji — i które właściwości projektu MCP (jakość opisów, spójność kontraktów) przesuwają tę granicę?

## 3. Domena (bez zmian)

Agent korelacji podatności: 3 serwisy MCP (`get_vulnerability`, `get_projects_using_library`, `get_project_details`). Agent łączy dane i zwraca STATUS + PRIORYTET + uzasadnienie. Dane stub deterministyczne, parametryzowane przez scenariusz. CVE testowe: `CVE-2024-9999` (lib-json-parser < 3.2.0).

## 4. Część A — wartość MCP i lokalizacja wiedzy

Zasada: kontrolujemy całkowitą informację docierającą do modelu; zmieniamy tylko mechanizm dostarczania i lokalizację wiedzy. Ten sam model, te same dane, te same scenariusze.

### A1 — efekt samego transportu

| Warunek | Dostarczanie | Wiedza |
|---|---|---|
| `noMCP` | function-calling in-process (jak `agent.py`) | reguły w prompcie + słaby opis narzędzia |
| `MCP-equiv` | MCP (stdio) | identyczne reguły w prompcie + słaby opis |

Hipoteza H-A1: `noMCP` ≈ `MCP-equiv` w poprawności (różnica nieistotna statystycznie) → MCP nie zmienia reasoning na poziomie tokenów. Jednocześnie mierzymy narzut: latencja, liczba tokenów, koszt startu procesów stdio.

### A2 — gdzie mieszka wiedza (2×2 w obrębie MCP)

| | prompt: minimalny (trigger) | prompt: pełne reguły |
|---|---|---|
| **schemat: słaby** | baseline zdegradowany | wiedza tylko w prompcie |
| **schemat: bogaty** | wiedza tylko w schemacie | obie (referencja) |

Hipoteza H-A2: wiedza dziedzinowa istotna dla decyzji (np. „środowisko determinuje priorytet") przeniesiona do schematu poprawia wynik bez zmiany promptu; wiedza ilościowa (dokładne progi) wymaga promptu. Oba czynniki addytywne.

### A3 — test przenośności (najmocniejszy dowód wartości MCP)

Bierzemy dwie komórki z A2: `schemat bogaty / prompt minimalny` oraz `schemat słaby / prompt pełny`. Dla każdej stosujemy 3 warianty promptu: (a) bare trigger, (b) inna persona, (c) parafraza. Mierzymy retencję poprawności.

Hipoteza H-A3: wiedza w schemacie przeżywa podmianę promptu (mała degradacja); wiedza w prompcie ginie przy podmianie na bare trigger (duża degradacja). To pokazuje, że schemat MCP jest przenośnym nośnikiem wiedzy.

## 5. Część B — złożoność i skala

### B1 — wybór narzędzia przy skali (dystraktory)

Dorzucamy serwisy-dystraktory MCP (plausible, nierelewantne: `get_weather`, `get_invoice`, `get_employee`, `get_license`, `get_incident`, `get_deployment_log`, …). Rozmiar zestawu narzędzi: **3 → 6 → 12**. Krzyżujemy z jakością opisów (słaby/bogaty).

Metryki: precision/recall wyboru narzędzi (czy agent wywołał właściwe 3 i tylko właściwe), poprawność zadania w funkcji liczby narzędzi.

Hipoteza H-B1: przy 3 narzędziach jakość opisu nieistotna (zawsze trafia); przy 12 staje się dominującym czynnikiem poprawnego wyboru. Słabe opisy → spadek precision wraz ze wzrostem N; bogate → utrzymanie.

### B2 — trudniejsze scenariusze (wieloetapowość)

Nowy zestaw scenariuszy wymuszający rozgałęzienia:

- **flota multi-project**: 5 projektów (podatny / bezpieczny / staging / nie-w-inwentarzu / podatny-prod) → werdykt per-projekt + rollup
- **multi-library**: projekt używa kilku bibliotek, podatna tylko jedna → nie wolno fałszywie flagować pozostałych
- **multi-CVE**: dwa CVE naraz
- **serwisy sprzeczne**: uogólnienie `COMP_VERSION=1` (jeden serwis zgłasza zasób, drugi go nie zna) → test wykrycia konfliktu
- **decoy CVE**: CVE niedotyczące żadnego naszego projektu
- **wersja graniczna**: dokładnie 3.2.0 (próg podatności)

Metryki: kompletność (pokrycie wszystkich dotkniętych projektów), false-positive rate (oznaczanie bezpiecznych), wykrycie konfliktu — obok STATUS/PRIORYTET.

## 6. Metryki i statystyka (wspólny fundament)

Każdy bieg agenta loguje:
- **STATUS** i **PRIORYTET** osobno (nie tylko łączny pass)
- **precision/recall wyboru narzędzi**; efektywność wywołań: zbędne / brakujące / zła kolejność
- **kompletność korelacji** i **false-positive** (multi-project)
- **odporność** przy danych sprzecznych/brakujących (czy wykrył konflikt vs zgadł)
- **latencja** i **liczba tokenów** (prompt+completion) — dla A1
- pełny ślad wywołań narzędzi

Agregacja: każdy warunek uruchamiany **N≥10–12 razy**; raportujemy rate + **przedział ufności Wilsona 95%**. Porównania dwóch warunków: test dwóch proporcji (z) lub Fisher exact dla małych N; raport wielkości efektu. Surowe wyniki → JSONL per bieg (powtarzalność).

## 7. Modele (umiarkowany budżet)

Dwa modele: mały (klasa gpt-4.1-mini / haiku) i duży (klasa gpt-5.x). Pełna siatka na jednym modelu; kluczowe komórki na drugim → test hipotezy „bogate kontrakty częściowo zastępują pojemność modelu" (H-MODEL). N i liczba modeli to pokrętła budżetu.

Szacunkowy budżet prób (regulowalny):
- Część A: ~5 warunków × ~8 scenariuszy × N12 × 2 modele
- Część B1: 3 rozmiary × 2 opisy × podzbiór scenariuszy × N12
- Część B2: ~6 trudnych scenariuszy × ~2 konfiguracje × N12

## 8. Architektura i reorganizacja repo

Refaktor do **config-driven harness** — warunek eksperymentu jest deklaratywnym obiektem, nie osobnym skryptem.

Proponowana struktura `vulnerability_agent/`:

```
config.py            # definicja Condition: delivery, desc, prompt, toolset, model, scenario_suite
scenarios.py         # zestawy: BASIC (obecne 6), HARD (B2), + parametry multi-project/multi-lib/multi-cve
services/            # istniejące 3 serwisy + nowe serwisy-dystraktory (B1)
  distractors/       # get_weather, get_invoice, ... (FastMCP stub)
delivery/
  mcp_runner.py      # agent przez MCPClient (parametryzowany toolset)
  direct_runner.py   # agent przez in-process function-calling (baseline noMCP)
metrics.py           # status/priority/precision/recall/completeness/false-positive/latency/tokens
stats.py             # Wilson CI, test dwóch proporcji / Fisher, wielkość efektu
run_experiment.py    # uruchamia warunek N razy, zapisuje JSONL
experiments/
  part_a.py          # warunki A1/A2/A3
  part_b.py          # warunki B1/B2
report.py            # generuje tabele + CI -> results_v3.md
results/             # JSONL surowe + tabele
```

`results.md` (stary) → przeniesiony do `archive/results_v1_v2.md`. Nowy raport pisany pod RQ1/RQ2.

## 9. Co NIE wchodzi w zakres (YAGNI)

- Brak realnych integracji (dane pozostają deterministycznymi stubami)
- Brak fine-tuningu / promptów per-model (te same prompty dla obu modeli — to jest częścią pomiaru)
- Brak więcej niż 2 modeli i więcej niż 12 narzędzi w B1 (ograniczenie budżetu)
- Brak transportu innego niż stdio dla MCP (jeden transport, by nie konfundować)

## 10. Kryteria sukcesu

- RQ1 ma odpowiedź popartą testem statystycznym (A1 istotność/brak istotności + A2/A3 efekty z CI)
- RQ2 ma krzywą precision/recall vs liczba narzędzi (B1) i tabelę kompletność/false-positive na trudnych scenariuszach (B2)
- Każde twierdzenie per-czynnik oparte na N≥10 z przedziałem ufności, nie na n=1
- Pełna powtarzalność: JSONL + config-driven runner pozwala odtworzyć każdą liczbę w raporcie
```
