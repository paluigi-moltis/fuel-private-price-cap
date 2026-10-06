"""Download ISTAT borders + population grid into adoption/data/ (idempotent)."""

import urllib.request
from pathlib import Path

DATA = Path("adoption/data")
URLS = {
    # generalizzata 2026 (latest release, 1 Jan 2026 reference) — WGS84
    "Limiti01012026_g.zip": "https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati/2026/Limiti01012026_g.zip",
    "GrigliaPop2021_Ind_ITA_CSV.zip": "https://www.istat.it/wp-content/uploads/2023/07/GrigliaPop2021_Ind_ITA_CSV.zip",
    "GrigliaPop2021_Ind_ITA.zip": "https://www.istat.it/wp-content/uploads/2023/07/GrigliaPop2021_Ind_ITA.zip",
}
for name, url in URLS.items():
    dest = DATA / name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"skip {name} ({dest.stat().st_size / 1e6:.1f} MB)")
        continue
    print(f"downloading {name} ...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    print(f"  -> {dest.stat().st_size / 1e6:.1f} MB")
