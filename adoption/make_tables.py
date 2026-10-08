"""Regenerate the LaTeX tables from R outputs (revision_samples.R).

Parses output/revision_{cox,lpm}.txt and rewrites paper_tables.tex,
paper_tables_s6.tex and paper_appendix_lpm.tex. Run after every data refresh.
"""
import re

DIR = "output"
SAMPLES = ["S1_universe", "S2_excl_agip_q8", "S3_pompe_bianche"]
SAMPLE_LABEL = {
    "S1_universe": "(1) Universe",
    "S2_excl_agip_q8": "(2) Excl.\\ Agip Eni + Q8",
    "S3_pompe_bianche": "(3) Pompe Bianche",
}
ROW_LABEL = {
    "(Intercept)": "Intercept",
    "nn_dist_km": "Nearest station (km)",
    "cap_dist_km_d0": "Nearest day-0 adopter (km)",
    "pop_density_cell": "Population per 1-km cell",
    "pre_gap_vs_cap": "Pre-cap gap (\\euro/l)",
    "n_stations_gestore": "Chain size (Gestore, stations)",
    "fuelGasolio": "Gasolio",
}

ROW_RE = re.compile(
    r"^([A-Za-z0-9_()\-\'/:&.\s]+?\S)\s+(-?[\d.e+-]+)\s+(-?[\d.e+-]+)\s+"
    r"(?:-?[\d.e+-]+\s+)?(?:-?[\d.e+-]+\s+)?-?[\d.e+-]+\s+(<\s*[\d.e+-]+|[\d.e+-]+|-?Inf)\s*$",
    re.M,
)
STAR_RE = re.compile(r"^([A-Za-z0-9_()\-\'/:&.\s]+?\S)\s+(\*+|\.?)\s*$", re.M)


def parse_samples(path):
    txt = open(path).read()
    out = {}
    for i, s in enumerate(SAMPLES):
        j = txt.find("SAMPLE: " + s)
        seg = txt[j: txt.find("SAMPLE:", j + 10)] if txt.find("SAMPLE:", j + 10) > 0 else txt[j:]
        # split coefficient table from the trailing stars block
        cut = seg.find("Signif. codes")
        table, stars_block = (seg[:cut], seg[:cut]) if cut > 0 else (seg, seg)
        if cut > 0:
            table = seg[: seg.rfind("---", 0, cut)]
        stars = {}
        for m in STAR_RE.finditer(stars_block):
            stars[m.group(1).strip()] = m.group(2).count("*")
        rows = {}
        for m in ROW_RE.finditer(table):
            name = m.group(1).strip()
            if name in rows or name.startswith("(") and name != "(Intercept)":
                continue
            try:
                coef = float(m.group(2))
            except ValueError:
                continue
            rows[name] = {
                "coef": coef,
                "se": float(m.group(3)),
                "p": m.group(4),
                "stars": stars.get(name, 0),
            }
        n = re.search(r"N = ([\d,]+), R2 = ([\d.]+), adj\. R2 = ([\d.]+)", seg)
        out[s] = {"rows": rows, "fit": n.groups() if n else None}
    return out


def fmt(x, stars, digits=4):
    s = f"{x:.{digits}f}" if digits else f"{x:.4f}"
    return s + ("$^{%s}$" % ("*" * stars) if stars else "")


cox = parse_samples(f"{DIR}/revision_cox.txt")
lpm = parse_samples(f"{DIR}/revision_lpm.txt")

# ---- counts (events / N dropped) from survival_input ----------------------
import polars as pl  # noqa: E402

sv = pl.read_csv(f"{DIR}/tables/survival_input.csv")
events = {s: None for s in SAMPLES}
import datetime as dt  # noqa: E402


def sample_of(bandiera):
    return "S3_pompe_bianche" if bandiera == "Pompe Bianche" else None


