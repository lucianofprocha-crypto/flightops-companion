"""
Cliente para dados históricos de METAR via Iowa Environmental Mesonet (IEM).

Fonte pública, gratuita, sem necessidade de API key:
https://mesonet.agron.iastate.edu/request/download.phtml

Cobre estações ASOS/AWOS/METAR de diversos países, incluindo aeroportos
brasileiros (ex: SBGR, SBKP, SBSP, SBSJ).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

IEM_BASE_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

# Colunas relevantes solicitadas ao IEM. "all" também funciona, mas listar
# explicitamente deixa a resposta menor e mais previsível.
IEM_FIELDS = [
    "tmpf",   # temperatura (F)
    "dwpf",   # ponto de orvalho (F)
    "drct",   # direção do vento (graus)
    "sknt",   # velocidade do vento (kt)
    "gust",   # rajada (kt)
    "vsby",   # visibilidade (statute miles)
    "skyc1", "skyl1",
    "skyc2", "skyl2",
    "skyc3", "skyl3",
    "skyc4", "skyl4",
    "wxcodes",
    "metar",
]

PERIOD_TO_DAYS = {
    "30d": 30,
    "365d": 365,
    "5y": 365 * 5,
}


class MetarFetchError(RuntimeError):
    pass


class NoHistoricalDataError(MetarFetchError):
    """Levantado quando a fonte responde normalmente, mas não há nenhuma
    observação para o ICAO/período pedidos (ex: aeroporto sem estação
    automatizada reportando ao IEM Mesonet)."""

    pass


@dataclass
class MetarObservation:
    station: str
    valid: datetime
    tmpf: float | None
    dwpf: float | None
    drct: float | None
    sknt: float | None
    gust: float | None
    vsby: float | None
    sky_layers: list[tuple[str, float | None]]  # [(cobertura, altura_ft), ...]
    wxcodes: str
    raw_metar: str

    @property
    def tmp_c(self) -> float | None:
        return (self.tmpf - 32) * 5.0 / 9.0 if self.tmpf is not None else None

    @property
    def vis_m(self) -> float | None:
        """Visibilidade em metros (a fonte fornece em statute miles)."""
        return self.vsby * 1609.344 if self.vsby is not None else None

    @property
    def ceiling_ft(self) -> float | None:
        """Menor altura entre camadas BKN/OVC (define o teto)."""
        heights = [
            h for cov, h in self.sky_layers
            if cov in ("BKN", "OVC") and h is not None
        ]
        return min(heights) if heights else None

    @property
    def flight_category(self) -> str:
        """Classificação padrão de aviação: VFR / MVFR / IFR / LIFR."""
        ceiling = self.ceiling_ft
        vis = self.vsby

        if vis is None and ceiling is None:
            return "UNKNOWN"

        vis = vis if vis is not None else 99
        ceiling = ceiling if ceiling is not None else 99999

        if ceiling < 500 or vis < 1:
            return "LIFR"
        if ceiling < 1000 or vis < 3:
            return "IFR"
        if ceiling < 3000 or vis < 5:
            return "MVFR"
        return "VFR"


def _parse_float(value: str) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value in ("", "M", "T"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_row(row: dict) -> MetarObservation | None:
    try:
        valid = datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone.utc
        )
    except (KeyError, ValueError):
        return None

    sky_layers = []
    for i in (1, 2, 3, 4):
        cov = (row.get(f"skyc{i}") or "").strip()
        height = _parse_float(row.get(f"skyl{i}", ""))
        if cov and cov != "M":
            sky_layers.append((cov, height))

    return MetarObservation(
        station=row.get("station", ""),
        valid=valid,
        tmpf=_parse_float(row.get("tmpf", "")),
        dwpf=_parse_float(row.get("dwpf", "")),
        drct=_parse_float(row.get("drct", "")),
        sknt=_parse_float(row.get("sknt", "")),
        gust=_parse_float(row.get("gust", "")),
        vsby=_parse_float(row.get("vsby", "")),
        sky_layers=sky_layers,
        wxcodes=(row.get("wxcodes") or "").strip(),
        raw_metar=(row.get("metar") or "").strip(),
    )


def fetch_historical_metar(
    icao: str, period: str, timeout: int = 30
) -> list[MetarObservation]:
    """Busca observações METAR históricas para um ICAO e período.

    period: uma das chaves de PERIOD_TO_DAYS ("30d", "365d", "5y").
    """
    if period not in PERIOD_TO_DAYS:
        raise ValueError(f"período inválido: {period}")

    days = PERIOD_TO_DAYS[period]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    params = {
        "station": icao.upper(),
        "data": ",".join(IEM_FIELDS),
        "year1": start.year,
        "month1": start.month,
        "day1": start.day,
        "year2": end.year,
        "month2": end.month,
        "day2": end.day,
        "tz": "UTC",
        "format": "onlycomma",
        "latlon": "no",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": "3",
    }

    try:
        resp = requests.get(IEM_BASE_URL, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise MetarFetchError(f"falha ao buscar dados do IEM Mesonet: {exc}") from exc

    text = resp.text.strip()
    if not text or text.startswith("ERROR"):
        raise MetarFetchError(f"resposta inesperada do IEM Mesonet para {icao}")

    reader = csv.DictReader(io.StringIO(text))
    observations = []
    for row in reader:
        obs = _parse_row(row)
        if obs is not None:
            observations.append(obs)

    if not observations:
        raise NoHistoricalDataError(
            f"sem dados históricos disponíveis para {icao} no período solicitado"
        )

    return observations
