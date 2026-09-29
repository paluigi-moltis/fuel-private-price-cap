"""Data access layer: MongoDB fetch + parquet persistence, and price cleaning."""

from __future__ import annotations

import os
from typing import Any

import polars as pl
from pymongo import MongoClient
from pymongo.collection import Collection

from fuel_price_cap import config

_PRICES_PIPELINE: list[dict[str, Any]] = [
    {
        "$match": {
            "date": {"$gte": config.PRICES_FROM.isoformat()},
            "isSelf": 1,
            "descCarburante": {"$in": list(config.FUELS)},
        }
    },
    {
        "$project": {
            "_id": 0,
            "idImpianto": 1,
            "date": 1,
            "descCarburante": 1,
            "isSelf": 1,
            "prezzo": 1,
            "dtComu": 1,
        }
    },
]

_STATIONS_PIPELINE: list[dict[str, Any]] = [
    {
        "$project": {
            "_id": 0,
            "idImpianto": 1,
            "Gestore": 1,
            "Bandiera": 1,
            "Tipo Impianto": 1,
            "Provincia": 1,
            "Latitudine": 1,
            "Longitudine": 1,
            "date": 1,
        }
    }
]

_TAX_PIPELINE: list[dict[str, Any]] = [
    {
        "$project": {
            "_id": 0,
            "application_date": 1,
            "benzina_tax": 1,
            "gasolio_tax": 1,
        }
    },
    {"$match": {"application_date": {"$gte": config.TAX_FROM.isoformat()}}},
    {"$sort": {"application_date": 1}},
]


