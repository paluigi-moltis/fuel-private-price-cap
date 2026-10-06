"""Who is the single station first seen on Oct 3 with dtComu Oct 1? And check
the '16/15 absent' claim: did they appear on Oct 2 at all?"""
import polars as pl

enr = (
    pl.read_parquet("data/prices_enriched.parquet")
    .with_columns(
        comu_date=pl.col("dt_comu").str.strptime(pl.Date, "%d/%m/%Y %H:%M:%S", strict=False)
    )
    .filter(pl.col("tipo_impianto") == "Stradale")
)

late = enr.filter(pl.col("comu_date") == pl.date(2026, 10, 1))
first_seen = late.group_by("id_impianto", "fuel").agg(first_date=pl.col("date").min())
stragglers = first_seen.filter(pl.col("first_date") == pl.date(2026, 10, 3))
print("stragglers (first seen Oct 3):")
rows = enr.join(
    stragglers.select("id_impianto", "fuel"), on=["id_impianto", "fuel"], how="semi"
).filter(pl.col("date") >= pl.date(2026, 10, 1))
print(
    rows.select(
        "id_impianto", "fuel", "date", "prezzo", "dt_comu", "bandiera", "gestore"
    ).sort("id_impianto", "fuel", "date")
)

# the 16/15 'absent on Oct 1' stations: on which extract dates do they appear?
d1_ids = enr.filter(pl.col("date") == pl.date(2026, 10, 1)).select("id_impianto", "fuel")
d2 = enr.filter(pl.col("date") == pl.date(2026, 10, 2))
late2 = d2.filter(pl.col("comu_date") == pl.date(2026, 10, 1))
absent = late2.join(d1_ids, on=["id_impianto", "fuel"], how="anti")
print("\n'absent from Oct-1 data' stations and their extract dates:")
print(
    enr.join(absent.select("id_impianto", "fuel"), on=["id_impianto", "fuel"], how="semi")
    .filter(pl.col("date") >= pl.date(2026, 9, 30))
    .group_by("id_impianto", "fuel")
    .agg(dates=pl.col("date").sort().unique())
    .with_columns(n_dates=pl.col("dates").list.len())
    .sort("id_impianto", "fuel")
    .head(40)
)
