"""Enrichment: text normalization, brand grouping, region mapping,
time-consistent station attribution (as-of join) and net price calculation."""

from __future__ import annotations

import re
import unicodedata

import polars as pl

from fuel_price_cap import config

# sigla -> (province name, region)
PROVINCE_REGION: dict[str, tuple[str, str]] = {
    "AG": ("Agrigento", "Sicilia"),
    "AL": ("Alessandria", "Piemonte"),
    "AN": ("Ancona", "Marche"),
    "AO": ("Aosta", "Valle d'Aosta"),
    "AP": ("Ascoli Piceno", "Marche"),
    "AQ": ("L'Aquila", "Abruzzo"),
    "AR": ("Arezzo", "Toscana"),
    "AT": ("Asti", "Piemonte"),
    "AV": ("Avellino", "Campania"),
    "BA": ("Bari", "Puglia"),
    "BG": ("Bergamo", "Lombardia"),
    "BI": ("Biella", "Piemonte"),
    "BL": ("Belluno", "Veneto"),
    "BN": ("Benevento", "Campania"),
    "BO": ("Bologna", "Emilia-Romagna"),
    "BR": ("Brindisi", "Puglia"),
    "BS": ("Brescia", "Lombardia"),
    "BT": ("Barletta-Andria-Trani", "Puglia"),
    "BZ": ("Bolzano", "Trentino-Alto Adige/Südtirol"),
    "CA": ("Cagliari", "Sardegna"),
    "CB": ("Campobasso", "Molise"),
    "CE": ("Caserta", "Campania"),
    "CH": ("Chieti", "Abruzzo"),
    "CL": ("Caltanissetta", "Sicilia"),
    "CN": ("Cuneo", "Piemonte"),
    "CO": ("Como", "Lombardia"),
    "CR": ("Cremona", "Lombardia"),
    "CS": ("Cosenza", "Calabria"),
    "CT": ("Catania", "Sicilia"),
    "CZ": ("Catanzaro", "Calabria"),
    "EN": ("Enna", "Sicilia"),
    "FC": ("Forlì-Cesena", "Emilia-Romagna"),
    "FE": ("Ferrara", "Emilia-Romagna"),
    "FG": ("Foggia", "Puglia"),
    "FI": ("Firenze", "Toscana"),
    "FM": ("Fermo", "Marche"),
    "FR": ("Frosinone", "Lazio"),
    "GE": ("Genova", "Liguria"),
    "GO": ("Gorizia", "Friuli-Venezia Giulia"),
    "GR": ("Grosseto", "Toscana"),
    "IM": ("Imperia", "Liguria"),
    "IS": ("Isernia", "Molise"),
    "KR": ("Crotone", "Calabria"),
    "LC": ("Lecco", "Lombardia"),
    "LE": ("Lecce", "Puglia"),
    "LI": ("Livorno", "Toscana"),
    "LO": ("Lodi", "Lombardia"),
    "LT": ("Latina", "Lazio"),
    "LU": ("Lucca", "Toscana"),
    "MB": ("Monza e Brianza", "Lombardia"),
    "MC": ("Macerata", "Marche"),
    "ME": ("Messina", "Sicilia"),
    "MI": ("Milano", "Lombardia"),
    "MN": ("Mantova", "Lombardia"),
    "MO": ("Modena", "Emilia-Romagna"),
    "MS": ("Massa-Carrara", "Toscana"),
    "MT": ("Matera", "Basilicata"),
    "NA": ("Napoli", "Campania"),
    "NO": ("Novara", "Piemonte"),
    "NU": ("Nuoro", "Sardegna"),
    "OR": ("Oristano", "Sardegna"),
    "PA": ("Palermo", "Sicilia"),
    "PC": ("Piacenza", "Emilia-Romagna"),
    "PD": ("Padova", "Veneto"),
    "PE": ("Pescara", "Abruzzo"),
    "PG": ("Perugia", "Umbria"),
    "PI": ("Pisa", "Toscana"),
    "PN": ("Pordenone", "Friuli-Venezia Giulia"),
    "PO": ("Prato", "Toscana"),
    "PR": ("Parma", "Emilia-Romagna"),
    "PT": ("Pistoia", "Toscana"),
    "PU": ("Pesaro e Urbino", "Marche"),
    "PV": ("Pavia", "Lombardia"),
    "PZ": ("Potenza", "Basilicata"),
    "RA": ("Ravenna", "Emilia-Romagna"),
    "RC": ("Reggio Calabria", "Calabria"),
    "RE": ("Reggio Emilia", "Emilia-Romagna"),
    "RG": ("Ragusa", "Sicilia"),
    "RI": ("Rieti", "Lazio"),
    "RM": ("Roma", "Lazio"),
    "RN": ("Rimini", "Emilia-Romagna"),
    "RO": ("Rovigo", "Veneto"),
    "SA": ("Salerno", "Campania"),
    "SI": ("Siena", "Toscana"),
    "SO": ("Sondrio", "Lombardia"),
    "SP": ("La Spezia", "Liguria"),
    "SR": ("Siracusa", "Sicilia"),
    "SS": ("Sassari", "Sardegna"),
    "SU": ("Sud Sardegna", "Sardegna"),
    "SV": ("Savona", "Liguria"),
    "TA": ("Taranto", "Puglia"),
    "TE": ("Teramo", "Abruzzo"),
    "TN": ("Trento", "Trentino-Alto Adige/Südtirol"),
    "TO": ("Torino", "Piemonte"),
    "TP": ("Trapani", "Sicilia"),
    "TR": ("Terni", "Umbria"),
    "TS": ("Trieste", "Friuli-Venezia Giulia"),
    "TV": ("Treviso", "Veneto"),
    "UD": ("Udine", "Friuli-Venezia Giulia"),
    "VA": ("Varese", "Lombardia"),
    "VB": ("Verbano-Cusio-Ossola", "Piemonte"),
    "VC": ("Vercelli", "Piemonte"),
    "VE": ("Venezia", "Veneto"),
    "VI": ("Vicenza", "Veneto"),
    "VR": ("Verona", "Veneto"),
    "VT": ("Viterbo", "Lazio"),
    "VV": ("Vibo Valentia", "Calabria"),
}


