# Agent korelacji podatności — notatki robocze

## Problem do rozwiązania

Gdy pojawia się nowa podatność, organizacja musi odpowiedzieć na trzy pytania — a każde wymaga danych z innego systemu:

- Czy ta biblioteka (i konkretna wersja) w ogóle nas dotyczy?
- Które z naszych produktów / projektów jej używają?
- Gdzie konkretnie to działa / kto jest właścicielem?

Ręczne zestawianie tych danych jest czasochłonne i podatne na błędy. Chcemy sprawdzić, czy agent LLM potrafi samodzielnie przeprowadzić tę korelację.

> **Cel badawczy:** zweryfikować, czy agent wyposażony w trzy niezależne serwisy potrafi autonomicznie zebrać dane, powiązać je i wydać jednoznaczną ocenę narażenia — wraz z uzasadnieniem krok po kroku.

---

## Dwa warianty kontekstu

### Wariant A — firma z urządzeniami (IoT / embedded / infrastruktura)

| Serwis | Co zwraca |
|---|---|
| **Serwis podatności** | CVE, CVSS score, dotknięte wersje biblioteki |
| **Serwis składu SW** | Produkt X = lib A v1.2 + lib B v3.1 + lib C v2.0 |
| **Serwis inwentaryzacji** | Urządzenie Y → ma wdrożony produkt X, lokalizacja, właściciel |

**Pytanie końcowe:** czy urządzenie Y działające w terenie jest narażone na tę podatność?

**Przykład odpowiedzi:** *"Urządzenie prod-gateway-07 (hala produkcyjna, Gdańsk) używa firmware v2.3 zawierającego lib-json-parser 3.1.4 — wersja podatna. Wymagany update."*

---

### Wariant B — software house / agencja (projekty klientów)

| Serwis | Co zwraca |
|---|---|
| **Serwis podatności** | CVE, CVSS score, dotknięte wersje biblioteki |
| **Serwis składu SW** | Projekt X = lib A v1.2 + lib B v3.1 + lib C v2.0 |
| **Serwis projektów** | Projekt X → klient ABC, środowisko produkcyjne, opiekun: Jan Kowalski |

**Pytanie końcowe:** które projekty klientów są narażone i kto musi zareagować?

**Przykład odpowiedzi:** *"Projekt 'Portal klienta ABC' używa lib-json-parser 3.1.4 — wersja podatna, CVSS 9.8. Środowisko produkcyjne, opiekun: Jan Kowalski. Wymagana akcja przed wdrożeniem patcha."*

---

## Krok po kroku — jak agent to łączy

Przykład: pojawia się CVE-2024-9999, biblioteka `lib-json-parser < 3.2.0`, CVSS 9.8 (krytyczna).

| Krok | Akcja agenta | Wynik |
|---|---|---|
| 1 | Zapytaj serwis podatności o CVE-2024-9999 | `lib-json-parser < 3.2.0` jest podatna |
| 2 | Zapytaj serwis składu — które produkty/projekty używają tej biblioteki | „Aplikacja płatności v2" używa wersji 3.1.4 → podatna |
| 3 | Zapytaj serwis inwentaryzacji/projektów gdzie to działa | Serwer prod-payments-01 / klient ABC, środowisko produkcyjne |
| 4 | Wyciągnij wniosek | **Krytyczne narażenie. Właściciel: Zespół Fintech. Upgrade do 3.2.0.** |

---

## Dlaczego stub-serwisy — klucz do weryfikowalności

Zamiast prawdziwych integracji budujemy **stub-serwisy** — funkcje z danymi zakodowanymi na stałe. Zmiana jednego atrybutu → przewidywalny wynik → łatwa weryfikacja czy reasoning agenta jest poprawny.

| Co zmieniamy w stub-ie | Oczekiwana odpowiedź agenta | Co testujemy |
|---|---|---|
| Wersja biblioteki: 3.1.4 (podatna) | „Narażony" | Podstawowa korelacja wersji |
| Wersja biblioteki: 3.2.1 (bezpieczna) | „Nie narażony" | Rozróżnienie wersji powyżej progu |
| Produkt/projekt nie w inwentarzu | „Brak aktywów" | Graceful handling braku danych |
| CVSS zmieniony na 2.0 | „Niskie ryzyko, brak priorytetu" | Wpływ severity na rekomendację |
| Środowisko: test zamiast produkcja | Niższy priorytet akcji | Kontekst środowiska w reasoning-u |

> **Zasada:** zmieniamy jeden atrybut na raz. Skoro dane są deterministyczne, wiemy z góry co agent powinien odpowiedzieć.

---

## Co wpływa na jakość reasoning-u

- **Opis narzędzi (tool descriptions)** — agent decyduje kiedy i w jakiej kolejności wywołać serwisy na podstawie ich opisów. Słaby opis → pominięty krok lub odpowiedź bez korelacji.
- **Prompt systemowy** — sam trigger „nowa podatność" to za mało. Agent musi wiedzieć, że jego zadaniem jest ustalenie narażenia przechodząc przez wszystkie trzy źródła.
- **Multi-step reasoning** — jeśli agent odpowiada po pierwszym wywołaniu, to nie jest korelacja, to look-up. Kluczowe pytanie: czy agent naturalnie „chce" zebrać dane ze wszystkich źródeł przed wnioskiem?

---

## To do

1. Trzy stub-serwisy jako proste funkcje Python/JS z deterministycznymi danymi
2. Agent LLM z dostępem do tych narzędzi (Claude API + tool use)
3. Zestaw 5 przypadków testowych (jedna zmienna na raz)
4. Weryfikacja: czy odpowiedź zmienia się zgodnie z oczekiwaniem przy każdej zmianie stub-a
5. Analiza: co w prompcie / opisie narzędzi poprawia lub psuje reasoning
6. Decyzja: wariant A (urządzenia) czy B (projekty SW) — lub oba dla porównania