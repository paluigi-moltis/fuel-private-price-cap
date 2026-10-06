"""Batch OpenAlex title searches for the cap-adoption literature review.

Builds a JSON pool of candidate works across the paper's sub-topics,
with abstracts reconstructed from the inverted index.
"""
import json
import time
import urllib.parse
import urllib.request

OUT = "adoption/literature/candidates.json"

QUERIES = [
    # Retail fuel price dynamics & asymmetry
    "retail gasoline price asymmetry",
    "gasoline price pass-through crude oil",
    "fuel price cycles retail",
    "Edgewater gasoline price war",
    "gasoline price response crude oil price changes",
    # Price ceilings
    "price ceiling gasoline",
    "price ceiling effects market",
    "regulated maximum price retail",
    "price cap regulation",
    # Spatial competition / diffusion in retail fuel
    "spatial competition gasoline stations",
    "spatial price competition retail fuel",
    "market structure gasoline prices",
    "local market power gasoline",
    "distance competition retail prices",
    # Strategic matching / price leadership / unilateral price changes
    "price leadership oligopoly",
    "strategic complementarities pricing",
    "kinked demand curve oligopoly",
    "sequential price setting retail",
    # Italian fuel market
    "fuel prices Italy",
    "Italian gasoline market regulation",
    "gasoline price dispersion Italy",
    # Price dispersion & search
    "price dispersion consumer search",
    "price dispersion gasoline",
    "search cost retail gasoline",
    # Diffusion of pricing decisions / duration models in IO
    "duration model adoption",
    "hazard model firm pricing",
    # Official statistics sampling
    "scanner data official statistics inflation",
    "price collection statistical institute bias",
]


def search_titles(query, per_page=6):
    q = urllib.parse.quote(query)
    url = (
        "https://api.openalex.org/works"
        f"?filter=title.search:{q}&per-page={per_page}&sort=cited_by_count:desc"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "HermesAgent/1.0 (mailto:research@example.com)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read()).get("results", [])


def reconstruct_abstract(inv):
    if not inv:
        return None
    pos = {}
    for word, plist in inv.items():
        for p in plist:
            pos[p] = word
    return " ".join(pos[i] for i in sorted(pos))


def slim(w):
    return {
        "id": w.get("id", "").rsplit("/", 1)[-1],
        "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
        "title": w.get("display_name"),
        "year": w.get("publication_year"),
        "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
        "authors": [a["author"]["display_name"] for a in (w.get("authorships") or [])][:6],
        "cited_by": w.get("cited_by_count"),
        "type": w.get("type"),
        "biblio": w.get("biblio") or {},
        "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
    }


def main():
    pool = {}
    for q in QUERIES:
        try:
            results = search_titles(q)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {q!r}: {e}")
            continue
        for w in results:
            wid = w.get("id", "").rsplit("/", 1)[-1]
            if wid and wid not in pool:
                pool[wid] = slim(w)
        print(f"{q!r}: {len(results)} results (pool {len(pool)})")
        time.sleep(0.15)
    with open(OUT, "w") as f:
        json.dump(list(pool.values()), f, indent=1)
    print("total unique:", len(pool))


if __name__ == "__main__":
    main()