def normalize_text(value: str | None) -> str | None:
    """Normalize a label: lowercase, strip accents, punctuation -> spaces,
    collapse whitespace. ``None``/empty stays ``None``."""
    if value is None:
        return None
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = without_accents.lower()
    without_punctuation = re.sub(r"[^\w\s]", " ", lowered)
    collapsed = re.sub(r"\s+", " ", without_punctuation).strip()
    return collapsed or None


def normalized_mapping(frame: pl.DataFrame, column: str) -> pl.DataFrame:
    """Distinct values of ``column`` with their normalized form (Python-side,
    computed once per distinct value rather than per row)."""
    distinct = (
        frame.select(pl.col(column).alias("raw"))
        .unique()
        .filter(pl.col("raw").is_not_null())
    )
    pairs = [
        {"raw": row["raw"], "normalized": normalize_text(row["raw"])}
        for row in distinct.iter_rows(named=True)
    ]
    schema = {"raw": pl.String, "normalized": pl.String}
    return pl.DataFrame(pairs, schema=schema)


class BrandGrouper:
    """Assigns the canonical brand name and the market group (Majors / Large /
    Pompe Bianche) via normalized exact matching on six brand names."""

    def __init__(self) -> None:
        self._mapping = dict(config.BRAND_GROUPS)

    def assign(
        self, frame: pl.DataFrame, bandeira_col: str = "bandiera"
    ) -> pl.DataFrame:
        """Add ``canonical_name`` and ``group`` columns to ``frame``."""
        mapping = normalized_mapping(frame, bandeira_col)
        rows = [
            {
                "raw": row["raw"],
                "canonical_name": self._canonical(row),
                "group": self._group(row),
            }
            for row in mapping.iter_rows(named=True)
        ]
        lookup = pl.DataFrame(
            rows,
            schema={"raw": pl.String, "canonical_name": pl.String, "group": pl.String},
        )
        return (
            frame.join(lookup, left_on=bandeira_col, right_on="raw", how="left")
            .with_columns(
                pl.col("canonical_name").fill_null(config.GROUP_WHITE),
                pl.col("group").fill_null(config.GROUP_WHITE),
            )
            .with_columns(pl.col("group").cast(pl.String).alias("group"))
        )

    def _canonical(self, row: dict[str, str | None]) -> str:
        if row["normalized"] is not None and row["normalized"] in self._mapping:
            return self._mapping[row["normalized"]][0]
        return row["raw"] if row["raw"] is not None else config.GROUP_WHITE

    def _group(self, row: dict[str, str | None]) -> str:
        if row["normalized"] is not None and row["normalized"] in self._mapping:
            return self._mapping[row["normalized"]][1]
        return config.GROUP_WHITE

    def audit(self, stations: pl.DataFrame) -> pl.DataFrame:
        """All distinct raw Bandiera values with normalized form and assigned group."""
        counts = stations.group_by("bandiera").agg(n_obs=pl.len())
        assigned = self.assign(counts, "bandiera")
        mapping = normalized_mapping(counts, "bandiera").select(
            pl.col("raw").alias("bandiera"),
            pl.col("normalized").alias("bandiera_normalized"),
        )
        return (
            assigned.join(mapping, on="bandiera", how="left")
            .select(
                "bandiera",
                "bandiera_normalized",
                "canonical_name",
                "group",
                "n_obs",
            )
            .sort("n_obs", descending=True)
        )

    @staticmethod
    def write_reference_csv(path: str) -> None:
        rows = [
            {
                "bandiera_normalized": normalized,
                "canonical_name": canonical,
                "group": group,
            }
            for normalized, (canonical, group) in config.BRAND_GROUPS.items()
        ]
        pl.DataFrame(rows).write_csv(path)


