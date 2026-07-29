"""
Eventos abaixo dos mínimos — parte do Airport Intelligence original
(ver docs/VISAO_E_ROADMAP.md).

"Abaixo dos mínimos" aqui é definido como IFR ou LIFR (teto < 1000ft ou
visibilidade < 3sm) — o mesmo limiar já usado em climatology.py para
"condições adversas". Não é o mínimo operacional real de nenhuma
categoria/procedimento específico (isso varia por aeronave/tripulação) —
é uma referência genérica para identificar padrões históricos.

Um "evento" é uma sequência contínua de observações (METAR/SPECI) nessa
condição. Como só temos observações periódicas (não um sensor contínuo),
a duração é estimada:

  fim do evento = horário da primeira observação seguinte que volta a
  reportar VFR/MVFR, DESDE QUE o intervalo até ela seja razoável
  (<= 6h — senão é mais provável que a estação tenha ficado fora do ar
  do que que o evento realmente tenha durado tanto). Quando isso
  acontece, ou quando o evento ainda está "aberto" no fim dos dados
  buscados, o evento é marcado com "end_uncertain": true.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from .metar_client import MetarObservation

_BELOW_MINIMA = ("IFR", "LIFR")
_MAX_RECOVERY_GAP = timedelta(hours=6)
_CALENDAR_DAY_CREDIT_CAP = timedelta(hours=3)


def _below_minima(obs: MetarObservation) -> bool:
    return obs.flight_category in _BELOW_MINIMA


def _duration_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}"


def _dominant_cause(run: list[MetarObservation]) -> str | None:
    tokens: list[str] = []
    for o in run:
        for tok in (o.wxcodes or "").split():
            # Ignora prefixos de intensidade sozinhos e o "+"/"-"; mantém o
            # código como veio (ex: "-RA", "FG", "BR", "+TSRA").
            tokens.append(tok)
    if not tokens:
        return None
    return Counter(tokens).most_common(1)[0][0]


def _obs_dict(obs: MetarObservation, context: bool = False) -> dict:
    return {
        "valid": obs.valid.isoformat(),
        "raw_metar": obs.raw_metar,
        "flight_category": obs.flight_category,
        "visibility_m": round(obs.vis_m) if obs.vis_m is not None else None,
        "ceiling_ft": obs.ceiling_ft,
        "context": context,  # true = observação de contexto (fora do evento em si)
    }


def compute_events(obs_list: list[MetarObservation]) -> list[dict]:
    """Identifica sequências contínuas de observações abaixo dos mínimos
    (IFR/LIFR) e as resume em eventos com início, fim estimado, duração,
    causa provável (a partir do wxcodes) e as observações para drill-down."""
    obs_sorted = sorted(obs_list, key=lambda o: o.valid)
    events: list[dict] = []

    i = 0
    n = len(obs_sorted)
    while i < n:
        if not _below_minima(obs_sorted[i]):
            i += 1
            continue

        j = i
        while j + 1 < n and _below_minima(obs_sorted[j + 1]):
            j += 1
        run = obs_sorted[i : j + 1]

        start = run[0].valid
        end_uncertain = False
        context_obs: MetarObservation | None = None
        if j + 1 < n:
            candidate = obs_sorted[j + 1]
            gap = candidate.valid - run[-1].valid
            if gap <= _MAX_RECOVERY_GAP:
                end = candidate.valid
                context_obs = candidate
            else:
                end = run[-1].valid
                end_uncertain = True
        else:
            end = run[-1].valid
            end_uncertain = True

        duration_minutes = max(0, round((end - start).total_seconds() / 60))
        vis_values = [o.vis_m for o in run if o.vis_m is not None]
        ceiling_values = [o.ceiling_ft for o in run if o.ceiling_ft is not None]

        observations = [_obs_dict(o) for o in run]
        if context_obs is not None:
            observations.append(_obs_dict(context_obs, context=True))

        events.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "duration_minutes": duration_minutes,
                "duration_label": _duration_label(duration_minutes),
                "end_uncertain": end_uncertain,
                "worst_category": "LIFR" if any(o.flight_category == "LIFR" for o in run) else "IFR",
                "cause": _dominant_cause(run),
                "min_visibility_m": round(min(vis_values)) if vis_values else None,
                "min_ceiling_ft": min(ceiling_values) if ceiling_values else None,
                "observation_count": len(run),
                "observations": observations,
            }
        )
        i = j + 1

    return events


def compute_heatmap(obs_list: list[MetarObservation]) -> dict:
    """Matriz mês (1-12) x hora UTC (0-23) com a % de observações abaixo
    dos mínimos em cada célula — para localizar rapidamente os
    horários/meses mais críticos."""
    cells: dict[tuple[int, int], list[MetarObservation]] = {}
    for o in obs_list:
        key = (o.valid.month, o.valid.hour)
        cells.setdefault(key, []).append(o)

    heatmap: dict[str, dict] = {}
    for month in range(1, 13):
        heatmap[str(month)] = {}
        for hour in range(24):
            items = cells.get((month, hour), [])
            total = len(items)
            below = sum(1 for o in items if _below_minima(o))
            heatmap[str(month)][str(hour)] = {
                "count": total,
                "below_minima_pct": round(100.0 * below / total, 1) if total else 0.0,
            }
    return heatmap


def compute_calendar(obs_list: list[MetarObservation]) -> dict:
    """Status diário (verde/amarelo/vermelho) a partir dos minutos
    estimados abaixo dos mínimos em cada dia (UTC).

    Critério: cada observação abaixo dos mínimos "credita" ao seu dia o
    intervalo até a próxima observação, limitado a 3h (evita inflar o
    total quando há um buraco grande nos dados). Classificação:
      🟢 verde   — nenhuma observação abaixo dos mínimos no dia
      🟡 amarelo — algum tempo abaixo dos mínimos, mas < 60 min e sem LIFR
      🔴 vermelho — >= 60 min abaixo dos mínimos, ou qualquer LIFR no dia
    """
    obs_sorted = sorted(obs_list, key=lambda o: o.valid)
    days: dict[str, dict] = {}

    for i, o in enumerate(obs_sorted):
        date_key = o.valid.date().isoformat()
        day = days.setdefault(
            date_key, {"minutes_below_minima": 0, "had_lifr": False, "observation_count": 0}
        )
        day["observation_count"] += 1
        if not _below_minima(o):
            continue

        if i + 1 < len(obs_sorted):
            gap = obs_sorted[i + 1].valid - o.valid
        else:
            gap = timedelta(hours=1)
        credit = min(gap, _CALENDAR_DAY_CREDIT_CAP)
        day["minutes_below_minima"] += round(credit.total_seconds() / 60)
        if o.flight_category == "LIFR":
            day["had_lifr"] = True

    calendar: dict[str, dict] = {}
    for date_key, day in days.items():
        if day["had_lifr"] or day["minutes_below_minima"] >= 60:
            status = "red"
        elif day["minutes_below_minima"] > 0:
            status = "yellow"
        else:
            status = "green"
        calendar[date_key] = {
            "status": status,
            "minutes_below_minima": day["minutes_below_minima"],
            "observation_count": day["observation_count"],
        }

    return calendar


def build_events_summary(icao: str, period: str, obs_list: list[MetarObservation]) -> dict:
    if not obs_list:
        raise ValueError("lista de observações vazia")

    events = compute_events(obs_list)
    heatmap = compute_heatmap(obs_list)
    calendar = compute_calendar(obs_list)

    total = len(obs_list)
    below_count = sum(1 for o in obs_list if _below_minima(o))
    availability_pct = round(100.0 * (total - below_count) / total, 1) if total else 0.0

    total_minutes_events = sum(e["duration_minutes"] for e in events)
    longest = max(events, key=lambda e: e["duration_minutes"], default=None)

    vis_values = [o.vis_m for o in obs_list if o.vis_m is not None]
    ceiling_values = [o.ceiling_ft for o in obs_list if o.ceiling_ft is not None]

    dates = [o.valid for o in obs_list]

    return {
        "icao": icao.upper(),
        "period": period,
        "sample": {
            "observations": total,
            "start": min(dates).isoformat(),
            "end": max(dates).isoformat(),
        },
        "headline": {
            "availability_pct": availability_pct,
            "hours_below_minima": round(total_minutes_events / 60, 1),
            "event_count": len(events),
            "longest_event_minutes": longest["duration_minutes"] if longest else 0,
            "longest_event_label": longest["duration_label"] if longest else "—",
            "min_visibility_m": round(min(vis_values)) if vis_values else None,
            "min_ceiling_ft": min(ceiling_values) if ceiling_values else None,
        },
        "heatmap": heatmap,
        "calendar": calendar,
        "events": events,
    }
