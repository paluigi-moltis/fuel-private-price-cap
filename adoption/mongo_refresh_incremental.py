"""Chunked MongoDB refresh: fetch prices newer than the parquet cache and append."""
import os
import sys
from datetime import date, timedelta

import polars as pl
from dotenv import load_dotenv
from pymongo import MongoClient

REPO = "/home/ubuntu/coding/fuel-private-price-cap"
sys.path.insert(0, os.path.join(REPO, "src"))
load_dotenv(os.path.join(REPO, ".env"))

from fuel_price_cap import config  # noqa: E402
from fuel_price_cap.data import _PRICES_PIPELINE, FuelDataRepository  # noqa: E402

PARQUET = config.PRICES_RAW_PATH
FIELD = "date"

old = pl.read_parquet(PARQUET, columns=[FIELD]).max()[0, 0]
if isinstance(old, str):
    old = pl.Series([old]).str.to_date(format="%d/%m/%Y %H:%M:%S")[0]
start = old + timedelta(days=1)
end = date.today()
print("cached through:", old, "| fetching:", start, "->", end)

repo_uri = FuelDataRepository()._uri
client = MongoClient(repo_uri)
coll = client[config.DB_NAME]["prices"]

frames = []
d = start
while d <= end:
    nxt = min(d + timedelta(days=9), end)  # 10-day windows
    pipe = [
        {"$match": {FIELD: {"$gte": d.isoformat(), "$lte": nxt.isoformat()}}},
        *_PRICES_PIPELINE,
    ]
    raw = FuelDataRepository._to_frame(coll, pipe)
    frames.append(raw.select(
        pl.col("idImpianto").cast(pl.Int64).alias("id_impianto"),
        pl.col("date").str.to_date("%Y-%m-%d"),
        pl.col("descCarburante").alias("fuel"),
        pl.col("prezzo"),
        pl.col("dtComu").cast(pl.String).alias("dt_comu"),
    ))
    print(f"  {d}..{nxt}: {len(frames[-1])} rows", flush=True)
    d = nxt + timedelta(days=1)

if frames:
    new = pl.concat(frames)
    print("new rows:", new.height)
else:
    new = pl.DataFrame()
    print("no new rows")

old_full = pl.read_parquet(PARQUET)
if new.height:
    comb = pl.concat([old_full, new], how="vertical").unique(subset=[FIELD, "id_impianto", "fuel", "prezzo"], keep="last")
    comb = comb.sort([FIELD, "id_impianto"])
    comb.write_parquet(PARQUET)
    print("combined:", comb[FIELD].min(), "->", comb[FIELD].max(), "|", comb.height, "rows")
else:
    print("cache unchanged")