class RegionMapper:
    """Maps province sigle to regions via a static reference table."""

    def __init__(self) -> None:
        self._table = pl.DataFrame(
            [
                {
                    "provincia_sigla": sigla,
                    "provincia_name": name,
                    "regione": region,
                }
                for sigla, (name, region) in PROVINCE_REGION.items()
            ],
            schema={
                "provincia_sigla": pl.String,
                "provincia_name": pl.String,
                "regione": pl.String,
            },
        )

    def assign(
        self, frame: pl.DataFrame, provincia_col: str = "provincia"
    ) -> pl.DataFrame:
        return frame.join(
            self._table,
            left_on=provincia_col,
            right_on="provincia_sigla",
            how="left",
        )

    @staticmethod
    def write_reference_csv(path: str) -> None:
        pl.DataFrame(
            [
                {
                    "provincia_sigla": sigla,
                    "provincia_name": name,
                    "regione": region,
                }
                for sigla, (name, region) in sorted(PROVINCE_REGION.items())
            ],
            schema={
                "provincia_sigla": pl.String,
                "provincia_name": pl.String,
                "regione": pl.String,
            },
        ).write_csv(path)


class StationTimeline:
    """Time-consistent attribution: joins weekly station snapshots onto daily
    prices with a backward as-of join, so each price carries the attributes
    (Gestore, Bandiera, Tipo Impianto, Provincia) in force that day.

    Prices with no station record at all, or whose station has no Tipo
    Impianto, are dropped from the output (both causes are reported in the
    returned metadata)."""

    _ATTRS = ("gestore", "bandiera", "tipo_impianto", "provincia")

    def attribute(
        self, prices: pl.DataFrame, stations: pl.DataFrame
    ) -> tuple[pl.DataFrame, dict[str, float]]:
        attrs = stations.select("id_impianto", "date", *self._ATTRS).sort("date")
        prices_idx = prices.sort("date").with_row_index("__row")

        backward = prices_idx.join_asof(
            attrs, on="date", by="id_impianto", strategy="backward"
        )
        earliest_attrs = attrs.rename({c: f"{c}__earliest" for c in self._ATTRS}).sort(
            "date"
        )
        forward = (
            prices_idx.select("__row", "id_impianto", "date")
            .join_asof(earliest_attrs, on="date", by="id_impianto", strategy="forward")
            .select("__row", *(f"{c}__earliest" for c in self._ATTRS))
        )

        merged = backward.join(forward, on="__row")
        total = merged.height
        fallback = merged.select(
            (
                pl.col("bandiera").is_null()
                & pl.col("bandiera__earliest").is_not_null()
            ).sum()
        ).item()

        filled = merged.with_columns(
            pl.col(c).fill_null(pl.col(f"{c}__earliest")) for c in self._ATTRS
        ).drop("__row", *(f"{c}__earliest" for c in self._ATTRS))
        no_station = filled.select(
            pl.all_horizontal(pl.col(c).is_null() for c in self._ATTRS).sum()
        ).item()
        missing_tipo = filled.select(
            (
                pl.col("tipo_impianto").is_null()
                & pl.any_horizontal(pl.col(c).is_not_null() for c in self._ATTRS)
            ).sum()
        ).item()
        kept = filled.filter(pl.col("tipo_impianto").is_not_null())

        meta = {
            "total_rows": float(total),
            "fallback_rows": float(fallback),
            "fallback_share_pct": fallback / total * 100 if total else 0.0,
            "no_station_rows": float(no_station),
            "no_station_share_pct": no_station / total * 100 if total else 0.0,
            "missing_tipo_rows": float(missing_tipo),
            "dropped_rows": float(no_station + missing_tipo),
            "dropped_share_pct": (
                (no_station + missing_tipo) / total * 100 if total else 0.0
            ),
        }
        return kept, meta


