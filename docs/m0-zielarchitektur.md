# M0 — Zielarchitektur (verdichtet)

Verbindliche Kurzfassung des M0-Berichts „IC WARE HQ — M0: Bestandsanalyse & Zielarchitektur"
(04.10.2026). Der vollständige Bericht kann als `docs/m0-bericht.md` danebengelegt werden.
Abweichungen in M1/M2 sind in `docs/adr/` und `docs/architecture.md` begründet.

## Grundsatz

Neubau als eigenständige Codebasis (ADR-001). IC·HQ 2.x (eine Datei, SQLite, nicht mandantenfähig)
bleibt Arbeitswerkzeug von IC Ware bis zum Umzug und liefert **Fachregeln und Testszenarien, nicht Code**.

## Zielbild

- **Zwei Ebenen:** Tenant Plane (Firmen) und Control Plane (Betreiber) — getrennte Anwendungen, gemeinsamer
  Rand (Caddy) und Infrastruktur. Die Control Plane liest Firmen-Metadaten, **keine Firmendaten**.
- **Jeder Datenzugriff** läuft durch die Service-Schicht mit Mandantenkontext — auch Worker und AI.
- **Kein versteckter Master-Zugang.** Support erhält Zugriff nur über befristete (max. 72 h), für die
  Firma sichtbare, protokollierte Freigaben. Notfallzugriff nur mit zwei Betreibern.

## Daten

- PostgreSQL, ein Schema, `tenant_id NOT NULL` + zusammengesetzte Fremdschlüssel + Row-Level Security.
- Geld als ganze Cent + Währung, Zeit als `timestamptz` UTC, IDs als UUIDv7, Alembic-Migrationen
  (Expand/Contract in Produktion).
- **Firma:** slug, name, legal_name, status (`pending → active ⇄ paused/suspended → deactivated`), plan,
  Zeitzone, Sprache, Währung, Branding, Adresse, Steuerdaten, Limits. Löschen: Antrag → Bestätigung durch
  zweite Person → 30 Tage Frist → letzte Sicherung → Löschung inkl. Dateien → Löschprotokoll.
- **Person:** ein Konto, je Firma eine Mitgliedschaft (`invited | active | suspended | left`) mit eigenen
  Rollen. Firmenwahl nach Login, jeder Wechsel protokolliert.

## Rechte (M4 baut das)

Entscheidungsreihenfolge, erste zutreffende Regel gewinnt:

```
0. Firma/Mitgliedschaft nicht aktiv, Recht unbekannt              → NEIN
1. Modul durch Plan/Feature-Flag aus                              → NEIN
2. Einzelrecht DENY                                               → NEIN
3. Ressourcen-DENY (Projekt, Aufgabe, Datei, Team, Abteilung)     → NEIN
4. Einzelrecht ALLOW                                              → JA
5. Ressourcen-ALLOW                                               → JA
6. Rolle der Mitgliedschaft enthält das Recht                     → JA
7. sonst                                                          → NEIN
```

Übernommen aus dem M4-Prototyp (`docs/reference/m4-prototyp-rbac.md`): Registry im Code, keine
Platzhalter-Rechte, Rang, „nur vergeben, was man selbst hat", Last-Admin-Schutz, fail closed.
Geändert: Plattform-Admins haben in Firmendaten **keinen** Generalschlüssel.

## Weitere Zielentscheidungen

