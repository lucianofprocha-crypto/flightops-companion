"""
FlightOps Companion - Airport Intelligence
API + servidor do frontend.

Rodar localmente:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Acessar:
    Desktop:  http://localhost:8000
    Celular:  http://<IP-do-computador-na-rede>:8000  (ver README.md)
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .atis_client import fetch_atis
from .briefing_parser import build_summary
from .climatology import compute_climatology
from .metar_client import (
    PERIOD_TO_DAYS,
    MetarFetchError,
    NoHistoricalDataError,
    fetch_historical_metar,
)

# Limite de tamanho pro upload de briefing (o PDF de exemplo tem ~3.7MB).
_MAX_BRIEFING_SIZE_BYTES = 20 * 1024 * 1024  # 20MB

app = FastAPI(title="FlightOps Companion API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Só sugestões para o campo de busca (autocomplete) — o app aceita qualquer
# ICAO válido de 4 letras, não é mais uma lista fechada.
SUGGESTED_AIRPORTS = ["SBJH", "SBKP", "SBGR", "SBSJ", "SBSP", "KJFK", "EGLL", "OMDB"]

# Cache simples em memória: (icao, period) -> (timestamp, resultado)
_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 60 * 60  # 1 hora

# ATIS é dado ao vivo — cache bem mais curto.
_ATIS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_ATIS_CACHE_TTL_SECONDS = 5 * 60  # 5 minutos


@app.get("/api/airports")
def list_airports() -> dict:
    """Sugestões para autocomplete. O campo ICAO aceita qualquer valor."""
    return {"airports": SUGGESTED_AIRPORTS}


@app.get("/api/atis")
def get_atis(icao: str = Query(..., min_length=4, max_length=4)) -> dict:
    icao = icao.upper()

    cached = _ATIS_CACHE.get(icao)
    if cached and (time.time() - cached[0]) < _ATIS_CACHE_TTL_SECONDS:
        reports = cached[1]
    else:
        reports = fetch_atis(icao)
        _ATIS_CACHE[icao] = (time.time(), reports)

    return {"icao": icao, "available": len(reports) > 0, "reports": reports}


@app.get("/api/climatology")
def get_climatology(
    icao: str = Query(..., min_length=4, max_length=4),
    period: str = Query("365d"),
) -> dict:
    icao = icao.upper()
    period = period.lower()

    if period not in PERIOD_TO_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"período inválido. Use um de: {list(PERIOD_TO_DAYS.keys())}",
        )

    cache_key = (icao, period)
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        observations = fetch_historical_metar(icao, period)
        result = compute_climatology(icao, period, observations)
    except NoHistoricalDataError as exc:
        # Fonte respondeu normalmente, mas não há histórico para este ICAO.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MetarFetchError as exc:
        # Falha real de rede/fonte de dados.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _CACHE[cache_key] = (time.time(), result)
    return result


@app.post("/api/briefing/upload")
async def upload_briefing(
    file: UploadFile = File(...),
    plan_text: str | None = Form(None),
) -> dict:
    """Recebe um PDF de flight briefing (ex: ForeFlight) e devolve um
    resumo estruturado: METAR/TAF/SIGMET por aeroporto, os principais
    pontos de atenção entre os NOTAMs (fechamentos de pista/táxi/aeródromo)
    e, se o texto do plano operacional apresentado (despachante) for
    colado em plan_text, a comparação da rota do briefing com a do plano
    apresentado, além da checagem dos itens de coordenação (atendimentos,
    FPL aprovado, slots, PPR)."""
    if file.content_type not in (
        "application/pdf",
        "application/x-pdf",
        "binary/octet-stream",
        "application/octet-stream",
    ) and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    if len(data) > _MAX_BRIEFING_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Arquivo muito grande (máx. 20MB).")

    try:
        summary = build_summary(data, filename=file.filename or "briefing.pdf", plan_text=plan_text)
    except Exception as exc:  # leitura de PDF é best-effort; nunca deve travar o usuário
        raise HTTPException(
            status_code=422, detail=f"Não foi possível ler o PDF: {exc}"
        ) from exc

    return summary


# Serve o frontend estático na raiz (mesma origem -> funciona em desktop e celular)
_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")


@app.middleware("http")
async def no_cache_for_frontend(request: Request, call_next):
    """Evita que o navegador cacheie HTML/CSS/JS do frontend durante o
    desenvolvimento — sem isso, mudanças no front podem não aparecer mesmo
    após um refresh normal."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response
