"""SDS Reader and REACH Checker: Streamlit app."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from checker import analyse, load_ghs, load_svhc, pdf_to_text
from report_pdf import build_pdf

st.set_page_config(page_title="SDS & REACH Checker", page_icon="🧪", layout="centered")

SAMPLES = {
    "🧽 Degreaser": "samples/degreaser_clean.pdf",
    "🧴 PVC plastisol": "samples/pvc_plastisol_svhc.pdf",
    "⚙️ Chrome bath": "samples/chrome_bath_errors.pdf",
}
LEVEL_STYLE = {
    "high": ("#DC2626", "#FEF2F2", "⛔"),
    "medium": ("#D97706", "#FFFBEB", "⚠️"),
    "low": ("#2563EB", "#EFF6FF", "ℹ️"),
}
VERDICT_STYLE = {
    "ACTION REQUIRED": ("#DC2626", "#FEF2F2", "⛔", "Regulated substances or serious SDS errors found."),
    "REVIEW": ("#D97706", "#FFFBEB", "⚠️", "Some items need a closer look."),
    "NO FLAGS": ("#16A34A", "#F0FDF4", "✅", "No SVHCs or SDS errors found against the loaded reference data."),
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu, footer, header [data-testid="stToolbar"] { visibility: hidden; }
.badge { display:inline-block; background:#CCFBF1; color:#0F766E; font-size:12px; font-weight:600;
         padding:3px 10px; border-radius:999px; }
.hero h1 { font-size:2.2rem; font-weight:800; margin:.3rem 0 .2rem 0; }
.hero p { color:#4B5563; margin:0; }
.verdict { border-radius:12px; padding:16px 18px; margin:8px 0 14px 0; }
.verdict b { font-size:1.25rem; }
.kpi { border:1px solid #E5E7EB; border-left-width:5px; border-radius:12px; padding:10px 14px; background:white; }
.kpi .n { font-size:1.6rem; font-weight:800; } .kpi .l { color:#6B7280; font-size:.8rem; }
.issue { border-radius:10px; padding:10px 14px; margin:6px 0; font-size:.92rem; }
.chip { display:inline-block; border-radius:999px; padding:1px 9px; font-size:11px; font-weight:600; color:white; }
.small { color:#6B7280; font-size:.8rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def reference():
    svhc, source = load_svhc()
    return svhc, source, load_ghs()


svhc, svhc_source, ghs = reference()

st.markdown(
    '<div class="hero"><span class="badge">REACH Candidate List • UN GHS hazard codes</span>'
    "<h1>SDS & REACH Checker</h1>"
    "<p>Upload a Safety Data Sheet. Code reads it, checks every substance and hazard code, "
    "and flags what needs attention.</p></div>",
    unsafe_allow_html=True,
)
if "SAMPLE" in svhc_source:
    st.caption(f"Reference: {svhc_source}. Add the official ECHA export to data/ for full coverage.")
else:
    st.caption(f"Reference: {svhc_source}, {len(svhc)} CAS numbers.")

# ---------- input ----------
st.write("")
st.markdown("**Try a sample SDS** (fictional products)")
cols = st.columns(len(SAMPLES))
for col, (label, path) in zip(cols, SAMPLES.items()):
    if col.button(label, width="stretch"):
        st.session_state["sds_bytes"] = Path(path).read_bytes()
        st.session_state["sds_name"] = Path(path).name

qs = st.query_params.get("sample")
if qs and "sds_bytes" not in st.session_state:
    match = {Path(v).stem: v for v in SAMPLES.values()}.get(qs)
    if match:
        st.session_state["sds_bytes"] = Path(match).read_bytes()
        st.session_state["sds_name"] = Path(match).name

tab_pdf, tab_text = st.tabs(["Upload PDF", "Paste text"])
with tab_pdf:
    up = st.file_uploader("SDS PDF", type=["pdf"], label_visibility="collapsed")
    if up is not None:
        st.session_state["sds_bytes"] = up.getvalue()
        st.session_state["sds_name"] = up.name
with tab_text:
    pasted = st.text_area("Paste SDS text (sections 1 to 3 are enough)", height=160)

text, name = "", ""
if pasted.strip():
    text, name = pasted, "pasted text"
elif "sds_bytes" in st.session_state:
    name = st.session_state["sds_name"]
    try:
        text = pdf_to_text(st.session_state["sds_bytes"])
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not read this PDF: {e}")

if not text:
    st.info("Upload an SDS or pick a sample to begin.")
    st.stop()
if len(text.strip()) < 200:
    st.warning("Very little text was found. This may be a scanned PDF; text extraction needs a digital PDF.")

report = analyse(text, svhc, ghs, svhc_source)

# ---------- verdict ----------
color, bg, icon, line = VERDICT_STYLE[report.verdict]
st.markdown(
    f'<div class="verdict" style="background:{bg};border:1px solid {color}">'
    f'<b style="color:{color}">{icon} {report.verdict}</b><br>'
    f'<span>{report.product_name}</span> <span class="small">({name})</span><br>'
    f'<span class="small">{line}</span></div>',
    unsafe_allow_html=True,
)

n_svhc = sum(1 for c in report.components if c.svhc)
n_codes = len(set(report.section2_hcodes) | {h for c in report.components for h in c.hcodes})
kpis = [
    ("Substances", len(report.components), "#0F766E"),
    ("SVHCs", n_svhc, "#DC2626" if n_svhc else "#16A34A"),
    ("Hazard codes", n_codes, "#D97706" if n_codes else "#16A34A"),
    ("Signal word", report.signal_word or "None", "#6B7280"),
]
for col, (label, val, c) in zip(st.columns(4), kpis):
    col.markdown(f'<div class="kpi" style="border-left-color:{c}"><div class="n">{val}</div>'
                 f'<div class="l">{label}</div></div>', unsafe_allow_html=True)

# ---------- findings ----------
st.subheader("Findings")
if not report.issues:
    st.success("Nothing flagged.")
for i in report.issues:
    c, b, ic = LEVEL_STYLE[i["level"]]
    st.markdown(f'<div class="issue" style="background:{b};border-left:4px solid {c}">'
                f'{ic} <b>{i["type"]}</b>: {i["detail"]}</div>', unsafe_allow_html=True)

# ---------- composition ----------
st.subheader("Composition (Section 3)")
rows = []
for c in report.components:
    rows.append({
        "Substance": c.name,
        "CAS": c.cas + ("" if c.cas_valid else " ❌"),
        "Concentration": c.concentration or "not stated",
        "REACH SVHC": "⛔ Yes" if c.svhc else "No",
        "Hazard codes": ", ".join(c.hcodes) or "-",
    })
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
else:
    st.warning("No CAS numbers found in Section 3.")

with st.expander("Hazard statements explained"):
    codes = sorted(set(report.section2_hcodes) | {h for c in report.components for h in c.hcodes})
    table = []
    for h in codes:
        g = ghs.get(h) or ghs.get(h[:4]) or {}
        table.append({"Code": h, "Statement": g.get("statement", "Unknown code"),
                      "Hazard class": g.get("hazard_class", ""), "Pictogram": g.get("pictogram", ""),
                      "Signal": g.get("signal_word", "")})
    if table:
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    else:
        st.write("No hazard codes found.")

# ---------- optional AI summary ----------
api_key = os.environ.get("ANTHROPIC_API_KEY")
if api_key:
    if st.button("✨ Plain-English summary (AI, based only on the findings above)"):
        import anthropic
        facts = {
            "product": report.product_name, "verdict": report.verdict,
            "signal_word": report.signal_word, "issues": report.issues,
            "components": [{"name": c.name, "cas": c.cas, "concentration": c.concentration,
                            "svhc": bool(c.svhc)} for c in report.components],
        }
        msg = anthropic.Anthropic(api_key=api_key).messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5"),
            max_tokens=400,
            system=("You summarise SDS screening results for a safety or regulatory manager. Use ONLY "
                    "the JSON facts given. Do not add substances, rules, limits or hazards that are not "
                    "in the facts. 4 short bullet points, plain English, then one line on what to do next."),
            messages=[{"role": "user", "content": json.dumps(facts)}],
        )
        st.info(msg.content[0].text)

# ---------- export ----------
export = {
    "checked_on": date.today().isoformat(), "file": name, "product": report.product_name,
    "verdict": report.verdict, "signal_word": report.signal_word,
    "section2_hazard_codes": report.section2_hcodes, "svhc_reference": report.svhc_source,
    "issues": report.issues, "components": [asdict(c) for c in report.components],
}
slug = "".join(ch if ch.isalnum() else "-" for ch in report.product_name.lower()).strip("-")[:40]
c1, c2 = st.columns([2, 1])
c1.download_button("📄 Download PDF report", build_pdf(report, ghs, name),
                   file_name=f"sds-report-{slug}-{date.today()}.pdf", mime="application/pdf",
                   type="primary", width="stretch")
c2.download_button("Data (JSON)", json.dumps(export, indent=2),
                   file_name=f"sds-report-{slug}-{date.today()}.json", mime="application/json",
                   width="stretch")

st.markdown("---")
st.markdown(
    '<p class="small">Screening aid on public reference data (ECHA Candidate List, UN GHS codes via '
    "PubChem). Not a regulatory determination. Sample SDSs are fictional.<br>"
    'Built by <a href="https://dilrushabdulmajeed-lang.github.io/dilrusha-portfolio-v2/">'
    "Dilrusha Abdul Majeed</a></p>",
    unsafe_allow_html=True,
)