class FuelDataRepository:
    """Fetches the raw collections from MongoDB into Polars frames.

    Field names in MongoDB are Italian/mixed-case (``Tipo Impianto``,
    ``Latitudine``); the repository renames them to snake_case and parses
    dates, so downstream code never sees the raw schema.
    """

    _PRICES_REQUIRED = ("idImpianto", "date", "descCarburante", "prezzo")
    _STATIONS_REQUIRED = ("idImpianto", "date", "Bandiera", "Provincia")

    def __init__(self, uri: str | None = None) -> None:
        self._uri = uri or os.environ["MONGO_URI"]

    def fetch_all(self) -> dict[str, pl.DataFrame]:
        client = MongoClient(self._uri)
        try:
            return {
                "prices": self._fetch_prices(client),
                "stations": self._fetch_stations(client),
                "tax": self._fetch_tax(client),
            }
        finally:
            client.close()

    def _fetch_prices(self, client: MongoClient) -> pl.DataFrame:
        raw = self._to_frame(client[config.DB_NAME]["prices"], _PRICES_PIPELINE)
        missing = [c for c in self._PRICES_REQUIRED if c not in raw.columns]
        if missing:
            msg = (
                f"prices collection is missing required field(s) {missing}; "
                "the join with stations is impossible. Raw columns: "
                f"{raw.columns}"
            )
            raise RuntimeError(msg)
        return raw.select(
            pl.col("idImpianto").cast(pl.Int64).alias("id_impianto"),
            pl.col("date").str.to_date("%Y-%m-%d"),
            pl.col("descCarburante").alias("fuel"),
            pl.col("prezzo").cast(pl.Float64),
            pl.col("dtComu").cast(pl.String).alias("dt_comu"),
        ).sort("date", "id_impianto")

    def _fetch_stations(self, client: MongoClient) -> pl.DataFrame:
        raw = self._to_frame(client[config.DB_NAME]["stations"], _STATIONS_PIPELINE)
        missing = [c for c in self._STATIONS_REQUIRED if c not in raw.columns]
        if missing:
            msg = (
                f"stations collection is missing required field(s) {missing}. "
                f"Raw columns: {raw.columns}"
            )
            raise RuntimeError(msg)
        provincia = self._provincia_expression()
        return (
            raw.select(
                pl.col("idImpianto").cast(pl.Int64).alias("id_impianto"),
                pl.col("date").str.to_date("%Y-%m-%d"),
                pl.col("Gestore").cast(pl.String).alias("gestore"),
                pl.col("Bandiera").cast(pl.String).alias("bandiera"),
                self._tipo_impianto_expression(),
                provincia,
                pl.col("Latitudine").cast(pl.Float64).alias("latitude"),
                pl.col("Longitudine").cast(pl.Float64).alias("longitude"),
            )
            # one row per (station, snapshot): keep the last if duplicated
            .unique(subset=["id_impianto", "date"], keep="last").sort(
                "date", "id_impianto"
            )
        )

    @staticmethod
    def _fetch_tax(client: MongoClient) -> pl.DataFrame:
        raw = FuelDataRepository._to_frame(client[config.DB_NAME]["tax"], _TAX_PIPELINE)
        return (
            raw.select(
                pl.col("application_date").str.to_date("%Y-%m-%d"),
                pl.col("benzina_tax").cast(pl.Float64),
                pl.col("gasolio_tax").cast(pl.Float64),
            )
            # tax values are EUR per 1000 litres
            .unique(subset=["application_date"], keep="last").sort("application_date")
        )

    @staticmethod
    def _provincia_expression() -> pl.Expr:
        # The upstream ETL parsed the sigla "NA" (Napoli) as a missing value,
        # so null/NaN Provincia means Napoli: restore it as "NA".
        sigla = pl.col("Provincia").cast(pl.String).str.strip_chars()
        return (
            pl.when(sigla.str.to_lowercase().is_in(["", "nan", "none", "null"]))
            .then(pl.lit("NA"))
            .otherwise(sigla)
            .fill_null("NA")
            .str.to_uppercase()
            .alias("provincia")
        )

    @staticmethod
    def _tipo_impianto_expression() -> pl.Expr:
        tipo = (
            pl.col("Tipo Impianto").cast(pl.String).str.strip_chars().str.to_titlecase()
        )
        return (
            pl.when(tipo.is_in(list(config.TIPO_MAIN)))
            .then(tipo)
            .otherwise(pl.lit(config.TIPO_ALTRO))
            .alias("tipo_impianto")
        )

    @staticmethod
    def _to_frame(
        collection: Collection, pipeline: list[dict[str, Any]]
    ) -> pl.DataFrame:
        docs = list(collection.aggregate(pipeline))
        if not docs:
            msg = f"MongoDB query on {collection.name} returned no documents"
            raise RuntimeError(msg)
        return pl.DataFrame(docs)


class PriceCleaner:
    """One-pass outlier filter: drop |prezzo - mean| > 4 sd per (date, fuel)."""

    def clean(self, prices: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Return (clean frame, audit frame of removed outliers)."""
        cell_stats = prices.group_by("date", "fuel").agg(
            n=pl.len(),
            mean=pl.col("prezzo").mean(),
            sd=pl.col("prezzo").std(ddof=1),
        )
        flagged = prices.join(cell_stats, on=["date", "fuel"], how="left").with_columns(
            is_outlier=self._outlier_flag()
        )
        clean = flagged.filter(~pl.col("is_outlier")).drop(
            "n", "mean", "sd", "is_outlier"
        )
        audit = (
            flagged.filter(pl.col("is_outlier"))
            .group_by("date", "fuel")
            .agg(
                n_total=pl.col("n").first(),
                cell_mean=pl.col("mean").first(),
                cell_sd=pl.col("sd").first(),
                n_removed=pl.len(),
            )
            .with_columns(
                share_removed_pct=pl.col("n_removed") / pl.col("n_total") * 100
            )
            .sort("date", "fuel")
        )
        return clean, audit

    @staticmethod
    def _outlier_flag() -> pl.Expr:
        # cells with < MIN_CELL_SIZE observations have null ddof=1 std: keep all
        deviation = (pl.col("prezzo") - pl.col("mean")).abs()
        return (
            (pl.col("n") >= config.MIN_CELL_SIZE)
            & (deviation > config.SD_CUTOFF * pl.col("sd"))
        ).fill_null(False)