n_ev = {}
for s in SAMPLES:
    sub = sv
    if s == "S2_excl_agip_q8":
        sub = sv.filter(~pl.col("bandiera").is_in(["Agip Eni", "Q8"]))
    elif s == "S3_pompe_bianche":
        sub = sv.filter(pl.col("bandiera") == "Pompe Bianche")
    n_ev[s] = (sub.height, int(sub["event"].sum()))

# ---- paper_tables.tex (Cox) ----------------------------------------------
head = (
    "% Auto-generated: do not edit by hand.\n"
    "% Source: R/revision_samples.R -> output/revision_{cox,lpm}.txt\n"
    "% Panel window: 2026-09-28 .. 2026-10-07, gasolio cap tax-adjusted "
    "(+6.1 c/l from 2026-10-06).\n\n"
)


def cox_row(name):
    cells = []
    for s in SAMPLES:
        r = cox[s]["rows"].get(name)
        cells.append(fmt(r["coef"], r["stars"]) if r else "--")
    return f"{ROW_LABEL[name]} & " + " & ".join(cells) + r" \\"


cox_rows = "\n".join(
    cox_row(v)
    for v in ["nn_dist_km", "cap_dist_km_d0", "pop_density_cell",
              "pre_gap_vs_cap", "n_stations_gestore", "fuelGasolio"]
)
cox_table = f"""{head}\\begin{{table}}[htbp]
\\centering
\\caption{{Cox duration-model estimates by sample (coefficients; hazard ratios $=e^{{\\hat\\beta}}$)}}
\\label{{tab:cox-samples}}
\\begin{{tabular}}{{lccc}}
\\toprule
 & {SAMPLE_LABEL['S1_universe']} & {SAMPLE_LABEL['S2_excl_agip_q8']} & {SAMPLE_LABEL['S3_pompe_bianche']} \\\\
\\midrule
{cox_rows}
\\midrule
N & {n_ev['S1_universe'][0]:,}\\ & {n_ev['S2_excl_agip_q8'][0]:,}\\ & {n_ev['S3_pompe_bianche'][0]:,}\\ \\\\
Events & {n_ev['S1_universe'][1]:,}\\ & {n_ev['S2_excl_agip_q8'][1]:,}\\ & {n_ev['S3_pompe_bianche'][1]:,}\\ \\\\
\\bottomrule
\\end{{tabular}}

\\medskip
\\footnotesize Gestore-clustered robust standard errors. All models
include a Gasolio dummy. The gasolio cap threshold is adjusted for the
excise change of 6 October 2026 (see \\cref{{sec:data}}).
\\end{{table}}

"""
open("paper_tables.tex", "w").write(cox_table)

# ---- paper_tables_s6.tex (LPM core) ---------------------------------------
def lpm_row(name, digits=4):
    cells = []
    for s in SAMPLES:
        r = lpm[s]["rows"].get(name)
        d = 0 if name == "pop_density_cell" else digits
        cells.append(fmt(r["coef"], r["stars"], d) if r else "--")
    return f"{ROW_LABEL.get(name, name)} & " + " & ".join(cells) + r" \\"


lpm_rows = "\n".join(
    lpm_row(v)
    for v in ["(Intercept)", "nn_dist_km", "cap_dist_km_d0", "pop_density_cell",
              "pre_gap_vs_cap", "n_stations_gestore", "fuelGasolio"]
)
fits = [lpm[s]["fit"] for s in SAMPLES]


n0 = fits[0][0].replace(",", "\\,")
n1 = fits[1][0].replace(",", "\\,")
n2 = fits[2][0].replace(",", "\\,")


def fr(x):
    return f"{float(x):.4f}"


