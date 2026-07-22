# Projektregeln für Claude Code (CLAUDE.md)

> Diese Datei legt fest, wie sich Claude Code in diesem Projekt verhalten soll:
> was erlaubt ist, was verboten ist und welcher Ablauf gilt.
> Claude Code liest sie automatisch zu Beginn jeder Sitzung.
>
> **Wichtig:** Diese Regeln sind *Leitlinien/Kontext*, keine technische Sperre.
> Für eine echte Blockade (z. B. Kern-Code wirklich schützen) zusätzlich die
> Berechtigungen (`/permissions`) und/oder einen **PreToolUse-Hook** nutzen.

-----

## 0. Grundhaltung

- Im Zweifel **fragen statt raten**.
- Lieber kleine, nachvollziehbare Schritte als große, unübersichtliche Änderungen.
- Immer zuerst erklären, **was** geplant ist und **warum**, bevor etwas umgesetzt wird.
- Sprache der Antworten: die Sprache, die der Nutzer verwendet (hier: Russisch).

## 1. Befehl: `start rules`

Wenn der Nutzer **`start rules`** schreibt, fährt Claude das Projekt „hoch" und
verschafft sich einen Überblick — in dieser Reihenfolge:

1. **`CLAUDE.md` lesen** (diese Regeln) und in 3–5 Sätzen zusammenfassen.
2. **`business_plan.md` lesen** → Ziel und Kontext des Projekts verstehen.
3. **`changelog.md` lesen** → nachvollziehen, welche Änderungen schon gemacht wurden.
4. **`improvements.md` lesen** → welche Vorschläge offen, freigegeben oder erledigt sind.
5. **Kurzen Statusbericht** geben und fragen, was als Nächstes ansteht.

## 2. Projektstart — erst reden, dann coden

Bei einem neuen Projekt oder größeren Feature gilt **zwingend** diese Reihenfolge,
*bevor* eine Zeile Code geschrieben wird:

1. **Diskussionsphase.** Gemeinsam klären und schriftlich festhalten:
   - **Struktur** — Aufbau (Ordner, Module, Tech-Stack)
   - **Ziel** — Was genau soll am Ende erreicht sein?
   - **Vorgang** — Welche Schritte, in welcher Reihenfolge?
   - **Resultat** — Akzeptanzkriterien
   - Claude stellt **aktiv Rückfragen**, bis alle vier Punkte eindeutig sind.
2. **`business_plan.md` erstellen.**
3. **`improvements.md` anlegen** (siehe Abschnitt 5).
4. **`changelog.md` anlegen** (siehe Abschnitt 6).
5. Erst **nach Freigabe** der Diskussion beginnt die Umsetzung.

## 3. Verboten ohne ausdrückliche Erlaubnis

Nur nach expliziter Bestätigung. Vorschlag zeigen ist erlaubt, eigenmächtig anwenden nicht:

- **Änderungen am Kern-/Hauptinhalt-Code** (Definition unten).
- Dateien **löschen** oder **umbenennen**.
- Neue **Abhängigkeiten/Pakete** hinzufügen oder Versionen ändern.
- Größere **Refactorings** oder Architektur-Änderungen.
- **Git-Aktionen**: `commit`, `push`, `merge`, Branches löschen.
- Änderungen an **Konfig-, Build- oder CI/CD-Dateien**.
- Zugriff auf oder Änderung von **Secrets / API-Keys / `.env`**.

**Was ist „Kern-/Hauptinhalt-Code"?** (für dieses Projekt — bei Bedarf anpassen):

- `bot/core/**`
- `bot/main.py`
- `bot/db/models.py`
- `bot/config.py`
- `bot/features/calendar/caldav_client.py` (Auth/Sync-Logik, sicherheitskritisch)

Diese Pfade gelten als **geschützt**. Verbesserungen dafür kommen in
`improvements.md`; umgesetzt wird erst nach Freigabe.

## 4. Immer erwünscht

