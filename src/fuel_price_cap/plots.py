"""Plotly chart builders: daily mean price lines with ±1 sd bands.

Each national chart shows the aggregate line (all stations) plus one line/band
per market group; a vertical line marks the cap date and a horizontal line the
cap threshold (gross charts only). Regional charts are facet grids of the
aggregate mean ± 1 sd per region.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import polars as pl

from fuel_price_cap import config

_AGG_COLOR = "#0B6E4F"


def _rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _value_prefix(value_col: str) -> str:
    return "mean_net_price" if value_col == "net_price" else "mean_price"


def _value_label(value_col: str) -> str:
    return (
        "net price (EUR/l, net of VAT and excise)"
        if value_col == "net_price"
        else ("gross price (EUR/l)")
    )


class PriceChartBuilder:
    """Builds and exports PNG (kaleido) + HTML price charts."""

    GROUP_COLORS: dict[str, str] = {
        config.GROUP_MAJORS: "#D62728",
        config.GROUP_LARGE: "#1F77B4",
        config.GROUP_WHITE: "#7F7F7F",
    }

    # compliance-share chart: the six grouped brands, then Pompe Bianche
    # (all independents pooled) in gray
    BRAND_LINE_ORDER: tuple[str, ...] = (
        "Agip Eni",
        "Api-Ip",
        "Q8",
        "Esso",
        "Tamoil",
        "Shell",
        config.GROUP_WHITE,
    )
    BRAND_LINE_COLORS: dict[str, str] = {
        "Agip Eni": "#D62728",
        "Api-Ip": "#FF7F0E",
        "Q8": "#9467BD",
        "Esso": "#1F77B4",
        "Tamoil": "#8C564B",
        "Shell": "#17BECF",
        config.GROUP_WHITE: "#7F7F7F",
    }

    def __init__(self, out_dir: Path) -> None:
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # National charts: aggregate + one line/band per group
    # ------------------------------------------------------------------ #
    def group_price_chart(
        self,
        by_group: pl.DataFrame,
        overall: pl.DataFrame,
        *,
        fuel: str,
        tipo: str,
        value_col: str,
        zoom: bool = False,
    ) -> tuple[Path, Path]:
        """by_group: daily stats for one (fuel, tipo) with a ``group`` column;
        overall: the same without the group dimension (all stations)."""
        if zoom:
            by_group = by_group.filter(pl.col("date") >= config.ZOOM_FROM)
            overall = overall.filter(pl.col("date") >= config.ZOOM_FROM)

        mean_col = f"mean_{value_col}"
        sd_col = f"sd_{value_col}"

        fig = go.Figure()
        self._add_line_with_band(
            fig,
            overall,
            mean_col,
            sd_col,
            name=config.AGGREGATE_LABEL,
            color=_AGG_COLOR,
            dash="dot",
        )
        for group in config.GROUP_ORDER:
            series = by_group.filter(pl.col("group") == group)
            if series.height:
                self._add_line_with_band(
                    fig,
                    series,
                    mean_col,
                    sd_col,
                    name=group,
                    color=self.GROUP_COLORS[group],
                )

        window_label = f" — zoom from {config.ZOOM_FROM.isoformat()}" if zoom else ""
        fig.update_layout(
            title=(
                f"{fuel} · {tipo}: daily mean {value_col.replace('_', ' ')} "
                f"(line) with ±1 sd band{window_label}"
            ),
            yaxis_title=_value_label(value_col),
            template="plotly_white",
            hovermode="x unified",
            width=1250,
            height=520,
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.0},
            margin={"l": 60, "r": 30, "t": 80, "b": 50},
        )
        # pad the x range so the cap line (at the right edge of the window)
        # does not collide with its own annotation text
        last_date = overall["date"].max()
        fig.update_xaxes(
            tickformat="%d %b",
            tickangle=0,
            range=[overall["date"].min(), last_date + datetime.timedelta(days=8)],
        )
        fig.update_yaxes(tickformat=".2f")
        fig.add_vline(
            x=config.CAP_DATE.isoformat(),
            line_dash="dash",
            line_color="black",
            annotation_text=f"cap {config.CAP_DATE.isoformat()}",
            annotation_position="top left",
        )
        if value_col == "prezzo":
            threshold = config.THRESHOLDS[fuel]
            fig.add_hline(
                y=threshold,
                line_dash="dot",
                line_color="firebrick",
                annotation_text=f"threshold {threshold:.1f} EUR/l",
                annotation_position="bottom left",
            )

        stem = f"{_value_prefix(value_col)}_{fuel.lower()}_{tipo.lower()}"
        if zoom:
            stem = f"{stem}_zoom"
        return self._export(fig, stem)

    @staticmethod
    def _add_line_with_band(
        fig: go.Figure,
        frame: pl.DataFrame,
        mean_col: str,
        sd_col: str,
        *,
        name: str,
        color: str,
        dash: str = "solid",
    ) -> None:
        dates = frame["date"].to_list()
        mean = frame[mean_col].to_list()
        sd = frame[sd_col].to_list()
        upper = [m + s for m, s in zip(mean, sd, strict=True)]
        lower = [m - s for m, s in zip(mean, sd, strict=True)]
        fig.add_trace(
            go.Scatter(
                x=dates + dates[::-1],
                y=upper + lower[::-1],
                fill="toself",
                mode="none",
                fillcolor=_rgba(color, 0.12),
                name=f"{name} ±1 sd",
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=mean,
                mode="lines",
                name=name,
                line={"color": color, "width": 3 if dash == "dot" else 2, "dash": dash},
                hovertemplate="%{y:.3f} EUR/l<extra>%{fullData.name}</extra>",
            )
        )

    # ------------------------------------------------------------------ #
    # Compliance-share chart: one line per Bandiera
    # ------------------------------------------------------------------ #
    def compliance_share_chart(
        self, daily: pl.DataFrame, *, fuel: str, zoom: bool = False
    ) -> tuple[Path, Path]:
        """daily: one row per date x plot_bandiera for a single fuel, with
        ``pct_below`` = share of stations priced below the cap threshold."""
        if zoom:
            daily = daily.filter(pl.col("date") >= config.ZOOM_FROM)

        fig = go.Figure()
        for brand in self.BRAND_LINE_ORDER:
            series = daily.filter(pl.col("plot_bandiera") == brand).sort("date")
            if not series.height:
                continue
            fig.add_trace(
                go.Scatter(
                    x=series["date"].to_list(),
                    y=series["pct_below"].to_list(),
                    mode="lines",
                    name=brand,
                    line={"color": self.BRAND_LINE_COLORS[brand], "width": 2},
                    hovertemplate="%{y:.1f}%<extra>%{fullData.name}</extra>",
                )
            )

        window_label = f" — zoom from {config.ZOOM_FROM.isoformat()}" if zoom else ""
        threshold = config.THRESHOLDS[fuel]
        fig.update_layout(
            title=(
                f"{fuel}: daily share of stations priced below the "
                f"{threshold:.1f} EUR/l cap, by Bandiera{window_label}"
            ),
            yaxis_title="% of stations below the cap",
            template="plotly_white",
            hovermode="x unified",
            width=1250,
            height=520,
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.0},
            margin={"l": 60, "r": 30, "t": 80, "b": 50},
        )
        # right padding keeps the cap line clear of its own annotation
        fig.update_xaxes(
            tickformat="%d %b",
            tickangle=0,
            range=[
                daily["date"].min(),
                daily["date"].max() + datetime.timedelta(days=8),
            ],
        )
        fig.update_yaxes(tickformat=".0f", ticksuffix="%")
        fig.add_vline(
            x=config.CAP_DATE.isoformat(),
            line_dash="dash",
            line_color="black",
            annotation_text=f"cap {config.CAP_DATE.isoformat()}",
            annotation_position="top left",
        )
        stem = f"compliance_share_by_bandiera_{fuel.lower()}"
        if zoom:
            stem = f"{stem}_zoom"
        return self._export(fig, stem)

    # ------------------------------------------------------------------ #
    # Regional facet charts: aggregate mean ± 1 sd per region
    # ------------------------------------------------------------------ #
    def regional_price_chart(
        self,
        by_region: pl.DataFrame,
        *,
        fuel: str,
        value_col: str,
    ) -> tuple[Path, Path]:
        """by_region: daily stats for one fuel with a ``regione`` column."""
        mean_col = f"mean_{value_col}"
        sd_col = f"sd_{value_col}"
        fig = px.line(
            by_region,
            x="date",
            y=mean_col,
            error_y=sd_col,
            facet_col="regione",
            facet_col_wrap=5,
            facet_col_spacing=0.03,
            facet_row_spacing=0.06,
            title=(
                f"{fuel}: daily mean {value_col.replace('_', ' ')} by region "
                "(mean ± 1 sd, all groups)"
            ),
            labels={mean_col: _value_label(value_col)},
        )
        fig.for_each_trace(
            lambda trace: trace.update(line_color=_AGG_COLOR, line_width=1.6)
        )
        fig.update_layout(
            template="plotly_white",
            width=1650,
            height=1050,
            margin={"l": 60, "r": 30, "t": 80, "b": 50},
            showlegend=False,
        )
        fig.update_xaxes(tickformat="%d %b", tickangle=0, matches=None)
        fig.update_yaxes(tickformat=".2f", matches=None)
        fig.add_vline(
            x=config.CAP_DATE.isoformat(),
            line_dash="dash",
            line_color="black",
            line_width=1,
        )
        stem = f"{_value_prefix(value_col)}_regions_{fuel.lower()}"
        return self._export(fig, stem)

    # ------------------------------------------------------------------ #
    def _export(self, fig: go.Figure, stem: str) -> tuple[Path, Path]:
        png_path = self._out_dir / f"{stem}.png"
        html_path = self._out_dir / f"{stem}.html"
        fig.write_image(png_path, scale=2)
        fig.write_html(html_path, include_plotlyjs="cdn")
        return png_path, html_path