class NetPriceCalculator:
    """Computes net-of-tax prices: ``net = prezzo / (1 + VAT) - excise(fuel, day)``.

    Excises are stored in EUR per 1000 litres and are rescaled to EUR/litre.
    A full daily calendar over the price range is built so the carry-forward
    (last ``application_date <= day``) is exact.
    """

    def enrich(
        self, prices: pl.DataFrame, tax: pl.DataFrame
    ) -> tuple[pl.DataFrame, dict[str, int]]:
        calendar = (
            pl.date_range(prices["date"].min(), prices["date"].max(), "1d", eager=True)
            .alias("date")
            .to_frame()
            .join_asof(
                tax.select("application_date", "benzina_tax", "gasolio_tax").sort(
                    "application_date"
                ),
                left_on="date",
                right_on="application_date",
                strategy="backward",
            )
        )
        excise_long = (
            calendar.unpivot(
                index="date",
                on=("benzina_tax", "gasolio_tax"),
                variable_name="tax_col",
                value_name="excise_per_1000l",
            )
            .with_columns(
                fuel=pl.when(pl.col("tax_col") == "benzina_tax")
                .then(pl.lit(config.FUELS[0]))
                .otherwise(pl.lit(config.FUELS[1])),
                excise=pl.col("excise_per_1000l") / 1000.0,
            )
            .select("date", "fuel", "excise")
        )
        enriched = prices.join(
            excise_long, on=["date", "fuel"], how="left"
        ).with_columns(
            net_price=(pl.col("prezzo") / (1 + config.VAT_RATE) - pl.col("excise"))
        )
        meta = {
            "null_excise_rows": enriched.filter(pl.col("excise").is_null()).height,
            "null_net_price_rows": enriched.filter(
                pl.col("net_price").is_null()
            ).height,
        }
        return enriched, meta