s6 = f"""{head}\\begin{{table}}[htbp]
\\centering
\\caption{{Adoption probability (LPM) by sample --- core covariates}}
\\label{{tab:lpm-core}}
\\begin{{tabular}}{{lccc}}
\\toprule
 & {SAMPLE_LABEL['S1_universe']} & {SAMPLE_LABEL['S2_excl_agip_q8']} & {SAMPLE_LABEL['S3_pompe_bianche']} \\\\
\\midrule
{lpm_rows}
Brand \\& region FE & Yes & Yes & Region only \\\\
\\midrule
N & {n0} & {n1} & {n2} \\\\
Adj.~$R^2$ & {fr(fits[0][2])} & {fr(fits[1][2])} & {fr(fits[2][2])} \\\\
\\bottomrule
\\end{{tabular}}

\\medskip
\\footnotesize Dependent variable: adopted (=1 if the station--fuel unit
priced at or below the cap on any day 28 Sep -- 7 Oct 2026; the gasolio
cap is tax-adjusted from 6 Oct). OLS with gestore-clustered standard
errors. Brand reference: Agip Eni in columns (1), Ala in column (2);
region reference: Abruzzo. Full brand and region coefficients in
\\cref{{app:lpm-s1,app:lpm-s2}}. In column (3) the sample is single-brand
(Pompe Bianche), so brand FE are undefined.
\\end{{table}}

"""
open("paper_tables_s6.tex", "w").write(s6)

# ---- paper_appendix_lpm.tex (brand/region FE, S1 + S2) ---------------------
txt = open(f"{DIR}/revision_lpm.txt").read()


def fe_table(sample, label, note, lab=None):
    j = txt.find("SAMPLE: " + sample)
    seg = txt[j: j + 9000]
    rows = []
    for m in re.finditer(
        r"^(bandiera_g|bandiera|regione)?([A-Za-z0-9\-'/:.&\s]+?)\s+"
        r"(-?[\d.e+-]+)\s+[\d.e+-]+\s+-?[\d.e+-]+\s+(<\s*[\d.e+-]+|[\d.e+-]+)\s*$",
        seg, re.M,
    ):
        kind, name, coef, p = m.groups()
        if kind is None:
            continue
        pv = float(p.replace("<", "").strip()) if "<" not in p else 1e-16
        st = 3 if pv < 0.001 else 2 if pv < 0.01 else 1 if pv < 0.05 else 0
        rows.append(("bandiera" if kind.startswith("bandiera") else "regione",
                     name.strip(), float(coef), st))
    body = "\n".join(
        f"{'Brand' if k == 'bandiera' else 'Region'}: {n} & {fmt(c, st)} \\\\"
        for k, n, c, st in rows
    )
    labline = f"\\label{{{lab}}}" if lab else ""
    return f"""{head}\\begin{{table}}[htbp]
\\centering
\\caption{{{label}}}
{labline}
\\begin{{tabular}}{{lr}}
\\toprule
 & Coefficient \\\\
\\midrule
{body}
\\bottomrule
\\end{{tabular}}

\\medskip
\\footnotesize {note}
\\end{{table}}

"""


t1 = fe_table(
    "S1_universe",
    "Adoption probability (LPM), universe sample --- brand and region fixed effects",
    lab="app:lpm-s1",
    note="Continuation of \\cref{tab:lpm-core} column (1). Brand\nreference: Agip Eni; region reference: Abruzzo. Brands with fewer\nthan 100 observations are grouped into OTHER.")
open("paper_appendix_lpm.tex", "w").write(t1 + fe_table(
    "S2_excl_agip_q8",
    "Adoption probability (LPM), excluding Agip Eni and Q8 --- brand and region fixed effects",
    lab="app:lpm-s2",
    note="Continues \\cref{tab:lpm-core} column (2). Brand\nreference: Ala; region reference: Abruzzo. Brands with fewer than\n100 observations are grouped into OTHER."))
print("tables regenerated")
print("cox S1 nn:", cox["S1_universe"]["rows"].get("nn_dist_km"))
print("lpm S3 nn:", lpm["S3_pompe_bianche"]["rows"].get("nn_dist_km"))