| Bereich | Entscheidung |
| --- | --- |
| Speicher | S3-kompatibel, privater Bucket, `t/<tenant>/f/<file>/v/<n>`, signierte Links ≤ 60 s nach Rechteprüfung, Inhaltsprüfung + Virenscan (ClamAV), Status `quarantined` bis geprüft |
| Automationen | Ereignisse über Transactional Outbox; Aktionen laufen mit den Rechten von `run_as_membership_id`; Schleifenschutz Tiefe 5 |
| Benachrichtigungen | Konsumenten derselben Ereignisse; Rechteprüfung **beim Zustellen**; nur Titel + Link, keine Beträge |
| AI | nie direkter DB-Zugriff; Werkzeuge = normale Service-Aufrufe mit Nutzerkontext; kein firmenübergreifender Index; schreibende Aktionen nur nach Bestätigung |
| API | eine versionierte API `/api/v1`, OpenAPI, Problem Details (RFC 9457), API-Schlüssel gehasht mit Scopes ⊆ Rechte des Erstellers, Rate-Limits je Schlüssel/Firma, fremde ID → 404 |
| Webhooks | HMAC-SHA256 mit Zeitstempel (±5 min), Wiederholung 24 h, nur HTTPS, keine privaten IPs (SSRF), Zustellprotokoll 30 Tage |
| Pläne | Daten, keine Code-Verzweigungen; Feature-Flag aus → `feature_disabled`; Limits beim Schreiben prüfen; SaaS-Abrechnung strikt getrennt von Firmenbuchhaltung |
| Onboarding | einmaliger Zufallstoken (Hash in DB), 7 Tage, Link ohne Firmen-ID/Name/E-Mail, widerrufbar, Rate-Limit |
| Betrieb | Docker Compose auf EU-Server; Kubernetes erst bei nachgewiesenem Bedarf |
| Backup | WAL-Archivierung + tägliche Vollsicherung, verschlüsselt, zweiter Standort; **wöchentlicher automatischer Restore-Test**; Aufbewahrung mit GoBD abstimmen |
| Sicherheit | jede Schicht verteidigt sich selbst; externer Pentest vor M26 |
| Tests | Ergebnis zählt nur im CI-Protokoll; Isolationstests je Endpunkt automatisch (ab M3); Mutationstests für Rechte |

## Roadmap und Tore

| Phase | Meilensteine |
| --- | --- |
| Fundament | M0 Architektur ✅ · M1 Foundation ✅ · M2 Anmeldung (Kern ✅) · M3 Mandanten · M4 Rollen & Rechte · M5 UI-Shell |
| **Tor 1** | Isolation bewiesen: Fremd-ID-Tests je Endpunkt grün, RLS greift |
| Kernprodukt | M6 Mitarbeiter/Teams · M7 Projekte/Aufgaben · M8 CRM · M9 Kommunikation · M10 Dateien/Proofing · M11 Termine/Ressourcen · M12 Finanzen/Rechnungen · M13 Angebote/Vorlagen · M14 Suche |
| **Tor 2** | Eigenbetrieb: IC Ware zieht um — vorher Server, verschlüsselte Sicherung und ein erfolgreicher Restore-Test (Teile von M22/M25 vorziehen) |
| Plattform, Verkauf | M15 Automationen · M16 Kundenportal · M17 Control Plane · M18 Onboarding · M19 Pläne/Flags/Abos · M20 API/Integrationen · M21 AI |
| **Tor 3** | Erster zahlender Kunde: nach M19, mit Auftragsverarbeitungsvertrag (AVV) und Pentest |
| Betriebsreife | M22 Backup/Restore · M23 Security-Härtung · M24 E2E/Last · M25 Produktivbetrieb · M26 Release |
| **Tor 4** | Kommerzieller Release: externer Pentest, Lasttest, geprüfte Restores |

Ein Tor ist erst passiert, wenn sein Kriterium im CI-Protokoll oder in einem Restore-Bericht belegt ist.

## Größte Risiken

Umfang vs. zwei Personen (verkaufbare Teilmenge zuerst: M1–M8 + M12 + M17–M19) · Mandantenleck
(existenzbedrohend) · Rechtsversprechen zu GoBD/XRechnung · Betrieb rund um die Uhr · Wechsel
Einmallizenz → Abo · Wettbewerb gegen Generalisten (Nische schärfen) · AVV vor dem ersten Kunden.

## Offene Fragen (Stand M2)

- [ ] Zielgruppe der ersten verkaufbaren Version
- [ ] Lokale Edition behalten?
- [x] Backend-Rahmen → FastAPI (ADR-003)
- [ ] Frontend: HTMX oder React (ADR-004, vor M5)
- [ ] Hoster/Region, Domain (`app.ic-ware.eu`?), Zahlungsanbieter, AI-Anbieter + AVV
- [ ] Aufbewahrungsfristen, Betreiber/Support-Zeiten
