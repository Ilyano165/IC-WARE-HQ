"""Betrieb (ADR-015): Installer, Launcher, Compose, Secrets, systemd — statisch und, wo ohne Docker möglich, echt.

Den laufenden Stack (Installation, HTTPS, ClamAV, Sicherung → Totalverlust → Wiederherstellung) prüft
deploy/smoke-test.sh im CI-Job „betrieb". Hier: alles, was ohne Docker geht und schnell rot werden kann.
``ICHQ_DEPLOY_DIR`` zeigt für Mutationstests auf eine veränderte Kopie von deploy/."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
DEPLOY = Path(os.environ.get("ICHQ_DEPLOY_DIR", REPO / "deploy"))
SKRIPTE = ["install.sh", "hq", "smoke-test.sh", "generate-secrets.sh", "fix-secret-permissions.sh"]
LANGLAUFEND = {"postgres", "app", "worker", "jobs", "clamav", "scanner", "caddy"}


def _compose() -> dict[str, Any]:
    return dict(yaml.safe_load((DEPLOY / "docker-compose.yml").read_text()))


def _bash(*args: str, **kw: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", *args], capture_output=True, text=True, timeout=60, **kw)


@pytest.mark.parametrize("skript", SKRIPTE)
def test_skripte_syntax_und_ausfuehrbar(skript: str) -> None:
    pfad = DEPLOY / skript
    assert os.access(pfad, os.X_OK), f"{skript} nicht ausführbar"
    assert _bash("-n", str(pfad)).returncode == 0


def test_shellcheck() -> None:
    sc = shutil.which("shellcheck")
    if sc is None:
        if os.environ.get("CI"):
            pytest.fail("shellcheck fehlt in CI")
        pytest.skip("shellcheck nicht installiert (pip install shellcheck-py)")
    r = subprocess.run([sc, *(str(DEPLOY / s) for s in SKRIPTE)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_nur_caddy_veroeffentlicht_ports_und_alles_startet_neu() -> None:
    dienste = _compose()["services"]
    assert {n for n, d in dienste.items() if d.get("ports")} == {"caddy"}       # DB/App/ClamAV nie nach außen
    assert set(dienste) >= LANGLAUFEND
    for n in LANGLAUFEND:
        assert dienste[n].get("restart") == "unless-stopped", n                 # überlebt Neustart von Docker/Server
    for n in ("db-init", "migrate"):
        assert dienste[n].get("restart") == "no", n


def test_app_dienste_gemeinsamer_speicher_und_scanner() -> None:
    dienste = _compose()["services"]
    for n in ("migrate", "app", "worker", "jobs", "scanner"):
        d = dienste[n]
        assert d["image"] == "ic-ware-hq:local" and d["pull_policy"] == "never", n
        assert d["environment"]["ICHQ_STORAGE_BACKEND"] == "local", n
        assert f"filedata:{d['environment']['ICHQ_STORAGE_PATH']}" in d["volumes"], n   # alle sehen dieselben Dateien
        assert d["environment"]["ICHQ_PUBLIC_ORIGIN"].startswith("https://"), n
    assert dienste["scanner"]["environment"]["ICHQ_CLAMD_HOST"] == "clamav"
    assert dienste["scanner"]["command"][:2] == ["ichq", "documents-scan"]
    assert dienste["app"]["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}


def test_secrets_vollstaendig_und_besitzer_passend_zum_image() -> None:
    app_secrets = set(_compose()["services"]["app"]["secrets"])
    fix = (DEPLOY / "fix-secret-permissions.sh").read_text()
    m = re.search(r'^APP="([^"]+)"', fix, re.M)
    assert m and set(m.group(1).split()) == app_secrets            # jede App-Secret-Datei gehört UID 10001
    uid = re.search(r"^USER (\d+)", (DEPLOY / "Dockerfile").read_text(), re.M)
    assert uid and f'chown {uid.group(1)}:{uid.group(1)} "secrets/$f"' in fix


def test_generate_secrets_ueberschreibt_nie(tmp_path: Path) -> None:
    (tmp_path / "deploy").mkdir()
    for f in ("generate-secrets.sh", "fix-secret-permissions.sh"):
        shutil.copy2(DEPLOY / f, tmp_path / "deploy" / f)
    r = _bash(str(tmp_path / "deploy/generate-secrets.sh"))
    assert r.returncode == 0, r.stderr
    sec = tmp_path / "secrets"
    assert {Path(s["file"]).name for s in _compose()["secrets"].values()} <= {f.name for f in sec.iterdir()}
    assert oct(sec.stat().st_mode & 0o777) == "0o700"
    for f in sec.iterdir():
        assert f.stat().st_mode & 0o077 == 0, f.name                            # nie für Gruppe/andere lesbar
        if os.geteuid() == 0:
            assert f.stat().st_uid == (10001 if "url" in f.name or "secret" in f.name else 0), f.name
    url = (sec / "database_url").read_text()
    assert url.startswith("postgresql://ichq_app:") and (sec / "pg_app_password").read_text().strip() in url
    vorher = {f.name: f.read_bytes() for f in sec.iterdir()}
    r = _bash(str(tmp_path / "deploy/generate-secrets.sh"))
    assert r.returncode == 1 and "nichts überschrieben" in r.stdout
    assert {f.name: f.read_bytes() for f in sec.iterdir()} == vorher


@pytest.mark.parametrize("args,meldung", [
    (["--domain", "https://hq.example.de", "--email", "a@b.de"], "ungültige Domain"),
    (["--domain", "hq.example.de/pfad", "--email", "a@b.de"], "ungültige Domain"),
    (["--domain", "hq.example.de\nevil", "--email", "a@b.de"], "ungültige Domain"),
    (["--domain", "hq.example.de", "--email", "a{b}@c.de"], "ungültige E-Mail"),     # Caddyfile-Injektion
    (["--domain", "hq.example.de", "--email", "a b@c.de"], "ungültige E-Mail"),
    (["--domain", "hq.example.de", "--email", "a@b.de", "--backup-dir", "rel/pfad"], "absoluter Pfad"),
])
def test_installer_lehnt_falsche_eingaben_ab(args: list[str], meldung: str) -> None:
    r = _bash(str(DEPLOY / "install.sh"), *args)
    assert r.returncode == 1 and meldung in r.stderr, r.stderr


def test_installer_ohne_pflichtangaben_zeigt_hilfe() -> None:
    r = _bash(str(DEPLOY / "install.sh"))
    assert r.returncode == 1 and "--domain" in r.stdout


def test_launcher_hilfe_und_unbekannter_befehl() -> None:
    r = _bash(str(DEPLOY / "hq"), "help")
    assert r.returncode == 0 and "restore" in r.stdout and "setup-admin" in r.stdout
    r = _bash(str(DEPLOY / "smoke-test.sh"))
    assert r.returncode == 2 and "WEGWERF" in r.stdout                           # ohne --wegwerf passiert nichts


def test_restore_verlangt_bestaetigung() -> None:
    hq = (DEPLOY / "hq").read_text()
    teil = hq[hq.index("restore() {"):hq.index("eingabe() {")]
    pruefung, stopp = teil.index('[ "$ja" = "--yes" ] || fehler'), teil.index("compose stop")
    assert pruefung < stopp                                                    # erst bestätigen, dann anfassen


def test_systemd_units() -> None:
    for f in ("ichq.service.in", "ichq-backup.service.in", "ichq-backup.timer.in"):
        assert (DEPLOY / "systemd" / f).exists()
    install = (DEPLOY / "install.sh").read_text()
    assert "systemctl enable ichq.service" in install and "enable --now ichq-backup.timer" in install
    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze fehlt")


def test_caddy_acme_email_pflicht() -> None:
    assert "email {$ICHQ_ACME_EMAIL}" in (DEPLOY / "Caddyfile").read_text()
    assert ":?" in _compose()["services"]["caddy"]["environment"]["ICHQ_ACME_EMAIL"]


# ---- init-roles.sql: Passwörter folgen den Secret-Dateien (Wiederherstellung, Rotation) -----------------------------

def _scram_passt(geheim: str, passwort: str) -> bool:
    """Prüft ein PostgreSQL-SCRAM-SHA-256-Verifier gegen ein Passwort (RFC 5802/7677)."""
    m = re.fullmatch(r"SCRAM-SHA-256\$(\d+):([^$]+)\$([^:]+):(.+)", geheim)
    assert m, "kein SCRAM-Verifier"
    salted = hashlib.pbkdf2_hmac("sha256", passwort.encode(), base64.b64decode(m.group(2)), int(m.group(1)))
    stored = hashlib.sha256(hmac.new(salted, b"Client Key", "sha256").digest()).digest()
    return hmac.compare_digest(stored, base64.b64decode(m.group(3)))


def test_init_roles_gleicht_passwoerter_an(tmp_path: Path) -> None:
    admin = os.environ.get("ICHQ_TEST_ADMIN_URL")
    if not admin or not shutil.which("psql"):
        if os.environ.get("CI"):
            pytest.fail("psql oder ICHQ_TEST_ADMIN_URL fehlt in CI")
        pytest.skip("psql/ICHQ_TEST_ADMIN_URL fehlt")
    # Eigene Rollennamen — die Testrollen ichq_* der übrigen Suite bleiben unberührt.
    sql = (DEPLOY / "postgres/init-roles.sql").read_text().replace("ichq_", "zzinit_")
    datei = tmp_path / "init.sql"
    datei.write_text(sql)
    rollen = ("owner", "app", "platform", "worker", "auth")

    def lauf(pw: str) -> None:
        r = subprocess.run(["psql", admin, "-v", "ON_ERROR_STOP=1", "-q", *[f"-v{r}_pw={pw}-{r}" for r in rollen],
                            "-v", "dbname=zzinit_db", "-f", str(datei)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr

    def verifier(rolle: str) -> str:
        return subprocess.run(["psql", admin, "-tAc", f"SELECT rolpassword FROM pg_authid WHERE rolname = 'zzinit_{rolle}'"],
                              capture_output=True, text=True, timeout=30).stdout.strip()

    def aufraeumen() -> None:   # je Befehl ein -c: DROP DATABASE darf nicht in einer Transaktion laufen
        befehle = ["DROP DATABASE IF EXISTS zzinit_db", *(f"DROP ROLE IF EXISTS zzinit_{r}" for r in rollen)]
        r = subprocess.run(["psql", admin, "-q", "-v", "ON_ERROR_STOP=1", *(a for b in befehle for a in ("-c", b))],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr

    aufraeumen()                                            # Reste früherer Läufe verfälschen sonst das Ergebnis
    try:
        lauf("erstes")
        lauf("zweites")                                     # zweiter Lauf: Rollen existieren schon
        for r in rollen:
            assert _scram_passt(verifier(r), f"zweites-{r}"), r
            assert not _scram_passt(verifier(r), f"erstes-{r}"), r
    finally:
        aufraeumen()
