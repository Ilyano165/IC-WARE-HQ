# ADR-009: Sichtbereich (`objects.read_all`) und Objektfreigaben

**Status:** angenommen (C0) · **Bezug:** M0 „Rechte", Schritte 3/5 (Ressourcen-DENY/ALLOW, Vollausbau M4)

## Kontext
C0 verlangt: „Steuerberater → nur erlaubte Objekte". Mit den bestehenden Modulrechten (`finance.read`,
`files.read` …) sieht jeder mit dem Recht *alle* Objekte des Moduls. Die Ressourcen-Freigaben aus M0 (Schritt
3/5 der Entscheidungsreihenfolge) kommen erst mit M4. Gleichzeitig gilt CLAUDE.md Regel 5: Rechte nur aus
Rollen, keine `if role == "Steuerberater"`.

## Entscheidung
1. Neues Recht **`objects.read_all`** („alle Objekte der freigegebenen Module sehen"). Es kommt wie jedes
   Recht ausschließlich aus Rollen.
2. Sichtbarkeit eines Objekts (eine Funktion: `ichq.objects.visibility.visible_clause`):
   **Modulrecht des Typs** UND (**`objects.read_all`** ODER **selbst angelegt** ODER **ausdrücklich
   freigegeben** in `object_grants`).
3. Freigaben verwaltet, wer **`objects.share`** hat — nur für Objekte, die er selbst sieht. Jede Freigabe und
   jeder Entzug steht im Audit und im Aktivitätsverlauf.
4. Wird eine Aufgabe jemandem ohne `objects.read_all` zugewiesen, erhält er automatisch eine Freigabe **der
   Aufgabe** — nicht des Bezugsobjekts (dessen ID wird ihm dann auch nicht angezeigt).
5. Unsichtbare Objekte sind **404**, nicht 403 — man erfährt nicht, dass es sie gibt (wie fremde Firmen).

Fail closed: Eine Rolle ohne `objects.read_all` sieht nur Eigenes und Freigegebenes. Wer heute Rollen anlegt,
muss das Recht für „normale" Mitarbeiterrollen bewusst vergeben (M4-Vorlagen müssen es enthalten).

## Verworfen
- **Flag an der Mitgliedschaft** (`access_scope = restricted`): Rechtequelle außerhalb von Rollen — verstößt
  gegen Regel 5 und wäre in der M4-Vorschau „was darf diese Person" nicht erklärbar.
- **Rollenname prüfen:** verboten (Regel 5).
- **Auf M4 warten:** C0 verlangt den Test jetzt; die Tabelle `object_grants` ist genau das M0-Ressourcen-ALLOW
  auf Objektebene und wird in M4 in die Entscheidungsreihenfolge eingebettet, nicht ersetzt.

## Folgen
- M4 muss `object_grants` als Schritt 5 (Ressourcen-ALLOW) aufnehmen und Ressourcen-DENY (Schritt 3) ergänzen.
- Freigaben werden beim Neuzuweisen einer Aufgabe nicht automatisch entzogen (bewusst: Nachvollziehbarkeit).
  Offene Frage, ob das so bleiben soll.
- Rechteprüfung beim Zustellen von Benachrichtigungen nutzt dieselbe Funktion (`can_see`).
