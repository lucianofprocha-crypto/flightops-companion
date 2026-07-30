# FlightOps Companion — Visão original e roadmap

Este documento guarda o escopo e a visão de produto definidos antes da
migração para o app web atual (FastAPI + HTML/JS). Serve de referência
para priorizar os próximos recursos — implementados aos poucos, um de
cada vez, conforme decidido em 30/07/2026.

A imagem de referência do design system está em
`docs/design-system-reference.png`.

## Mission

Help pilots make better operational decisions through intelligent
information, presented at the right time.

## Vision

To become the operational companion every professional pilot wants
before every flight.

## North Star

Before every flight, tell the pilot only what matters.

> Good morning, Captain. You have one flight scheduled today. Your
> briefing is ready. Three operational items require your attention.
>
> Then the dashboard opens.

## Arquitetura modular (proposta original)

A ideia original era organizar o produto em "engines" independentes,
crescendo sem precisar reescrever o sistema:

- **Weather Engine** — METAR, TAF, mínimos, estatísticas. *(hoje:
  `climatology.py` + `metar_client.py` + `atis_client.py`, cobrindo a
  parte estatística/histórica e o ATIS ao vivo)*
- **Airport Engine** — pistas, cartas, procedimentos. *(não iniciado)*
- **NOTAM Engine** — classificação e resumo de NOTAMs. *(hoje:
  `briefing_parser.py` cobre a leitura a partir do PDF de briefing; uma
  fonte oficial ao vivo — ex. AISWEB/DECEA — ainda está pendente)*
- **Briefing Engine** — leitura e análise dos PDFs de despacho. *(hoje:
  `briefing_parser.py`, incluindo comparação de rota e checklist de
  coordenação)*
- **Performance Engine** (futuro) — combustível, ETPs, alternados.
  *(não iniciado — depende de ler a capa do briefing, ver Fase 2 do
  relatório em PDF no README principal)*

## Roadmap original (V1 → V3)

### V1.0 — Airport Intelligence (SBJH)

- ✅ Atualizar METAR automaticamente — *implementado via IEM Mesonet
  (histórico) em vez de REDEMET ao vivo; REDEMET/AISWEB ficou como
  possível fonte futura*
- ✅ Salvar no banco — *hoje o cache é só em memória (TTL de 1h), sem
  persistência permanente ainda*
- ✅ **Calcular eventos abaixo dos mínimos** (heatmap por mês×hora,
  calendário mensal com dias 🟢🟡🔴, lista de eventos com
  causa/duração, drill-down por evento com METAR/SPECI e gráfico de
  visibilidade/teto) — **implementado em 30/07/2026** em
  `backend/app/minima_events.py` + `GET /api/events`. Duas diferenças
  em relação ao pedido original: (1) "abaixo dos mínimos" foi definido
  como IFR/LIFR (mesmo limiar já usado em "condições adversas" no
  resto do app), não o mínimo real de nenhuma aeronave/procedimento
  específico; (2) o gráfico do evento é observação a observação (METAR
  reporta de hora em hora + specials), não minuto a minuto — não temos
  granularidade menor que isso na fonte de dados
- ✅ Dashboard — *versão simplificada (gráficos de categoria/mês/hora)*
- ✅ **Exportar Excel** — **implementado em 30/07/2026** em
  `backend/app/climatology_export.py` (`GET /api/climatology/export?format=xlsx`).
  6 abas: Resumo, Por mês, Por hora, Heatmap, Calendário, Eventos.
- ✅ **Exportar PDF do Airport Intelligence** — **implementado em
  30/07/2026**, mesmo módulo (`format=pdf`) — resumo de climatologia +
  eventos abaixo dos mínimos em texto/tabelas coloridas. Distinto do
  relatório de pré-voo (`report_generator.py`), que cobre
  briefing/documentos, não climatologia.

### V2.0 — Mais aeroportos

