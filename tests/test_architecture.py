"""Architekturregeln, die nicht vom Fleiß abhängen dürfen."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "ichq"


@pytest.mark.skipif(shutil.which("lint-imports") is None, reason="import-linter nicht installiert")
def test_schichtregeln() -> None:
    r = subprocess.run(["lint-imports"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_keine_riesendatei() -> None:
    zu_gross = [(p.relative_to(ROOT), n) for p in SRC.rglob("*.py")
                if (n := len(p.read_text(encoding="utf-8").splitlines())) > 400]
    assert zu_gross == [], f"Dateien über 400 Zeilen: {zu_gross}"


def test_keine_geheimnisse_im_code() -> None:
    muster = re.compile(r"(postgres(ql)?(\+\w+)?://\w+:[^@\s/'\"{]+@|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)")
    funde = [str(p.relative_to(ROOT)) for p in [*SRC.rglob("*"), *(ROOT / "deploy").rglob("*"), ROOT / ".env.example"]
             if p.is_file() and muster.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert funde == [], funde


def test_keine_rollennamen_im_code() -> None:
    """M0: kein `if role == "ceo"`. Rollen sind Daten, keine Code-Verzweigungen."""
    muster = re.compile(r"""role\w*\s*==\s*['"]""", re.IGNORECASE)
    funde = [str(p.relative_to(ROOT)) for p in SRC.rglob("*.py") if muster.search(p.read_text(encoding="utf-8"))]
    assert funde == []
