"""Generate three fictional Safety Data Sheets as PDFs (via headless Chrome).

All products and suppliers are invented for testing. Hazard data is simplified.
"""
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

SAMPLES = {
    "degreaser_clean": {
        "product": "AquaClean Heavy Duty Degreaser",
        "use": "Industrial cleaning of metal surfaces",
        "signal": "Danger",
        "h2": "H290 May be corrosive to metals.<br>H314 Causes severe skin burns and eye damage.",
        "rows": [
            ("Sodium hydroxide", "215-185-5", "1310-73-2", "1 - 5 %", "H290, H314"),
            ("Alcohols, C12-14, ethoxylated, sulfates, sodium salts", "500-234-8", "68891-38-3", "5 - 10 %", "H315, H318, H412"),
            ("2-Butoxyethanol", "203-905-0", "111-76-2", "1 - 5 %", "H302, H312, H332, H315, H319"),
        ],
    },
    "pvc_plastisol_svhc": {
        "product": "FlexiCoat PVC Plastisol P-200",
        "use": "Coating of fabrics and metal parts",
        "signal": "Danger",
        "h2": "H360FD May damage fertility. May damage the unborn child.",
        "rows": [
            ("Poly(vinyl chloride)", "-", "9002-86-2", "40 - 60 %", "-"),
            ("Bis(2-ethylhexyl) phthalate", "204-211-0", "117-81-7", "20 - 30 %", "H360FD"),
            ("Calcium carbonate", "207-439-9", "471-34-2", "10 - 20 %", "-"),
            ("Dibutyl phthalate", "201-557-4", "84-74-2", "< 0.05 %", "H360Df, H400"),
        ],
    },
    "chrome_bath_errors": {
        "product": "ChromaPlate HC-35 Hard Chrome Concentrate",
        "use": "Electroplating",
        "signal": "Warning",
        "h2": ("H271 May cause fire or explosion; strong oxidiser.<br>H301 Toxic if swallowed.<br>"
               "H314 Causes severe skin burns and eye damage.<br>H330 Fatal if inhaled.<br>"
               "H340 May cause genetic defects.<br>H350 May cause cancer.<br>"
               "H372 Causes damage to organs through prolonged or repeated exposure.<br>"
               "H410 Very toxic to aquatic life with long lasting effects."),
        "rows": [
            ("Chromium trioxide", "215-607-8", "1333-82-0", "25 - 35 %", "H271, H301, H311, H330, H314, H317, H334, H340, H350, H361f, H372, H410"),
            ("Sulphuric acid", "231-639-5", "7664-93-9", "1 - 2 %", "H314"),
            ("Water", "231-791-2", "7732-18-5", "", "-"),
        ],
    },
}

OTHER_SECTIONS = [
    "First-aid measures", "Fire-fighting measures", "Accidental release measures",
    "Handling and storage", "Exposure controls/personal protection",
    "Physical and chemical properties", "Stability and reactivity",
    "Toxicological information", "Ecological information", "Disposal considerations",
    "Transport information", "Regulatory information", "Other information",
]


def html(s: dict) -> str:
    rows = "".join(
        f"<tr><td>{n}</td><td>{ec}</td><td>{cas}</td><td>{c}</td><td>{h}</td></tr>"
        for n, ec, cas, c, h in s["rows"]
    )
    rest = "".join(
        f"<h2>{i} {title}</h2><p>See supplier documentation. (Fictional sample.)</p>"
        for i, title in enumerate(OTHER_SECTIONS, start=4)
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{font-family:Arial,sans-serif;font-size:11px;margin:28px}} h1{{font-size:16px}}
h2{{font-size:12px;background:#eee;padding:3px 6px;margin-top:14px}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #999;padding:3px;text-align:left}}
</style></head><body>
<h1>SAFETY DATA SHEET</h1>
<p>FICTIONAL SAMPLE FOR SOFTWARE TESTING. NOT A REAL PRODUCT.</p>
<h2>1 Identification of the substance/mixture and of the company</h2>
<p>Product name: {s['product']}<br>Recommended use: {s['use']}<br>Supplier: Example Chemicals LLC, Sharjah, UAE</p>
<h2>2 Hazards identification</h2>
<p>Signal word: {s['signal']}</p><p>Hazard statements:<br>{s['h2']}</p>
<h2>3 Composition/information on ingredients</h2>
<table><tr><th>Substance</th><th>EC No.</th><th>CAS No.</th><th>Concentration</th><th>Classification</th></tr>{rows}</table>
{rest}
</body></html>"""


if __name__ == "__main__":
    for key, s in SAMPLES.items():
        src = HERE / f"{key}.html"
        src.write_text(html(s), encoding="utf-8")
        out = HERE / f"{key}.pdf"
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={out}", src.as_uri()], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        src.unlink()
        print("wrote", out.name)
