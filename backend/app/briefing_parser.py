"""
Leitura e resumo de PDFs de flight briefing (padrão ForeFlight / DECEA).

Extrai do PDF de despacho:
  - METAR/TAF/SIGMET-AIRMET por aeroporto (partida, destino, adequados).
  - NOTAMs individuais, classificados por categoria e com detecção de
    vigência atual, deduplicados quando repetitivos (ex: várias NOTAM de
    drone/UAS quase idênticas emitidas contra vários ICAOs próximos).

Este é um parser "best effort" para o formato específico observado em
briefings do ForeFlight (layout em 2 colunas nas páginas de NOTAM, seção
"METARs / TAFs" de uma coluna só). Não é uma leitura NOTAM certificada —
serve para destacar rapidamente os pontos de atenção; o texto original de
cada NOTAM/METAR/TAF é sempre preservado para conferência.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO

import pdfplumber

# ---------------------------------------------------------------------------
# Extração de texto (com correção de layout em 2 colunas)
# ---------------------------------------------------------------------------


def _column_text(page) -> str:
    """Extrai o texto de uma página respeitando um possível layout em duas
    colunas (comum nas páginas de NOTAM do ForeFlight). Extrair a página
    inteira de uma vez intercala as colunas na ordem errada; recortar em
    metade esquerda/direita e concatenar resolve isso. Para páginas de
    coluna única, a metade direita fica vazia e não afeta o resultado."""
    mid = page.width / 2
    left = page.crop((0, 0, mid, page.height)).extract_text(layout=False) or ""
    right = page.crop((mid, 0, page.width, page.height)).extract_text(layout=False) or ""
    return (left + "\n" + right).strip()


def _plain_text(page) -> str:
    return page.extract_text(layout=False) or ""


# ---------------------------------------------------------------------------
# METAR / TAF / SIGMET
# ---------------------------------------------------------------------------

_STATION_HEADER_RE = re.compile(
    r"^(?P<role>Departure|Destination|Adequate)[^:]*:?\s*(?P<icao>[A-Z]{4})-(?P<name>.+)$"
)
_TIME_RE = re.compile(r"\((\d{3,4}Z?)\)")

# Grupo de visibilidade em METAR ICAO (metros): exatamente 4 dígitos, seguido
# no máximo por até 3 letras (ex: "9999", "6000", "0800NDV"). O uso de
# fullmatch evita confundir com vento ("21003KT"), horário ("272030Z") ou
# QNH ("Q1013"), que têm comprimento/posição de letras diferentes.
_VIS_TOKEN_RE = re.compile(r"^(\d{4})[A-Z]{0,3}$")
_CLOUD_LAYER_RE = re.compile(r"\b(FEW|SCT|BKN|OVC)(\d{3})\b")
_VV_RE = re.compile(r"\bVV(\d{3})\b")


def classify_weather(metar_raw: str | None) -> str | None:
    """Classifica um METAR bruto em VFR / SVFR / IFR a partir de
    visibilidade e teto (camadas BKN/OVC ou visibilidade vertical).

    Limiares usados (convenção operacional brasileira/ICAO):
      - VFR:  visibilidade >= 5000m e teto >= 1500ft (ou sem teto definido)
      - SVFR: visibilidade >= 3000m e teto >= 500ft (faixa de VFR especial)
      - IFR:  abaixo disso

    CAVOK sempre classifica como VFR. Retorna None se não houver dados
    suficientes no METAR para classificar."""
    if not metar_raw:
        return None

    text = metar_raw.upper()
    if "CAVOK" in text:
        return "VFR"

    vis_m: int | None = None
    for tok in text.split():
        m = _VIS_TOKEN_RE.match(tok)
        if m:
            vis_m = int(m.group(1))
            break
    if vis_m is None:
        sm_m = re.search(r"(\d+)\s*SM\b", text)
        if sm_m:
            vis_m = int(sm_m.group(1)) * 1609

    heights = [int(h) * 100 for cov, h in _CLOUD_LAYER_RE.findall(text) if cov in ("BKN", "OVC")]
    vv_m = _VV_RE.search(text)
    if vv_m:
        heights.append(int(vv_m.group(1)) * 100)
    ceiling_ft = min(heights) if heights else None

    if vis_m is None and ceiling_ft is None:
        return None

    vis = vis_m if vis_m is not None else 9999
    ceiling = ceiling_ft if ceiling_ft is not None else 99999

    if vis >= 5000 and ceiling >= 1500:
        return "VFR"
    if vis >= 3000 and ceiling >= 500:
        return "SVFR"
    return "IFR"


@dataclass
class WeatherStation:
    icao: str
    name: str
    role: str  # "Partida", "Destino" ou "Alternado"
    observed_at: str | None
    metar: str | None
    taf: str | None
    category: str | None = None  # VFR / SVFR / IFR, a partir do METAR


def _find_weather_page(pdf) -> object | None:
    for page in pdf.pages:
        text = _plain_text(page)
        first_line = text.split("\n", 1)[0] if text else ""
        if "METARs" in first_line and "TAFs" in first_line:
            return page
    return None


def parse_weather(pdf) -> dict:
    page = _find_weather_page(pdf)
    if page is None:
        return {"available": False, "stations": [], "sigmet_airmet": None}

    text = _plain_text(page)
    lines = [l for l in text.split("\n") if l.strip()]

    stations: list[WeatherStation] = []
    current: WeatherStation | None = None
    taf_lines: list[str] = []
    sigmet_lines: list[str] = []
    in_sigmet = False

    role_pt = {"Departure": "Partida", "Destination": "Destino", "Adequate": "Alternado"}

    def flush_taf():
        if current is not None and taf_lines:
            current.taf = " ".join(taf_lines).strip()
        taf_lines.clear()

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("SIGMETs") or stripped.startswith("SIGMET"):
            flush_taf()
            in_sigmet = True
            continue

        if in_sigmet:
            if stripped.startswith("WX:") or stripped.lower().startswith("page"):
                continue
            sigmet_lines.append(stripped)
            continue

        header = _STATION_HEADER_RE.match(stripped)
        if header:
            flush_taf()
            role_word = header.group("role")
            time_m = _TIME_RE.search(stripped)
            current = WeatherStation(
                icao=header.group("icao"),
                name=header.group("name").strip(),
                role=role_pt.get(role_word, role_word),
                observed_at=time_m.group(1) if time_m else None,
                metar=None,
                taf=None,
            )
            stations.append(current)
            continue

        if stripped.startswith("METAR"):
            flush_taf()
            if current is not None:
                raw = stripped.split("METAR")[-1].strip(" ●").strip()
                current.metar = raw
            continue

        if stripped.startswith("TAF"):
            flush_taf()
            raw = stripped.split("TAF")[-1].strip(" ●").strip()
            if raw:
                taf_lines.append(raw)
            continue

        if stripped.startswith("●"):
            taf_lines.append(stripped.lstrip("●").strip())
            continue

        if stripped.lower().startswith("no relevant") or stripped.lower().startswith("page"):
            continue

    flush_taf()

    for s in stations:
        s.category = classify_weather(s.metar)

    sigmet_text = " ".join(sigmet_lines).strip() or None

    return {
        "available": True,
        "stations": [s.__dict__ for s in stations],
        "sigmet_airmet": sigmet_text,
    }


# ---------------------------------------------------------------------------
# NOTAMs
# ---------------------------------------------------------------------------

_FOOTER_RE = re.compile(r"NOTAMs\s+\d+\s+of\s+\d+", re.IGNORECASE)
_NOISE_LINE_RE = re.compile(
    r"^(NOTAMs\b|Filtered|No relevant Notams found)", re.IGNORECASE
)
_ROUTE_HEADER_RE = re.compile(r"Created[A-Za-z]{3}\d")
_SECTION_RE = re.compile(r"^(Departure|Destination|Adequate)\b|^FIR\s+[A-Z]{4}$")
_ID_LINE_RE = re.compile(
    r"^([A-Z]\d{3,5}/\d{2})\s+NOTAM([NRC])(?:\s+([A-Z]\d{3,5}/\d{2}))?\s*$"
)


def _is_notam_page(page) -> bool:
    text = _plain_text(page)
    if _FOOTER_RE.search(text):
        return True
    return bool(_ID_LINE_RE.search(text)) and "NOTAM" in text.upper()


def _parse_notam_datetime(raw: str | None) -> tuple[datetime | None, str | None]:
    """Retorna (datetime ou None, nota) a partir de um campo B)/C) no formato
    YYMMDDHHMM, ou 'PERM'/'PERM' + sufixo 'EST'/'UFN'."""
    if not raw:
        return None, None
    raw = raw.strip()
    note = None
    m = re.match(r"^(\d{10})(EST|UFN)?$", raw)
    if not m:
        if raw.upper() in ("PERM", "PERMANENT"):
            return None, "PERM"
        return None, raw
    digits, suffix = m.group(1), m.group(2)
    try:
        dt = datetime.strptime(digits, "%y%m%d%H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None, raw
    if suffix:
        note = suffix
    return dt, note


_CATEGORY_RULES: list[tuple[re.Pattern, str, int]] = [
    # (padrão no título, categoria em pt-BR, peso de severidade 1-3)
    (re.compile(r"RUNWAY", re.I), "Pista", 3),
    (re.compile(r"TAXIWAY", re.I), "Táxi", 2),
    (re.compile(r"OBSTACLE|OBST\b", re.I), "Obstáculo", 2),
    (re.compile(r"AERODROME", re.I), "Aeródromo", 2),
    (re.compile(r"INSTRUMENT APPROACH|STANDARD INSTRUMENT|\bSID\b|\bSTAR\b", re.I), "Procedimentos IFR", 3),
    (re.compile(r"UNMANNED AIRCRAFT|\bDRONE\b|\bUAS\b", re.I), "Drone/UAS", 2),
    (re.compile(r"DANGER AREA|RESTRICTED AREA|PROHIBITED AREA", re.I), "Espaço aéreo restrito", 3),
    (re.compile(r"ENTRY REQUIREMENTS", re.I), "Requisitos de entrada", 2),
    (re.compile(r"BALLOON", re.I), "Balão", 1),
    (re.compile(r"FIREFIGHTING|RESCUE|RFFS", re.I), "Resgate/Combate a incêndio", 2),
    (re.compile(r"HELIPORT", re.I), "Heliporto", 1),
    (re.compile(r"AIRCRAFT STANDS|APRON", re.I), "Pátio/Stands", 1),
    (
        re.compile(
            r"NAVAID|GNSS|RAIM|GPS|\bVOR\b|\bDME\b|\bNDB\b|\bILS\b|GLIDE PATH|MARKER|"
            r"RADIO BEACON|LOCALIZER|APPROACH LIGHTING|DISTANCE MEASURING EQUIPMENT",
            re.I,
        ),
        "Navegação/GNSS",
        2,
    ),
    (re.compile(r"COMM|FREQUENC|DATA LINK", re.I), "Comunicações", 1),
    (re.compile(r"CONTROL AREA|AIRSPACE|OVERFLYING OF PROHIBITED|OVERFLYING OF TRIGGER", re.I), "Espaço aéreo restrito", 2),
    (re.compile(r"DECLARED DISTANCES|STRIP/SHOULDER", re.I), "Pista", 2),
    (re.compile(r"FUEL", re.I), "Combustível", 2),
    (re.compile(r"PARACHUTE|PARAGLIDING|HANG GLIDING|GLIDER", re.I), "Atividade aérea", 2),
    (
        re.compile(r"MISSILE|GUN OR ROCKET|ROCKET FIRING|EXERCISE|RADIOACTIVE|TOXIC CHEMICAL", re.I),
        "Exercício militar/perigo",
        3,
    ),
]


def _classify(title: str) -> tuple[str, int]:
    for pattern, category, weight in _CATEGORY_RULES:
        if pattern.search(title):
            return category, weight
    return "Outros", 1


# Filtro de foco: por pedido, o resumo de NOTAM só destaca fechamentos de
# pista, táxi e aeródromo/aeroporto — as demais categorias continuam sendo
# classificadas internamente (útil se o filtro for relaxado no futuro), mas
# não entram no resumo final.
_CLOSURE_RE = re.compile(r"\b(RUNWAY|TAXIWAY|AERODROME|AIRPORT)\b[^\n]*\bCLOSED\b", re.I)


def _closure_category(title: str) -> str:
    t = title.upper()
    if "RUNWAY" in t:
        return "Pista fechada"
    if "TAXIWAY" in t:
        return "Táxi fechado"
    return "Aeródromo fechado"


def _is_closure(title: str) -> bool:
    return bool(_CLOSURE_RE.search(title))


@dataclass
class NotamRecord:
    id: str
    type: str
    replaces: str | None
    title: str
    section: str | None
    icao: str | None
    valid_from: str | None
    valid_from_note: str | None
    valid_to: str | None
    valid_to_note: str | None
    schedule: str | None
    q_raw: str | None
    text: str
    category: str
    severity: int
    active_now: bool
    new_today: bool


def parse_notams(pdf, now: datetime | None = None) -> list[NotamRecord]:
    now = now or datetime.now(timezone.utc)

    notam_pages = [p for p in pdf.pages if _is_notam_page(p)]
    if not notam_pages:
        return []

    raw_lines: list[str] = []
    for page in notam_pages:
        raw_lines.extend(_column_text(page).split("\n"))

    # Remove ruído de cabeçalho/rodapé, preservando marcadores de seção.
    flat: list[tuple[str, str | None]] = []
    current_section: str | None = None
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _NOISE_LINE_RE.match(stripped) or _ROUTE_HEADER_RE.search(stripped):
            continue
        if _SECTION_RE.match(stripped):
            current_section = stripped
            continue
        flat.append((line, current_section))

    # Localiza as âncoras (linhas de ID de NOTAM).
    anchors = [i for i, (text, _) in enumerate(flat) if _ID_LINE_RE.match(text.strip())]

    records: list[NotamRecord] = []
    for pos, idx in enumerate(anchors):
        id_line, section = flat[idx]
        m = _ID_LINE_RE.match(id_line.strip())
        notam_id, notam_type, replaces = m.group(1), m.group(2), m.group(3)

        title = flat[idx - 1][0].strip() if idx - 1 >= 0 else ""
        new_today = "(NEW TODAY)" in title.upper()
        title_clean = re.sub(r"\(NEW TODAY\)", "", title, flags=re.I).strip()

        next_idx = anchors[pos + 1] if pos + 1 < len(anchors) else len(flat)
        body_end = next_idx - 1 if next_idx < len(flat) else next_idx
        body_end = max(body_end, idx + 1)
        body = "\n".join(text for text, _ in flat[idx + 1 : body_end])

        icao_m = re.search(r"\bA\)\s*(\S+)", body)
        b_m = re.search(r"\bB\)\s*(\S+)", body)
        c_m = re.search(r"\bC\)\s*(\S+)", body)
        d_m = re.search(r"\bD\)\s*(.*?)(?=\n[A-Z]\)|$)", body, re.S)
        q_m = re.search(r"\bQ\)\s*(.+)", body)
        e_m = re.search(r"\bE\)\s*(.*?)(?=\n[FG]\)|\Z)", body, re.S)

        valid_from, from_note = _parse_notam_datetime(b_m.group(1) if b_m else None)
        valid_to, to_note = _parse_notam_datetime(c_m.group(1) if c_m else None)

        active = False
        if valid_from and valid_from <= now:
            if valid_to is None or valid_to >= now:
                active = True
        elif from_note == "PERM" or (valid_from is None and b_m is None and c_m and c_m.group(1).upper() == "PERM"):
            active = True

        category, severity = _classify(title_clean)
        if new_today:
            severity += 1

        records.append(
            NotamRecord(
                id=notam_id,
                type=notam_type,
                replaces=replaces,
                title=title_clean,
                section=section,
                icao=icao_m.group(1) if icao_m else None,
                valid_from=valid_from.isoformat() if valid_from else None,
                valid_from_note=from_note if not valid_from else None,
                valid_to=valid_to.isoformat() if valid_to else None,
                valid_to_note=to_note if not valid_to else None,
                schedule=d_m.group(1).strip() if d_m and d_m.group(1).strip() else None,
                q_raw=q_m.group(1).strip() if q_m else None,
                text=(e_m.group(1).strip() if e_m else body.strip()),
                category=category,
                severity=severity,
                active_now=active,
                new_today=new_today,
            )
        )

    return records


def _dedupe_notams(records: list[NotamRecord]) -> list[dict]:
    """Agrupa NOTAMs quase idênticos (tipicamente drone/UAS repetidas contra
    vários ICAOs vizinhos) para não poluir o resumo com dezenas de entradas
    praticamente iguais."""
    groups: dict[str, dict] = {}
    order: list[str] = []

    for r in records:
        key = f"{r.category}|{r.title}|{r.text[:80]}"
        if key not in groups:
            groups[key] = {
                "title": r.title,
                "category": r.category,
                "severity": r.severity,
                "active_now": r.active_now,
                "new_today": r.new_today,
                "text": r.text,
                "ids": [],
                "icaos": [],
                "section": r.section,
            }
            order.append(key)
        g = groups[key]
        g["ids"].append(r.id)
        if r.icao and r.icao not in g["icaos"]:
            g["icaos"].append(r.icao)
        g["severity"] = max(g["severity"], r.severity)
        g["active_now"] = g["active_now"] or r.active_now
        g["new_today"] = g["new_today"] or r.new_today

    deduped = []
    for key in order:
        g = groups[key]
        g["count"] = len(g["ids"])
        deduped.append(g)
    return deduped


# ---------------------------------------------------------------------------
# Resumo consolidado
# ---------------------------------------------------------------------------


def build_summary(pdf_bytes: bytes, filename: str = "briefing.pdf") -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        weather = parse_weather(pdf)
        notam_records = parse_notams(pdf)

    # Só interessam fechamentos de pista, táxi e aeródromo/aeroporto.
    closures = [r for r in notam_records if _is_closure(r.title)]
    for r in closures:
        r.category = _closure_category(r.title)
        r.severity = 3

    deduped = _dedupe_notams(closures)
    deduped.sort(key=lambda g: (-g["severity"], -g["active_now"], -g["count"]))

    by_category: dict[str, int] = {}
    for r in closures:
        by_category[r.category] = by_category.get(r.category, 0) + 1

    return {
        "filename": filename,
        "pages_read": True,
        "weather": weather,
        "notams": {
            "total": len(closures),
            "active_now": sum(1 for r in closures if r.active_now),
            "new_today": sum(1 for r in closures if r.new_today),
            "by_category": by_category,
            "top_attention": deduped,
            "filter_note": "Somente fechamentos de pista, táxi e aeródromo/aeroporto.",
        },
    }