- **Viele Rückfragen** bei Unklarheit (lieber 2–4 gezielte Fragen als falsche Annahme).
- **Plan zuerst**: Was ändere ich, in welchen Dateien, mit welchem Ziel?
- **Bestätigung** einholen, bevor geschützte Bereiche berührt werden.
- **Bestehenden Stil** übernehmen.
- **Tests** schreiben/aktualisieren, wenn Logik hinzukommt oder sich ändert.
- **Dokumentation** aktuell halten.

## 5. `improvements.md` — Vorschläge sammeln, nicht heimlich umsetzen

- Jede mögliche Verbesserung wird **als Vorschlag eingetragen** — nicht sofort umgesetzt.
- Aufbau: oben Tabelle aller Tipps (Prio **1–5**, 5 = höchste), unten Detailblock je Eintrag.
- Sicherheitsbefunde kommen hierher; Schweregrad = Priorität (hoch = Prio 5).

## 6. `changelog.md` — Änderungs-Log (kurz halten)

- Jede umgesetzte Änderung in **einer Zeile**, neueste oben, mit Datum.
- Format: `- JJJJ-MM-TT — Was (kurz) — betroffene Datei(en) — Bezug: improvements #NN`

## 7. Sicherheit / Cybersecurity-Skills

- Bei sicherheitsrelevanten Themen (Auth, Eingaben, Secrets, Netzwerk, Dependencies)
  Befunde melden und Gegenmaßnahmen **vorschlagen**.
- Gefundene Probleme in `improvements.md` mit **Schweregrad** eintragen.
- **Nur defensiv** — kein Schadcode, keine echten Angriffe.

## 8. Code-Qualität (Grundregeln)

- Keine Geheimnisse/Keys im Code oder in Logs.
- Eingaben validieren, Fehler sauber behandeln.
- Keine toten Code-Reste; klare, sprechende Namen.
- Eine Änderung = ein Zweck (kleine, fokussierte Diffs/Commits).

## 9. Kommunikation

- Am Ende jeder Aufgabe: **Was wurde gemacht**, **was ist offen**, **nächster Vorschlag**.
- Unsicherheiten offen benennen.

## 10. Navigation (UI-Grundregel für JEDES Menü/Screen)

- **Zwei getrennte Knöpfe**, nicht einen mehrdeutigen:
  - **«‹ Назад»** = **ein Schritt zurück** zum vorherigen Screen (Eltern-Screen),
    NICHT zur Startseite.
  - **«🏠 Домой»** = direkt zur **Startseite** (Dashboard / Hauptmenü).
- **In jeder Screen-Funktion** anzuwenden:
  - Verschachtelter Screen (hat einen Eltern-Screen) → beide Knöpfe:
    `[‹ Назад zum Eltern] [🏠 Домой]`.
  - Oberster Screen eines Moduls (Eltern = Startseite) → nur `[🏠 Домой]`
    (ein „Zurück“ wäre dasselbe wie Home).
  - Bestätigungs-/Eingabe-Screens → `[⬅️ Отмена]` zählt als „ein Schritt zurück“;
    Home optional.
- i18n-Schlüssel: `common.back_btn` («‹ Назад»), `common.home_btn`/`common.menu_btn`
  («🏠 Домой»). Home-Callback = `CALLBACK_PREFIX + HOME_KEY`.

-----

### TL;DR

1. `start rules` → Regeln + Logs lesen → Status.
2. Erst Diskussion (Struktur, Ziel, Vorgang, Resultat) → dann Doku-Dateien → Freigabe → Code.
3. Geschützten Kern-Code **nie ohne Erlaubnis** ändern.
4. Verbesserungen → `improvements.md` (nicht heimlich umsetzen).
5. Jede Änderung → kurz in `changelog.md` mit Datum.
6. Sicherheit defensiv prüfen.
7. **Im Zweifel viele Rückfragen.**
8. Navigation: **«‹ Назад» = ein Schritt zurück**, **«🏠 Домой» = Startseite** — in jedem Screen.
