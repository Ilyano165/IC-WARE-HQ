# ADR-005: Betrieb mit Docker Compose und Caddy auf einem EU-Server

**Status:** angenommen, Anbieter offen · **Grundlage:** M0, Abschnitt 29

## Entscheidung
Docker Compose auf einem einzelnen Server; Caddy als Reverse Proxy mit automatischem TLS; Images ohne
Root-Rechte, Abhängigkeiten nur mit geprüften Hashes; Geheimnisse als Docker-Secrets.

## Verworfen
Kubernetes: für zwei Personen und die ersten Kunden unverhältnismäßig. Neu bewerten, wenn ein Server
nachweislich nicht mehr reicht.

## Offen
Hoster und Region (M0 schlägt Hetzner Deutschland vor). Backup-Ziel (M22, aber vor Tor 2 nötig).
