"""
Motor de climatologia aeroportuária.

Não é uma previsão numérica de modelo (NWP) — é uma projeção estatística
("o que normalmente acontece neste aeroporto, nesta época/horário, com base
no histórico observado"). Útil para planejamento e para identificar padrões
recorrentes de condições adversas.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from .metar_client import MetarObservation

FLIGHT_CATEGORIES = ["VFR", "MVFR", "IFR", "LIFR", "UNKNOWN"]

COMPASS_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _compass(direction: float | None) -> str | None:
    if direction is None:
        return None
    idx = int((direction / 22.5) + 0.5) % 16
    return COMPASS_16[idx]


def _round1(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _round_m(value: float | None) -> float | None:
    """Arredonda visibilidade em metros para a centena mais próxima
    (a precisão original em statute miles não sustenta mais que isso)."""
    return round(value / 100) * 100 if value is not None else None


def _pct(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def _category_breakdown(obs_list: list[MetarObservation]) -> dict:
    total = len(obs_list)
    counts = Counter(o.flight_category for o in obs_list)
    return {
        cat: {"count": counts.get(cat, 0), "pct": _pct(counts.get(cat, 0), total)}
        for cat in FLIGHT_CATEGORIES
    }


def _adverse_pct(obs_list: list[MetarObservation]) -> float:
    """% de observações em IFR, LIFR (condições que exigem procedimento IFR)."""
    total = len(obs_list)
    adverse = sum(1 for o in obs_list if o.flight_category in ("IFR", "LIFR"))
    return _pct(adverse, total)


def compute_climatology(icao: str, period: str, obs_list: list[MetarObservation]) -> dict:
    if not obs_list:
        raise ValueError("lista de observações vazia")

    temps = [o.tmp_c for o in obs_list if o.tmp_c is not None]
    winds = [o.sknt for o in obs_list if o.sknt is not None]
    gusts = [o.gust for o in obs_list if o.gust is not None]
    vis = [o.vis_m for o in obs_list if o.vis_m is not None]
    directions = [d for o in obs_list if (d := _compass(o.drct)) is not None]

    dates = [o.valid for o in obs_list]

    # A observação mais recente do próprio histórico já buscado é, na
    # prática, o METAR atual (o período sempre vai até "agora") — não
    # precisa de uma segunda chamada a uma fonte de dados ao vivo.
    latest = max(obs_list, key=lambda o: o.valid)

    # Agregação por hora UTC (0-23)
    by_hour: dict[int, list[MetarObservation]] = defaultdict(list)
    for o in obs_list:
        by_hour[o.valid.hour].append(o)

    # Agregação por mês (1-12), útil para sazonalidade
    by_month: dict[int, list[MetarObservation]] = defaultdict(list)
    for o in obs_list:
        by_month[o.valid.month].append(o)

    return {
        "icao": icao.upper(),
        "period": period,
        "current": {
            "raw_metar": latest.raw_metar,
            "valid": latest.valid.isoformat(),
            "flight_category": latest.flight_category,
        },
        "sample": {
            "observations": len(obs_list),
            "start": min(dates).isoformat(),
            "end": max(dates).isoformat(),
        },
        "temperature_c": {
            "mean": _round1(statistics.mean(temps)) if temps else None,
            "min": _round1(min(temps)) if temps else None,
            "max": _round1(max(temps)) if temps else None,
            "stdev": _round1(statistics.pstdev(temps)) if len(temps) > 1 else None,
        },
        "wind_kt": {
            "mean_speed": _round1(statistics.mean(winds)) if winds else None,
            "max_gust": _round1(max(gusts)) if gusts else None,
            "dominant_direction": Counter(directions).most_common(1)[0][0]
            if directions
            else None,
            "direction_histogram": dict(Counter(directions)),
        },
        "visibility_m": {
            "mean": _round_m(statistics.mean(vis)) if vis else None,
            "min": _round_m(min(vis)) if vis else None,
        },
        "flight_category": _category_breakdown(obs_list),
        "adverse_conditions_pct": _adverse_pct(obs_list),
        "by_hour_utc": {
            str(hour): {
                "count": len(items),
                "adverse_pct": _adverse_pct(items),
                "mean_temp_c": _round1(
                    statistics.mean([o.tmp_c for o in items if o.tmp_c is not None])
                )
                if any(o.tmp_c is not None for o in items)
                else None,
            }
            for hour, items in sorted(by_hour.items())
        },
        "by_month": {
            str(month): {
                "count": len(items),
                "adverse_pct": _adverse_pct(items),
                "mean_temp_c": _round1(
                    statistics.mean([o.tmp_c for o in items if o.tmp_c is not None])
                )
                if any(o.tmp_c is not None for o in items)
                else None,
            }
            for month, items in sorted(by_month.items())
        },
    }