Já superado: o app aceita qualquer ICAO do mundo (não só SBKP, SBGR,
SBSJ, SBSP), limitado apenas pela cobertura de dados do IEM Mesonet.

### V3.0 — Briefing inteligente com risco

Visão original: arrastar um PDF de briefing e o sistema responder algo
como *"Este voo apresenta risco moderado de atraso devido à
meteorologia histórica no destino. A probabilidade de o SBJH estar
abaixo dos mínimos no horário estimado de chegada é de 9%. O alternado
SBKP permaneceu operacional em 97% dos eventos semelhantes."*

Isso cruzaria a climatologia histórica (Airport Intelligence) com o
horário estimado de chegada extraído do briefing — ainda não
implementado; hoje as duas features (climatologia e leitura de
briefing) existem separadas, sem essa correlação automática.

## Design system de referência

Ver `docs/design-system-reference.png`.

- Primary `#0B1320` · Secondary `#15202B` · Accent `#00A2A9`
- Warning `#F5A623` · Danger `#E63946` · Success `#22C55E` · Neutral `#E2E8F0`
- Tipografia: Inter (Semibold / Medium / Regular)
- Layout: sidebar de navegação (Dashboard, Weather Intelligence, Airport
  Intelligence, Flight Briefing, NOTAM Intelligence, Dispatch, Flight
  Replay, Knowledge Base, Statistics, Settings) + dashboard central em
  cards: voo atual, operational risk score (gauge 0–100), status chips
  (Weather/NOTAM/Airport/Alternate/Fuel/Handling), METAR com campos
  decompostos, NOTAM crítico em destaque, mini-mapa de rota, flight
  briefing summary com checklist, versão mobile equivalente.

**✅ Paleta e tipografia — implementado em 30/07/2026.** `frontend/styles.css`
e `frontend/app.js` (cores de gráficos/badges) agora usam as cores e a
fonte Inter acima.

**✅ Sidebar + Dashboard consolidado — implementado em 30/07/2026.** Layout
migrou para sidebar de navegação (4 seções: Dashboard, Airport
Intelligence, Flight Briefing, Dispatch) + uma view de Dashboard com
cards de status alimentados pelos dados que cada seção já busca — sem
nenhuma chamada nova ao backend. Diferenças em relação ao mockup
original: **sem** operational risk score (gauge 0–100), **sem** mini-mapa
de rota, **sem** status chips de Fuel/Handling/Alternate — o app não
calcula esses dados hoje (não lê combustível, tripulação/SOB nem
desenha mapa) e decidimos não simular números numa ferramenta de
decisão operacional. Ficam como candidatos a um próximo passo, se/quando
houver uma fonte de dados real pra eles (ver "Relatório em PDF — Fase 2"
no README, que depende da mesma leitura de capa do briefing).

## O que já foi implementado (fora da ordem do roadmap original)

Como registro — a versão atual não seguiu o roadmap V1→V3 à risca; foi
priorizando o que o usuário mais precisava no dia a dia:

- Climatologia estatística por ICAO livre (VFR/MVFR/IFR/LIFR por
  mês/hora) + ATIS ao vivo (cobertura EUA)
- Eventos abaixo dos mínimos: heatmap, calendário, lista de eventos e
  drill-down com METAR/SPECI + gráfico de visibilidade/teto
- Exportar Airport Intelligence (climatologia + eventos) em Excel e PDF
- Leitura de flight briefing em PDF: METAR/TAF/SIGMET, NOTAM
  (fechamentos de pista/táxi/aeródromo), comparação de rota
  (briefing × plano apresentado) + checklist de coordenação
- Comparação de documentos de tripulação/passageiros (GEDEC, eAPIS,
  eGAR via OCR, lista de passageiros)
- Relatório de pré-voo em PDF (Fase 1: texto/tabelas, sem mapa/combustível)
- Deploy em produção (Render, via Docker por causa do OCR)
