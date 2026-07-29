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

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .atis_client import fetch_atis
from .briefing_parser import build_summary
from .climatology import compute_climatology
from .metar_client import (
    PERIOD_TO_DAYS,
    MetarFetchError,
    MetarObservation,
    NoHistoricalDataError,
    fetch_historical_metar,
)
from .minima_events import build_events_summary
from .report_generator import build_report
from .travel_docs_parser import build_docs_summary

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

# Cache das observações brutas (mesma chave) — compartilhado entre
# /api/climatology e /api/events pra não buscar o histórico duas vezes no
# IEM Mesonet quando o usuário consulta os dois pro mesmo ICAO/período.
_OBS_CACHE: dict[tuple[str, str], tuple[float, list[MetarObservation]]] = {}

# ATIS é dado ao vivo — cache bem mais curto.
_ATIS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_ATIS_CACHE_TTL_SECONDS = 5 * 60  # 5 minutos


def _get_observations(icao: str, period: str) -> list[MetarObservation]:
    cache_key = (icao, period)
    cached = _OBS_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    observations = fetch_historical_metar(icao, period)
    _OBS_CACHE[cache_key] = (time.time(), observations)
    return observations


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
        observations = _get_observations(icao, period)
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


@app.get("/api/events")
def get_events(
    icao: str = Query(..., min_length=4, max_length=4),
    period: str = Query("365d"),
) -> dict:
    """Eventos abaixo dos mínimos (IFR/LIFR): heatmap mês x hora,
    calendário diário (verde/amarelo/vermelho) e a lista de eventos com
    início, fim estimado, duração, causa provável e as observações
    (METAR/SPECI) de cada um, para drill-down. Ver docstring de
    minima_events.py para os critérios usados."""
    icao = icao.upper()
    period = period.lower()

    if period not in PERIOD_TO_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"período inválido. Use um de: {list(PERIOD_TO_DAYS.keys())}",
        )

    try:
        observations = _get_observations(icao, period)
        result = build_events_summary(icao, period, observations)
    except NoHistoricalDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MetarFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@app.post("/api/traveldocs/compare")
async def compare_travel_docs(
    gedec: UploadFile | None = File(None),
    eapis: UploadFile | None = File(None),
    egar: UploadFile | None = File(None),
    passenger_list: UploadFile | None = File(None),
) -> dict:
    """Recebe até 4 PDFs (GEDEC, eAPIS, eGAR, lista de passageiros — todos
    opcionais, mas envie ao menos um) e cruza os dados de
    tripulação/passageiros entre eles: nome, nacionalidade, número de
    documento e data de nascimento. Aponta divergências entre documentos e
    quem está ausente em algum deles. O eGAR não tem texto no PDF (é
    gerado via "imprimir em PDF" do navegador) — seus dados vêm de OCR e
    são marcados como tal; confira visualmente o PDF original em caso de
    divergência envolvendo o eGAR. A lista de passageiros costuma ter
    páginas extras com fotos de passaporte escaneadas — só a primeira
    página (com a tabela) é lida."""
    uploads = {"gedec": gedec, "eapis": eapis, "egar": egar, "passenger_list": passenger_list}
    files: dict[str, bytes] = {}
    for key, upload in uploads.items():
        if upload is not None and upload.filename:
            data = await upload.read()
            if data:
                if len(data) > _MAX_BRIEFING_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail=f"Arquivo {key} muito grande (máx. 20MB).")
                files[key] = data

    if not files:
        raise HTTPException(
            status_code=400,
            detail="Envie ao menos um PDF (GEDEC, eAPIS, eGAR ou lista de passageiros).",
        )

    try:
        summary = build_docs_summary(files)
    except Exception as exc:  # leitura de PDF é best-effort; nunca deve travar o usuário
        raise HTTPException(
            status_code=422, detail=f"Não foi possível ler os documentos: {exc}"
        ) from exc

    return summary


@app.post("/api/report/generate")
async def generate_report(payload: dict = Body(...)) -> Response:
    """Gera um PDF de resumo (Fase 1: texto/tabelas, sem mapa e sem
    combustível/tripulação/alternados) a partir dos resultados que o
    frontend já obteve de /api/briefing/upload e/ou /api/traveldocs/compare
    e reenvia aqui em {"briefing": ..., "travel_docs": ...} (cada chave é
    opcional). Nenhum PDF é reprocessado — só formata o que já foi lido."""
    try:
        pdf_bytes = build_report(payload)
    except Exception as exc:  # geração de PDF é best-effort; nunca deve travar o usuário
        raise HTTPException(
            status_code=422, detail=f"Não foi possível gerar o relatório: {exc}"
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="flightops-relatorio.pdf"'},
    )


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
