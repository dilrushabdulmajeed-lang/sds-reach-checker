"""SDS Reader and REACH Checker: core engine.

Everything that decides a result is plain Python: regex extraction, CAS checksum
validation and exact lookups against the reference lists. AI is optional and
only writes a summary of findings that this code already produced.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).parent / "data"

# Hazard groups worth calling out for a reviewer.
CMR_CODES = {"H340", "H341", "H350", "H351", "H360", "H361", "H362"}
ACUTE_TOX_CODES = {"H300", "H301", "H310", "H311", "H330", "H331"}
AQUATIC_CODES = {"H400", "H410", "H411", "H412", "H413"}
SVHC_THRESHOLD = 0.1  # % w/w

CAS_RE = re.compile(r"\b(\d{2,7})-(\d{2})-(\d)\b")
HCODE_RE = re.compile(r"\b(EUH\d{3}|H\d{3}(?:[FDfd]{1,2})?)(?:\s*\+\s*H\d{3})*")
HCOMBO_RE = re.compile(r"\bH\d{3}(?:\s*\+\s*H\d{3})+")
SIGNAL_RE = re.compile(r"signal\s*word\s*[:\-]?\s*(danger|warning)", re.I)
SECTION_RE = re.compile(r"(?im)^\s*(?:section\s*)?(\d{1,2})\s*[.:)]?\s+[A-Z]")
# Concentrations such as "20 - 30 %", "< 1 %", ">= 0.1 - < 1 %", "25%".
CONC_RE = re.compile(
    r"(?P<lo_op>[<>≤≥]=?)?\s*(?P<lo>\d+(?:[.,]\d+)?)\s*"
    r"(?:(?:-|–|to)\s*(?P<hi_op>[<>≤≥]=?)?\s*(?P<hi>\d+(?:[.,]\d+)?)\s*)?%"
)


# ---------- reference data ----------

def load_ghs() -> dict[str, dict]:
    with open(DATA / "ghs_hazard_statements.csv", encoding="utf-8") as f:
        return {r["code"]: r for r in csv.DictReader(f)}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z]", "", h.lower())


def load_svhc() -> tuple[dict[str, dict], str]:
    """Load the official ECHA Candidate List export if present, else the sample.

    Drop the export from https://echa.europa.eu/candidate-list-table (CSV or
    XLSX) into data/ as svhc_candidate_list.csv or .xlsx. Header rows above the
    table are skipped automatically.
    """
    official_csv = DATA / "svhc_candidate_list.csv"
    official_xlsx = DATA / "svhc_candidate_list.xlsx"
    if official_xlsx.exists():
        import warnings
        import pandas as pd
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        raw = pd.read_excel(official_xlsx, header=None, dtype=str).fillna("")
        rows = raw.values.tolist()
        source = "ECHA Candidate List (official export)"
    elif official_csv.exists():
        text = official_csv.read_text(encoding="utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        source = "ECHA Candidate List (official export)"
    else:
        with open(DATA / "svhc_sample.csv", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        source = "SAMPLE list (27 well-known SVHCs), not the full official list"

    # Find the header row: the first row that mentions a CAS column.
    hdr_i = next(i for i, r in enumerate(rows) if any("cas" in _norm_header(str(c)) for c in r))
    hdr = [_norm_header(str(c)) for c in rows[hdr_i]]

    def col(*keys):
        for k in keys:
            for i, h in enumerate(hdr):
                if k in h:
                    return i
        return None

    i_name = col("substancename", "name")
    i_cas = col("cas")
    i_ec = col("ec")
    i_reason = col("reason")
    out: dict[str, dict] = {}
    for r in rows[hdr_i + 1:]:
        if i_cas is None or i_cas >= len(r):
            continue
        for cas in CAS_RE.finditer(str(r[i_cas])):
            out[cas.group(0)] = {
                "name": str(r[i_name]).strip() if i_name is not None else "",
                "ec": str(r[i_ec]).strip() if i_ec is not None else "",
                "reason": "; ".join(x.strip() for x in str(r[i_reason]).split("#") if x.strip())
                if i_reason is not None else "",
            }
    return out, source


# ---------- extraction ----------

def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def cas_checksum_ok(cas: str) -> bool:
    digits = cas.replace("-", "")
    body, check = digits[:-1], int(digits[-1])
    return sum((i + 1) * int(d) for i, d in enumerate(reversed(body))) % 10 == check


def split_sections(text: str) -> dict[int, str]:
    """Split SDS text into its 16 numbered sections (best effort)."""
    marks = [(int(m.group(1)), m.start()) for m in SECTION_RE.finditer(text)
             if 1 <= int(m.group(1)) <= 16]
    # Keep the first occurrence of each section number, in increasing order.
    seen, ordered = set(), []
    for num, pos in marks:
        if num not in seen and (not ordered or num > ordered[-1][0]):
            seen.add(num)
            ordered.append((num, pos))
    sections = {}
    for i, (num, pos) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(text)
        sections[num] = text[pos:end]
    return sections


def _to_float(s: str | None) -> float | None:
    return float(s.replace(",", ".")) if s else None


def parse_concentration(line: str) -> tuple[str, float | None]:
    """Return (as written, upper bound in %) for the first concentration on a line."""
    m = CONC_RE.search(line)
    if not m:
        return "", None
    lo, hi = _to_float(m.group("lo")), _to_float(m.group("hi"))
    upper = hi if hi is not None else lo
    return m.group(0).strip(), upper


def hcodes_in(text: str) -> list[str]:
    codes = set()
    for m in re.finditer(r"\b(EUH\d{3}|H\d{3}[FDfd]{0,2})\b", text):
        codes.add(m.group(1))
    return sorted(codes)


@dataclass
class Component:
    cas: str
    name: str
    concentration: str
    upper_pct: float | None
    hcodes: list[str]
    cas_valid: bool
    svhc: dict | None = None


@dataclass
class Report:
    product_name: str
    signal_word: str | None
    section2_hcodes: list[str]
    components: list[Component]
    issues: list[dict] = field(default_factory=list)
    svhc_source: str = ""
    sections_found: list[int] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        levels = {i["level"] for i in self.issues}
        if "high" in levels:
            return "ACTION REQUIRED"
        if "medium" in levels:
            return "REVIEW"
        return "NO FLAGS"


def _component_name(line: str, cas: str) -> str:
    before = line.split(cas)[0]
    before = re.sub(r"(CAS|EC|Index)\s*(No\.?|number)?\s*[:#]?\s*$", "", before, flags=re.I)
    before = re.sub(r"\b\d{3}-\d{3}-\d\b", "", before)  # drop EC numbers
    return " ".join(before.replace("|", " ").split()).strip(" ,;:-")


def analyse(text: str, svhc: dict[str, dict], ghs: dict[str, dict], svhc_source: str = "") -> Report:
    sections = split_sections(text)
    s1 = sections.get(1, text[:600])
    s2 = sections.get(2, "")
    s3 = sections.get(3, "")
    if not s3:
        # Fall back to the whole document if section 3 was not found.
        s3 = text

    m = re.search(r"(?im)product\s*(?:name|identifier)\s*[:\-]\s*(.+)$", s1)
    product = m.group(1).strip() if m else "Unknown product"

    sig = SIGNAL_RE.search(s2 or text)
    signal = sig.group(1).capitalize() if sig else None

    components: list[Component] = []
    seen = set()
    for line in s3.splitlines():
        for cm in CAS_RE.finditer(line):
            cas = cm.group(0)
            if cas in seen or re.fullmatch(r"\d{3}-\d{3}-\d", cas):
                continue
            seen.add(cas)
            conc, upper = parse_concentration(line.split(cas, 1)[1] if cas in line else line)
            if not conc:
                conc, upper = parse_concentration(line)
            components.append(Component(
                cas=cas,
                name=_component_name(line, cas) or "(name not found)",
                concentration=conc,
                upper_pct=upper,
                hcodes=hcodes_in(line),
                cas_valid=cas_checksum_ok(cas),
                svhc=svhc.get(cas),
            ))

    report = Report(
        product_name=product,
        signal_word=signal,
        section2_hcodes=hcodes_in(s2),
        components=components,
        svhc_source=svhc_source,
        sections_found=sorted(sections),
    )

    # ---- checks ----
    for c in components:
        if not c.cas_valid:
            report.issues.append({"level": "medium", "type": "Data quality",
                                  "detail": f"CAS {c.cas} ({c.name}) fails the CAS checksum. Likely a typo in the SDS."})
        if c.svhc:
            over = c.upper_pct is None or c.upper_pct >= SVHC_THRESHOLD
            where = f"at {c.concentration}" if c.concentration else "(concentration not stated)"
            report.issues.append({
                "level": "high" if over else "medium",
                "type": "REACH SVHC",
                "detail": (f"{c.name} (CAS {c.cas}) is on the REACH Candidate List {where}. "
                           f"Reason: {c.svhc['reason'] or 'see ECHA'}. "
                           + ("At or above 0.1% w/w, REACH information duties apply (Art. 31 SDS, Art. 33 articles)."
                              if over else "Below 0.1% w/w, check whether it can rise above the threshold.")),
            })
        if c.upper_pct is None:
            report.issues.append({"level": "low", "type": "Data quality",
                                  "detail": f"No concentration found for {c.name} (CAS {c.cas})."})

    all_codes = set(report.section2_hcodes) | {h for c in components for h in c.hcodes}
    base = {h[:4] for h in all_codes if h.startswith("H")}
    if base & CMR_CODES:
        report.issues.append({"level": "high", "type": "CMR hazard",
                              "detail": "Contains carcinogenic, mutagenic or reprotoxic hazard statements: "
                                        + ", ".join(sorted(h for h in all_codes if h[:4] in CMR_CODES)) + "."})
    if base & ACUTE_TOX_CODES:
        report.issues.append({"level": "medium", "type": "Acute toxicity",
                              "detail": "Toxic or fatal acute hazard: " + ", ".join(sorted(h for h in all_codes if h[:4] in ACUTE_TOX_CODES)) + "."})
    if base & AQUATIC_CODES:
        report.issues.append({"level": "low", "type": "Environment",
                              "detail": "Aquatic hazard: " + ", ".join(sorted(h for h in all_codes if h[:4] in AQUATIC_CODES)) + "."})

    # Signal word must be "Danger" if any classified hazard needs it.
    needs_danger = sorted(h for h in report.section2_hcodes if ghs.get(h, {}).get("signal_word") == "Danger")
    if signal == "Warning" and needs_danger:
        report.issues.append({"level": "high", "type": "SDS consistency",
                              "detail": f"Signal word is 'Warning', but {', '.join(needs_danger)} require 'Danger'."})
    if report.section2_hcodes and not signal:
        report.issues.append({"level": "medium", "type": "SDS consistency",
                              "detail": "Hazard statements present in Section 2 but no signal word found."})
    unknown = sorted(h for h in all_codes if h not in ghs and h[:4] not in ghs and not h.startswith("EUH"))
    if unknown:
        report.issues.append({"level": "medium", "type": "Data quality",
                              "detail": "Unrecognised hazard codes: " + ", ".join(unknown) + "."})
    missing = [n for n in (1, 2, 3) if n not in report.sections_found]
    if missing:
        report.issues.append({"level": "medium", "type": "Structure",
                              "detail": f"Could not find SDS section(s) {missing}. Results may be incomplete."})

    order = {"high": 0, "medium": 1, "low": 2}
    report.issues.sort(key=lambda i: order[i["level"]])
    return report
