"""
Geracao do relatorio de pre-voo em PDF (Fase 1).

Resume em um unico documento os resultados JA CALCULADOS pelo app -
meteorologia (VFR/SVFR/IFR), NOTAMs (fechamentos de pista/taxi/aerodromo),
comparacao de rota (briefing x plano apresentado) + checklist de
coordenacao, e a comparacao de documentos de tripulacao/passageiros
(GEDEC/eAPIS/eGAR/lista de passageiros).

Fase 1 e so texto/tabelas: sem mapa da rota e sem combustivel/tripulacao/
alternados (esses dados vem da capa do PDF de briefing, que ainda nao e
lida pelo app). Isso fica pra uma fase futura.

O payload de entrada e simplesmente o JSON que /api/briefing/upload e/ou
/api/traveldocs/compare ja devolveram - o frontend reenvia aqui o que
tiver em maos, sem reprocessar nenhum PDF.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_INK = colors.HexColor("#1a2333")
_RED = colors.HexColor("#c0392b")
_GREY = colors.HexColor("#666666")
_LINE = colors.HexColor("#cccccc")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(name="H1FO", parent=ss["Heading1"], fontSize=17, textColor=_INK, spaceAfter=2))
    ss.add(
        ParagraphStyle(
            name="H2FO",
            parent=ss["Heading2"],
            fontSize=12.5,
            textColor=_INK,
            spaceBefore=12,
            spaceAfter=5,
            borderColor=_LINE,
        )
    )
    ss.add(ParagraphStyle(name="Body9", parent=ss["Normal"], fontSize=9, leading=12, alignment=TA_LEFT))
    ss.add(ParagraphStyle(name="Small", parent=ss["Normal"], fontSize=7.5, textColor=_GREY, leading=10))
    ss.add(ParagraphStyle(name="Mono", parent=ss["Normal"], fontName="Courier", fontSize=8, leading=10.5))
    return ss


def _esc(value) -> str:
    """Escapa texto pra uso seguro em Paragraph (que interpreta um HTML
    reduzido) - qualquer campo vindo de PDF de terceiros pode conter & < >."""
    if value is None:
        return ""
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bool_icon(value) -> str:
    if value is True:
        return "[OK]"
    if value is False:
        return "[PENDENTE]"
    return "[?]"


# ---------------------------------------------------------------------------
# Secoes do briefing
# ---------------------------------------------------------------------------


def _weather_section(styles, weather: dict | None) -> list:
    flow = [Paragraph("Meteorologia (METAR / TAF / SIGMET)", styles["H2FO"])]
    if not weather or not weather.get("available") or not weather.get("stations"):
        flow.append(Paragraph("Nenhuma secao de METAR/TAF encontrada no briefing.", styles["Body9"]))
        return flow

    for s in weather["stations"]:
        cat = s.get("category") or "-"
        role = _esc(s.get("role"))
        icao = _esc(s.get("icao"))
        name = _esc(s.get("name"))
        header = f"<b>{role}</b> &mdash; {icao} &middot; {name} &mdash; <b>{cat}</b>"
        flow.append(Paragraph(header, styles["Body9"]))
        if s.get("metar"):
            flow.append(Paragraph(f"METAR: {_esc(s['metar'])}", styles["Mono"]))
        if s.get("taf"):
            flow.append(Paragraph(f"TAF: {_esc(s['taf'])}", styles["Mono"]))
        flow.append(Spacer(1, 4))

    if weather.get("sigmet_airmet"):
        flow.append(Paragraph(f"<b>SIGMET/AIRMET:</b> {_esc(weather['sigmet_airmet'])}", styles["Body9"]))

    return flow


def _notam_section(styles, notams: dict | None) -> list:
    flow = [Paragraph("NOTAMs &mdash; fechamentos (pista / taxi / aerodromo)", styles["H2FO"])]
    if not notams or not notams.get("total"):
        flow.append(Paragraph("Nenhum fechamento de pista, taxi ou aerodromo encontrado.", styles["Body9"]))
        return flow

    resumo = f"{notams['total']} fechamento(s) &middot; {notams['active_now']} vigente(s) agora"
    if notams.get("new_today"):
        resumo += f" &middot; {notams['new_today']} novo(s) hoje"
    flow.append(Paragraph(resumo, styles["Body9"]))
    flow.append(Spacer(1, 4))

    for item in notams.get("top_attention", []):
        status = "VIGENTE" if item.get("active_now") else "fora do periodo"
        ids = ", ".join(item.get("ids", [])[:5])
        icaos = ", ".join(item.get("icaos", []))
        title = f"<b>{_esc(item.get('title'))}</b> [{_esc(item.get('category'))}] &mdash; {status}"
        flow.append(Paragraph(title, styles["Body9"]))
        meta = " &middot; ".join(x for x in [_esc(ids), _esc(icaos)] if x)
        if meta:
            flow.append(Paragraph(meta, styles["Small"]))
        if item.get("text"):
            flow.append(Paragraph(_esc(item["text"]), styles["Mono"]))
        flow.append(Spacer(1, 5))

    return flow


def _route_section(styles, route: dict | None) -> list:
    flow = [Paragraph("Rota &mdash; briefing x plano apresentado", styles["H2FO"])]
    briefing = (route or {}).get("briefing")
    plan = (route or {}).get("plan")
    comparison = (route or {}).get("comparison")

    if not briefing and not plan:
        flow.append(Paragraph("Sem dados de rota (pagina ICAO FLIGHT PLAN nao encontrada e nenhum plano apresentado foi colado).", styles["Body9"]))
        return flow

    if briefing:
        dep = _esc(briefing.get("departure_icao") or "?")
        dest = _esc(briefing.get("destination_icao") or "?")
        flow.append(Paragraph(f"<b>PDF (ICAO FLIGHT PLAN):</b> {dep} -&gt; {dest}", styles["Body9"]))
        if briefing.get("route"):
            flow.append(Paragraph(_esc(briefing["route"]), styles["Mono"]))
        flow.append(Spacer(1, 4))

    if plan:
        dep = _esc(plan.get("departure_icao") or "?")
        arr = _esc(plan.get("arrival_icao") or "?")
        flow.append(Paragraph(f"<b>Plano apresentado:</b> {dep} -&gt; {arr}", styles["Body9"]))
        if plan.get("route"):
            flow.append(Paragraph(_esc(plan["route"]), styles["Mono"]))
        flow.append(Spacer(1, 4))

    if comparison and comparison.get("available"):
        if comparison.get("match"):
            flow.append(Paragraph("<b>Rotas identicas.</b>", styles["Body9"]))
        else:
            pct = round((comparison.get("similarity") or 0) * 100)
            flow.append(Paragraph(f"<b>Divergencia entre as rotas</b> &mdash; similaridade {pct}%.", styles["Body9"]))
            removed = []
            added = []
            for d in comparison.get("diff", []):
                if d["op"] in ("delete", "replace"):
                    removed += d.get("a", [])
                if d["op"] in ("insert", "replace"):
                    added += d.get("b", [])
            if removed:
                flow.append(Paragraph(f"So no briefing: {_esc(' '.join(removed))}", styles["Small"]))
            if added:
                flow.append(Paragraph(f"So no plano apresentado: {_esc(' '.join(added))}", styles["Small"]))
    elif plan and briefing:
        flow.append(Paragraph("Nao foi possivel comparar as rotas (rota ausente em um dos lados).", styles["Small"]))

    return flow


def _checklist_section(styles, route: dict | None) -> list:
    flow = [Paragraph("Itens de coordenacao", styles["H2FO"])]
    plan = (route or {}).get("plan")
    if not plan:
        flow.append(Paragraph("Sem plano apresentado colado &mdash; nada a checar.", styles["Body9"]))
        return flow

    linhas = [
        ("Atendimento confirmado na origem", plan.get("handling_origem_confirmado")),
        ("Atendimento confirmado no destino", plan.get("handling_destino_confirmado")),
        ("FPL aprovado", plan.get("fpl_aprovado")),
        ("FPL OK (checagem final)", plan.get("fpl_ok")),
    ]
    comparison = (route or {}).get("comparison")
    if comparison and comparison.get("available"):
        linhas.append(("Rota do plano confere com o briefing", comparison.get("match")))

    for label, value in linhas:
        flow.append(Paragraph(f"{_bool_icon(value)} {_esc(label)}", styles["Body9"]))

    for icao, val in (plan.get("slots") or {}).items():
        flow.append(Paragraph(f"Slot {_esc(icao)}: {_esc(val)}", styles["Body9"]))
    for icao, val in (plan.get("ppr") or {}).items():
        flow.append(Paragraph(f"PPR {_esc(icao)}: {_esc(val)}", styles["Body9"]))

    if plan.get("obs"):
        flow.append(Spacer(1, 4))
        flow.append(Paragraph("<b>OBS do despachante:</b>", styles["Body9"]))
        for line in plan["obs"]:
            flow.append(Paragraph(f"-&gt; {_esc(line)}", styles["Small"]))

    return flow


# ---------------------------------------------------------------------------
# Secao de documentos de tripulacao/passageiros
# ---------------------------------------------------------------------------

_DOC_FIELD_COLS = {"name": 1, "nationality": 2, "document_number": 3, "dob_iso": 4}


def _docs_section(styles, docs: dict | None) -> list:
    flow = [Paragraph("Documentos de tripulacao/passageiros", styles["H2FO"])]
    comparison = (docs or {}).get("comparison")
    if not comparison:
        flow.append(Paragraph("Nenhum documento comparado.", styles["Body9"]))
        return flow

    if docs.get("has_ocr"):
        flow.append(
            Paragraph(
                "Atencao: dados do eGAR extraidos via OCR (marcados como OCR abaixo) &mdash; "
                "confira visualmente o PDF original em caso de divergencia.",
                styles["Small"],
            )
        )
        flow.append(Spacer(1, 5))

    for group in comparison:
        people = group.get("people", [])
        name = max((p.get("name") or "" for p in people), key=len, default="(sem nome)")
        status = "DIVERGENCIA" if group.get("has_issue") else "confere"
        flow.append(Paragraph(f"<b>{_esc(name)}</b> &mdash; {status}", styles["Body9"]))
        if group.get("missing_from"):
            flow.append(Paragraph(f"Ausente em: {_esc(', '.join(group['missing_from']))}", styles["Small"]))
        flow.append(Spacer(1, 2))

        data = [["Documento", "Nome", "Nacionalidade", "Documento no", "Nascimento"]]
        mism = set(group.get("mismatched_fields", []))
        for p in people:
            doc_label = p.get("_doc", "")
            if p.get("ocr"):
                doc_label += " (OCR)"
            dob = p.get("dob_iso") or p.get("dob_raw") or "-"
            data.append(
                [
                    doc_label,
                    p.get("name") or "-",
                    p.get("nationality") or "-",
                    p.get("document_number") or "-",
                    dob,
                ]
            )

        table = Table(data, colWidths=[30 * mm, 42 * mm, 24 * mm, 28 * mm, 26 * mm], repeatRows=1)
        style_cmds = [
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), _INK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, _LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for field in mism:
            col = _DOC_FIELD_COLS.get(field)
            if col is not None:
                style_cmds.append(("TEXTCOLOR", (col, 1), (col, -1), _RED))
                style_cmds.append(("FONTNAME", (col, 1), (col, -1), "Helvetica-Bold"))
        table.setStyle(TableStyle(style_cmds))
        flow.append(table)
        flow.append(Spacer(1, 9))

    return flow


# ---------------------------------------------------------------------------
# Documento completo
# ---------------------------------------------------------------------------


def build_report(payload: dict) -> bytes:
    """payload: {"briefing": <resultado de /api/briefing/upload ou None>,
                 "travel_docs": <resultado de /api/traveldocs/compare ou None>}
    Retorna os bytes do PDF gerado."""
    styles = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title="FlightOps Companion - Relatorio de pre-voo",
    )

    briefing = payload.get("briefing") if isinstance(payload, dict) else None
    travel_docs = payload.get("travel_docs") if isinstance(payload, dict) else None

    flow: list = []
    flow.append(Paragraph("FlightOps Companion &mdash; Relatorio de pre-voo", styles["H1FO"]))
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%MZ")
    subtitle = f"Gerado em {now}"
    if briefing and briefing.get("filename"):
        subtitle += f" &middot; briefing: {_esc(briefing['filename'])}"
    flow.append(Paragraph(subtitle, styles["Small"]))
    flow.append(HRFlowable(width="100%", thickness=0.75, color=_INK, spaceBefore=6, spaceAfter=8))

    if briefing:
        flow += _weather_section(styles, briefing.get("weather"))
        flow += _notam_section(styles, briefing.get("notams"))
        route = briefing.get("route")
        if route:
            flow += _route_section(styles, route)
            flow += _checklist_section(styles, route)

    if travel_docs:
        if briefing:
            flow.append(PageBreak())
        flow += _docs_section(styles, travel_docs)

    if not briefing and not travel_docs:
        flow.append(
            Paragraph(
                "Nenhuma analise disponivel ainda &mdash; rode a leitura do briefing e/ou a "
                "comparacao de documentos antes de gerar o relatorio.",
                styles["Body9"],
            )
        )

    flow.append(Spacer(1, 14))
    flow.append(HRFlowable(width="100%", thickness=0.5, color=_LINE, spaceBefore=2, spaceAfter=6))
    flow.append(
        Paragraph(
            "Leitura best-effort gerada automaticamente pelo FlightOps Companion &mdash; "
            "sempre confira a documentacao original antes do voo.",
            styles["Small"],
        )
    )

    doc.build(flow)
    return buf.getvalue()
