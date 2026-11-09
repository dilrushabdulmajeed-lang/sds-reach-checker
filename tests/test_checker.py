from pathlib import Path

import pytest

from checker import analyse, cas_checksum_ok, load_ghs, load_svhc, parse_concentration, pdf_to_text

ROOT = Path(__file__).parent.parent
GHS = load_ghs()
SVHC, SRC = load_svhc()


def run(name):
    return analyse(pdf_to_text((ROOT / "samples" / name).read_bytes()), SVHC, GHS, SRC)


@pytest.mark.parametrize("cas,ok", [("117-81-7", True), ("7732-18-5", True), ("471-34-1", True), ("471-34-2", False)])
def test_cas_checksum(cas, ok):
    assert cas_checksum_ok(cas) is ok


@pytest.mark.parametrize("line,upper", [("20 - 30 %", 30.0), ("< 0.05 %", 0.05), ("25%", 25.0), ("0,5 - 1 %", 1.0)])
def test_concentration(line, upper):
    assert parse_concentration(line)[1] == upper


def test_clean_degreaser():
    r = run("degreaser_clean.pdf")
    assert r.verdict == "NO FLAGS"
    assert len(r.components) == 3 and not any(c.svhc for c in r.components)


def test_pvc_svhc_and_typo():
    r = run("pvc_plastisol_svhc.pdf")
    assert r.verdict == "ACTION REQUIRED"
    svhc = {c.cas: c for c in r.components if c.svhc}
    assert set(svhc) == {"117-81-7", "84-74-2"}
    levels = {i["detail"].split(" (CAS")[0]: i["level"] for i in r.issues if i["type"] == "REACH SVHC"}
    assert levels["Bis(2-ethylhexyl) phthalate"] == "high"
    assert levels["Dibutyl phthalate"] == "medium"  # below 0.1 %
    assert any("471-34-2" in i["detail"] for i in r.issues)


def test_chrome_signal_word_error():
    r = run("chrome_bath_errors.pdf")
    types = {i["type"] for i in r.issues}
    assert {"REACH SVHC", "CMR hazard", "SDS consistency"} <= types
    assert r.signal_word == "Warning"


def test_no_false_positive_on_unrelated_text():
    r = analyse("SECTION 1 Product name: Water\nSECTION 2 Hazards\nNot classified\nSECTION 3 Composition\nWater 7732-18-5 100 %", SVHC, GHS, SRC)
    assert r.verdict == "NO FLAGS"
