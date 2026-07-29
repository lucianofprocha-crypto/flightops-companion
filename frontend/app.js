const API_BASE = ""; // mesma origem (backend serve o frontend)

const $icao = document.getElementById("icao");
const $icaoSugestoes = document.getElementById("icao-sugestoes");
const $btn = document.getElementById("analisar");
const $status = document.getElementById("status");
const $resultados = document.getElementById("resultados");
const $semDados = document.getElementById("sem-dados");
const $atisCard = document.getElementById("atis-card");
const $atisContent = document.getElementById("atis-content");
const $metarAtualContent = document.getElementById("metar-atual-content");

const $briefingFile = document.getElementById("briefing-file");
const $planText = document.getElementById("plan-text");
const $btnBriefing = document.getElementById("analisar-briefing");
const $briefingStatus = document.getElementById("briefing-status");
const $briefingResultados = document.getElementById("briefing-resultados");
const $briefingWeather = document.getElementById("briefing-weather");
const $briefingNotamResumo = document.getElementById("briefing-notam-resumo");
const $briefingNotams = document.getElementById("briefing-notams");
const $routeCard = document.getElementById("route-card");
const $routeContent = document.getElementById("route-content");
const $checklistCard = document.getElementById("checklist-card");
const $checklistContent = document.getElementById("checklist-content");

const $docGedec = document.getElementById("doc-gedec");
const $docEapis = document.getElementById("doc-eapis");
const $docEgar = document.getElementById("doc-egar");
const $docPax = document.getElementById("doc-pax");
const $btnDocs = document.getElementById("comparar-docs");
const $docsStatus = document.getElementById("docs-status");
const $docsResultados = document.getElementById("docs-resultados");
const $docsOcrAviso = document.getElementById("docs-ocr-aviso");
const $docsComparacao = document.getElementById("docs-comparacao");

const $btnRelatorio = document.getElementById("gerar-relatorio");
const $relatorioStatus = document.getElementById("relatorio-status");

const $eventsResultados = document.getElementById("events-resultados");
const $evDisponibilidade = document.getElementById("ev-disponibilidade");
const $evHoras = document.getElementById("ev-horas");
const $evContagem = document.getElementById("ev-contagem");
const $evMaior = document.getElementById("ev-maior");
const $evMenorVis = document.getElementById("ev-menorvis");
const $evMenorTeto = document.getElementById("ev-menorteto");
const $eventsHeatmap = document.getElementById("events-heatmap");
const $eventsMesSelect = document.getElementById("events-mes-select");
const $eventsCalendario = document.getElementById("events-calendario");
const $eventsLista = document.getElementById("events-lista");
const $eventsDetalheCard = document.getElementById("events-detalhe-card");
const $eventsDetalheResumo = document.getElementById("events-detalhe-resumo");
const $eventsDetalheMetars = document.getElementById("events-detalhe-metars");

let chartCategorias, chartMes, chartHora, chartEventoDetalhe;
let lastEventsData = null;

// Últimos resultados de cada análise, guardados em memória pra alimentar o
// relatório em PDF sem precisar reler os PDFs originais.
let lastBriefingResult = null;
let lastDocsResult = null;

const CATEGORY_COLORS = {
  VFR: "#22c55e",
  MVFR: "#3b82f6",
  IFR: "#f59e0b",
  LIFR: "#ef4444",
  UNKNOWN: "#6b7280",
};

async function carregarSugestoes() {
  try {
    const resp = await fetch(`${API_BASE}/api/airports`);
    const data = await resp.json();
    $icaoSugestoes.innerHTML = "";
    for (const code of data.airports) {
      const opt = document.createElement("option");
      opt.value = code;
      $icaoSugestoes.appendChild(opt);
    }
    if (!$icao.value && data.airports.length) {
      $icao.value = data.airports[0];
    }
  } catch (err) {
    // Sugestões são só conveniência — sem elas o campo livre ainda funciona.
  }
}

function setStatus(msg, isError = false) {
  $status.textContent = msg;
  $status.classList.toggle("error", isError);
}

// Período fixo: única opção é 365 dias, sem seletor na UI.
function periodoSelecionado() {
  return "365d";
}

function periodoLabel(p) {
  return { "365d": "últimos 365 dias" }[p] || p;
}

function icaoValido(icao) {
  return /^[A-Z0-9]{4}$/.test(icao);
}

async function analisar() {
  const icao = $icao.value.trim().toUpperCase();
  const periodo = periodoSelecionado();

  if (!icaoValido(icao)) {
    setStatus("Digite um código ICAO válido (4 letras, ex: SBGR).", true);
    return;
  }

  $btn.disabled = true;
  $resultados.classList.add("hidden");
  $semDados.classList.add("hidden");
  $atisCard.classList.add("hidden");
  $eventsResultados.classList.add("hidden");
  setStatus(`Buscando histórico METAR de ${icao} (${periodoLabel(periodo)})...`);

  // ATIS e eventos abaixo dos mínimos são complementos — buscamos em
  // paralelo e nunca deixamos eles travarem a análise principal.
  buscarAtis(icao);
  buscarEventos(icao, periodo);

  try {
    const resp = await fetch(
      `${API_BASE}/api/climatology?icao=${encodeURIComponent(icao)}&period=${encodeURIComponent(periodo)}`
    );

    if (resp.status === 404) {
      $semDados.classList.remove("hidden");
      setStatus("");
      return;
    }

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Erro ${resp.status}`);
    }

    const data = await resp.json();
    renderResultados(data);
    setStatus("");
  } catch (err) {
    setStatus(`Erro: ${err.message}`, true);
  } finally {
    $btn.disabled = false;
  }
}

async function buscarAtis(icao) {
  try {
    const resp = await fetch(`${API_BASE}/api/atis?icao=${encodeURIComponent(icao)}`);
    if (!resp.ok) return;

    const data = await resp.json();
    if (!data.available || !data.reports.length) return;

    renderAtis(data.reports);
  } catch (err) {
    // Silencioso: ATIS é opcional, não deve gerar erro visível.
  }
}

function renderAtis(reports) {
  $atisContent.innerHTML = "";
  for (const report of reports) {
    const bloco = document.createElement("div");
    bloco.className = "atis-report";

    const titulo = document.createElement("div");
    titulo.className = "atis-report-title";
    const tipo = report.type ? report.type.toUpperCase() : "ATIS";
    const codigo = report.code ? ` — Info ${report.code}` : "";
    titulo.textContent = `${tipo}${codigo}`;

    // Div (não <pre>) com wrap forçado inline, pra não depender do CSS
    // externo (cache de navegador) para o comportamento de quebra de linha.
    const texto = document.createElement("div");
    texto.className = "atis-report-text";
    texto.textContent = report.datis || "";
    texto.style.whiteSpace = "pre-wrap";
    texto.style.overflowWrap = "anywhere";
    texto.style.wordBreak = "break-word";
    texto.style.maxWidth = "100%";
    texto.style.boxSizing = "border-box";

    bloco.appendChild(titulo);
    bloco.appendChild(texto);
    $atisContent.appendChild(bloco);
  }
  $atisCard.classList.remove("hidden");
}

function renderMetarAtual(current) {
  $metarAtualContent.innerHTML = "";
  if (!current || !current.raw_metar) {
    $metarAtualContent.textContent = "METAR atual indisponível.";
    return;
  }

  const texto = document.createElement("div");
  texto.textContent = current.raw_metar;
  texto.style.whiteSpace = "pre-wrap";
  texto.style.overflowWrap = "anywhere";
  texto.style.wordBreak = "break-word";
  texto.style.maxWidth = "100%";
  texto.style.boxSizing = "border-box";
  texto.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, monospace";
  texto.style.fontSize = "13px";
  texto.style.lineHeight = "1.5";

  const meta = document.createElement("p");
  meta.className = "muted";
  meta.style.margin = "8px 0 0";
  const horario = current.valid ? new Date(current.valid).toISOString().slice(0, 16).replace("T", " ") + "Z" : "";
  meta.textContent = `Categoria: ${current.flight_category} · Observado em ${horario}`;

  $metarAtualContent.appendChild(texto);
  $metarAtualContent.appendChild(meta);
}

function renderResultados(data) {
  renderMetarAtual(data.current);

  document.getElementById("res-titulo").textContent = `${data.icao} — ${periodoLabel(data.period)}`;
  document.getElementById("res-amostra").textContent =
    `${data.sample.observations} observações · ${data.sample.start.slice(0, 10)} a ${data.sample.end.slice(0, 10)}`;

  document.getElementById("m-temp").textContent =
    data.temperature_c.mean != null ? `${data.temperature_c.mean}°C (${data.temperature_c.min}° a ${data.temperature_c.max}°)` : "—";

  document.getElementById("m-vento").textContent =
    data.wind_kt.mean_speed != null
      ? `${data.wind_kt.mean_speed} kt${data.wind_kt.dominant_direction ? " · " + data.wind_kt.dominant_direction : ""}`
      : "—";

  document.getElementById("m-vis").textContent =
    data.visibility_m.mean != null ? `${data.visibility_m.mean.toLocaleString("pt-BR")} m` : "—";

  document.getElementById("m-adversas").textContent = `${data.adverse_conditions_pct}%`;

  renderChartCategorias(data.flight_category);
  renderChartMes(data.by_month);
  renderChartHora(data.by_hour_utc);

  $resultados.classList.remove("hidden");
}

function renderChartCategorias(catData) {
  const labels = Object.keys(catData).filter((k) => catData[k].count > 0);
  const values = labels.map((k) => catData[k].pct);
  const colors = labels.map((k) => CATEGORY_COLORS[k] || "#888");

  chartCategorias?.destroy();
  chartCategorias = new Chart(document.getElementById("chart-categorias"), {
    type: "doughnut",
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: colors }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#e8edf5" } } },
    },
  });
}

function renderChartMes(byMonth) {
  const meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  const labels = [];
  const values = [];
  for (let m = 1; m <= 12; m++) {
    const entry = byMonth[String(m)];
    if (entry) {
      labels.push(meses[m - 1]);
      values.push(entry.adverse_pct);
    }
  }

  chartMes?.destroy();
  chartMes = new Chart(document.getElementById("chart-mes"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "% condições adversas", data: values, backgroundColor: "#3b82f6" }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#93a2b8" }, grid: { color: "#2a3548" } },
        y: { ticks: { color: "#93a2b8" }, grid: { color: "#2a3548" }, beginAtZero: true },
      },
      plugins: { legend: { display: false } },
    },
  });
}

function renderChartHora(byHour) {
  const labels = [];
  const values = [];
  for (let h = 0; h < 24; h++) {
    const entry = byHour[String(h)];
    labels.push(`${String(h).padStart(2, "0")}h`);
    values.push(entry ? entry.adverse_pct : 0);
  }

  chartHora?.destroy();
  chartHora = new Chart(document.getElementById("chart-hora"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "% condições adversas", data: values, backgroundColor: "#f59e0b" }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#93a2b8" }, grid: { color: "#2a3548" } },
        y: { ticks: { color: "#93a2b8" }, grid: { color: "#2a3548" }, beginAtZero: true },
      },
      plugins: { legend: { display: false } },
    },
  });
}

async function buscarEventos(icao, periodo) {
  try {
    const resp = await fetch(
      `${API_BASE}/api/events?icao=${encodeURIComponent(icao)}&period=${encodeURIComponent(periodo)}`
    );
    if (!resp.ok) {
      $eventsResultados.classList.add("hidden");
      return;
    }
    const data = await resp.json();
    renderEvents(data);
  } catch (err) {
    // Silencioso: eventos são um complemento, não devem travar a análise principal.
    $eventsResultados.classList.add("hidden");
  }
}

function formatMinutosLabel(minutos) {
  if (minutos < 60) return `${minutos} min`;
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  return `${h}h${String(m).padStart(2, "0")}`;
}

function renderEvents(data) {
  lastEventsData = data;

  $evDisponibilidade.textContent = `${data.headline.availability_pct}%`;
  $evHoras.textContent = `${data.headline.hours_below_minima} h`;
  $evContagem.textContent = data.headline.event_count;
  $evMaior.textContent = data.headline.longest_event_label;
  $evMenorVis.textContent =
    data.headline.min_visibility_m != null ? `${data.headline.min_visibility_m.toLocaleString("pt-BR")} m` : "—";
  $evMenorTeto.textContent = data.headline.min_ceiling_ft != null ? `${data.headline.min_ceiling_ft} ft` : "—";

  renderHeatmap(data.heatmap);
  popularSeletorMes(data.calendar);
  renderEventsList(data.events);

  $eventsDetalheCard.classList.add("hidden");
  $eventsResultados.classList.remove("hidden");
}

function renderHeatmap(heatmap) {
  $eventsHeatmap.innerHTML = "";

  const meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  const table = document.createElement("table");
  table.className = "heatmap-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.appendChild(document.createElement("th"));
  for (const m of meses) {
    const th = document.createElement("th");
    th.textContent = m;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (let hour = 0; hour < 24; hour++) {
    const tr = document.createElement("tr");
    const thHour = document.createElement("th");
    thHour.className = "heatmap-hour-label";
    thHour.textContent = `${String(hour).padStart(2, "0")}h`;
    tr.appendChild(thHour);

    for (let month = 1; month <= 12; month++) {
      const cellData = heatmap[String(month)]?.[String(hour)];
      const td = document.createElement("td");
      const pct = cellData ? cellData.below_minima_pct : 0;
      const hasData = cellData && cellData.count > 0;
      const cell = document.createElement("div");
      cell.className = "heatmap-cell";
      if (hasData) {
        const alpha = Math.min(1, pct / 100);
        cell.style.background = `rgba(239, 68, 68, ${(0.08 + alpha * 0.85).toFixed(2)})`;
        cell.title = `${meses[month - 1]} ${String(hour).padStart(2, "0")}h — ${pct}% abaixo dos mínimos (${cellData.count} obs.)`;
      } else {
        cell.style.background = "transparent";
        cell.title = `${meses[month - 1]} ${String(hour).padStart(2, "0")}h — sem dados`;
      }
      td.appendChild(cell);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  $eventsHeatmap.appendChild(table);
}

function popularSeletorMes(calendar) {
  const meses = [...new Set(Object.keys(calendar).map((d) => d.slice(0, 7)))].sort();
  const anterior = $eventsMesSelect.value;
  $eventsMesSelect.innerHTML = "";

  const nomesMes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  for (const mesKey of meses) {
    const [ano, mes] = mesKey.split("-");
    const opt = document.createElement("option");
    opt.value = mesKey;
    opt.textContent = `${nomesMes[parseInt(mes, 10) - 1]} ${ano}`;
    $eventsMesSelect.appendChild(opt);
  }

  const selecionado = meses.includes(anterior) ? anterior : meses[meses.length - 1];
  if (selecionado) {
    $eventsMesSelect.value = selecionado;
    renderCalendar(calendar, selecionado);
  } else {
    $eventsCalendario.innerHTML = "";
  }
}

function renderCalendar(calendar, mesKey) {
  $eventsCalendario.innerHTML = "";

  const [ano, mes] = mesKey.split("-").map((v) => parseInt(v, 10));
  const primeiroDia = new Date(Date.UTC(ano, mes - 1, 1));
  const diasNoMes = new Date(Date.UTC(ano, mes, 0)).getUTCDate();
  const offset = primeiroDia.getUTCDay(); // 0 = domingo

  for (const w of ["D", "S", "T", "Q", "Q", "S", "S"]) {
    const el = document.createElement("div");
    el.className = "calendar-weekday";
    el.textContent = w;
    $eventsCalendario.appendChild(el);
  }

  for (let i = 0; i < offset; i++) {
    const el = document.createElement("div");
    el.className = "calendar-day empty";
    $eventsCalendario.appendChild(el);
  }

  for (let dia = 1; dia <= diasNoMes; dia++) {
    const dateKey = `${ano}-${String(mes).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
    const info = calendar[dateKey];
    const el = document.createElement("div");
    el.textContent = dia;
    if (!info) {
      el.className = "calendar-day nodata";
      el.title = "Sem dados";
    } else {
      el.className = `calendar-day ${info.status}`;
      el.title = `${info.minutes_below_minima} min abaixo dos mínimos (${info.observation_count} obs.)`;
    }
    $eventsCalendario.appendChild(el);
  }
}

function renderEventsList(events) {
  $eventsLista.innerHTML = "";

  if (!events.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "Nenhum evento abaixo dos mínimos neste período.";
    $eventsLista.appendChild(p);
    return;
  }

  const table = document.createElement("table");
  table.className = "events-table";

  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>Data</th><th>Início</th><th>Fim</th><th>Duração</th><th>Causa</th><th>Pior cat.</th></tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  events.forEach((evento, idx) => {
    const tr = document.createElement("tr");
    tr.className = "event-row";
    tr.dataset.index = idx;

    const start = new Date(evento.start);
    const end = new Date(evento.end);
    const dataStr = start.toISOString().slice(0, 10).split("-").reverse().join("/");
    const inicioStr = start.toISOString().slice(11, 16) + "Z";
    const fimStr = end.toISOString().slice(11, 16) + "Z" + (evento.end_uncertain ? " (?)" : "");

    tr.innerHTML = `
      <td>${dataStr}</td>
      <td>${inicioStr}</td>
      <td>${fimStr}</td>
      <td>${evento.duration_label}</td>
      <td>${evento.cause || "—"}</td>
      <td class="worst-${evento.worst_category.toLowerCase()}">${evento.worst_category}</td>
    `;
    tr.addEventListener("click", () => selecionarEvento(idx));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  $eventsLista.appendChild(table);
}

function selecionarEvento(idx) {
  if (!lastEventsData) return;
  const evento = lastEventsData.events[idx];
  if (!evento) return;

  for (const row of $eventsLista.querySelectorAll("tr.event-row")) {
    row.classList.toggle("selected", parseInt(row.dataset.index, 10) === idx);
  }

  renderEventDetail(evento);
}

function renderEventDetail(evento) {
  $eventsDetalheCard.classList.remove("hidden");

  const resumoPartes = [
    `Pior categoria: ${evento.worst_category}`,
    evento.min_visibility_m != null ? `menor vis. ${evento.min_visibility_m} m` : null,
    evento.min_ceiling_ft != null ? `menor teto ${evento.min_ceiling_ft} ft` : null,
    evento.cause ? `causa provável: ${evento.cause}` : null,
    evento.end_uncertain ? "fim estimado incerto (gap nos dados ou evento em aberto)" : null,
  ].filter(Boolean);
  $eventsDetalheResumo.textContent = resumoPartes.join(" · ");

  const labels = evento.observations.map((o) => o.valid.slice(11, 16) + "Z");
  const visData = evento.observations.map((o) => o.visibility_m);
  const ceilData = evento.observations.map((o) => o.ceiling_ft);

  chartEventoDetalhe?.destroy();
  chartEventoDetalhe = new Chart(document.getElementById("events-detalhe-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Visibilidade (m)",
          data: visData,
          borderColor: "#3b82f6",
          backgroundColor: "transparent",
          yAxisID: "y",
          tension: 0.2,
        },
        {
          label: "Teto (ft)",
          data: ceilData,
          borderColor: "#f59e0b",
          backgroundColor: "transparent",
          yAxisID: "y1",
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#93a2b8" }, grid: { color: "#2a3548" } },
        y: {
          position: "left",
          ticks: { color: "#93a2b8" },
          grid: { color: "#2a3548" },
          title: { display: true, text: "m", color: "#93a2b8" },
        },
        y1: {
          position: "right",
          ticks: { color: "#93a2b8" },
          grid: { display: false },
          title: { display: true, text: "ft", color: "#93a2b8" },
        },
      },
      plugins: { legend: { labels: { color: "#e8edf5" } } },
    },
  });

  $eventsDetalheMetars.innerHTML = "";
  const label = document.createElement("div");
  label.className = "weather-field-label";
  label.textContent = "METAR/SPECI (observação a observação — não há dado minuto a minuto)";
  $eventsDetalheMetars.appendChild(label);

  for (const o of evento.observations) {
    const div = document.createElement("div");
    div.className = "metar-drilldown-item" + (o.context ? " context" : "");
    div.textContent = o.raw_metar + (o.context ? "  (recuperação — fora do evento)" : "");
    $eventsDetalheMetars.appendChild(div);
  }

  $eventsDetalheCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function setBriefingStatus(msg, isError = false) {
  $briefingStatus.textContent = msg;
  $briefingStatus.classList.toggle("error", isError);
}

function wrapText(el, content) {
  el.textContent = content;
  el.style.whiteSpace = "pre-wrap";
  el.style.overflowWrap = "anywhere";
  el.style.wordBreak = "break-word";
  el.style.maxWidth = "100%";
  el.style.boxSizing = "border-box";
}

async function analisarBriefing() {
  const file = $briefingFile.files[0];
  if (!file) {
    setBriefingStatus("Selecione um arquivo PDF primeiro.", true);
    return;
  }

  $btnBriefing.disabled = true;
  $briefingResultados.classList.add("hidden");
  setBriefingStatus(`Lendo ${file.name}...`);

  try {
    const formData = new FormData();
    formData.append("file", file);
    const planText = $planText.value.trim();
    if (planText) {
      formData.append("plan_text", planText);
    }

    const resp = await fetch(`${API_BASE}/api/briefing/upload`, {
      method: "POST",
      body: formData,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Erro ${resp.status}`);
    }

    const data = await resp.json();
    lastBriefingResult = data;
    renderBriefing(data);
    setBriefingStatus("");
  } catch (err) {
    setBriefingStatus(`Erro: ${err.message}`, true);
  } finally {
    $btnBriefing.disabled = false;
  }
}

function renderBriefing(data) {
  renderBriefingWeather(data.weather);
  renderBriefingNotams(data.notams);
  renderRoute(data.route);
  renderChecklist(data.route);
  $briefingResultados.classList.remove("hidden");
}

function renderBriefingWeather(weather) {
  $briefingWeather.innerHTML = "";

  if (!weather || !weather.available || !weather.stations.length) {
    $briefingWeather.textContent = "Nenhuma seção de METAR/TAF encontrada neste PDF.";
    return;
  }

  for (const station of weather.stations) {
    const bloco = document.createElement("div");
    bloco.className = "weather-station";

    const header = document.createElement("div");
    header.className = "notam-item-header";

    const titulo = document.createElement("span");
    titulo.className = "weather-station-title";
    titulo.style.marginBottom = "0";
    titulo.textContent = `${station.role} — ${station.icao}${station.name ? " · " + station.name : ""}`;
    header.appendChild(titulo);

    if (station.category) {
      const badge = document.createElement("span");
      badge.className = `notam-badge weather-badge-${station.category.toLowerCase()}`;
      badge.textContent = station.category;
      header.appendChild(badge);
    }

    bloco.appendChild(header);

    if (station.metar) {
      const label = document.createElement("div");
      label.className = "weather-field-label";
      label.textContent = "METAR";
      const texto = document.createElement("div");
      texto.className = "notam-text";
      wrapText(texto, station.metar);
      bloco.appendChild(label);
      bloco.appendChild(texto);
    }

    if (station.taf) {
      const label = document.createElement("div");
      label.className = "weather-field-label";
      label.textContent = "TAF";
      const texto = document.createElement("div");
      texto.className = "notam-text";
      wrapText(texto, station.taf);
      bloco.appendChild(label);
      bloco.appendChild(texto);
    }

    $briefingWeather.appendChild(bloco);
  }

  if (weather.sigmet_airmet) {
    const bloco = document.createElement("div");
    bloco.className = "weather-station";
    const label = document.createElement("div");
    label.className = "weather-field-label";
    label.textContent = "SIGMET / AIRMET";
    const texto = document.createElement("div");
    texto.className = "notam-text";
    wrapText(texto, weather.sigmet_airmet);
    bloco.appendChild(label);
    bloco.appendChild(texto);
    $briefingWeather.appendChild(bloco);
  }
}

function renderBriefingNotams(notams) {
  $briefingNotams.innerHTML = "";

  if (!notams || notams.total === 0) {
    $briefingNotamResumo.textContent = "Nenhum fechamento de pista, táxi ou aeródromo encontrado neste PDF.";
    return;
  }

  $briefingNotamResumo.textContent =
    `${notams.total} fechamentos (pista/táxi/aeródromo) · ${notams.active_now} vigentes agora` +
    (notams.new_today ? ` · ${notams.new_today} novos hoje` : "");

  const chipsWrap = document.createElement("div");
  chipsWrap.className = "notam-summary-chips";
  for (const [categoria, count] of Object.entries(notams.by_category)) {
    const chip = document.createElement("span");
    chip.className = "notam-chip";
    chip.textContent = `${categoria}: ${count}`;
    chipsWrap.appendChild(chip);
  }
  $briefingNotams.appendChild(chipsWrap);

  for (const item of notams.top_attention) {
    const bloco = document.createElement("div");
    bloco.className = "notam-item";

    const header = document.createElement("div");
    header.className = "notam-item-header";

    const titulo = document.createElement("span");
    titulo.className = "notam-title";
    titulo.textContent = item.title;
    header.appendChild(titulo);

    const badgeAtivo = document.createElement("span");
    badgeAtivo.className = `notam-badge ${item.active_now ? "active" : "inactive"}`;
    badgeAtivo.textContent = item.active_now ? "vigente" : "fora do período";
    header.appendChild(badgeAtivo);

    if (item.new_today) {
      const badgeNovo = document.createElement("span");
      badgeNovo.className = "notam-badge new";
      badgeNovo.textContent = "novo hoje";
      header.appendChild(badgeNovo);
    }

    bloco.appendChild(header);

    const meta = document.createElement("div");
    meta.className = "notam-meta";
    const idsTxt = item.ids.slice(0, 5).join(", ") + (item.ids.length > 5 ? "…" : "");
    const icaosTxt = item.icaos.length ? ` · ${item.icaos.join(", ")}` : "";
    const countTxt = item.count > 1 ? ` · ${item.count}x` : "";
    meta.textContent = `${item.category} · ${idsTxt}${icaosTxt}${countTxt}`;
    bloco.appendChild(meta);

    const texto = document.createElement("div");
    texto.className = "notam-text";
    wrapText(texto, item.text);
    bloco.appendChild(texto);

    $briefingNotams.appendChild(bloco);
  }
}

function buildDiffLine(diffArray, side) {
  const wrap = document.createElement("div");
  wrap.className = "route-tokens";
  for (const seg of diffArray) {
    const tokens = seg[side];
    if (!tokens.length) continue;
    for (const tok of tokens) {
      const span = document.createElement("span");
      span.className = "route-token";
      if (seg.op !== "equal") {
        span.classList.add(side === "a" ? "removed" : "added");
      }
      span.textContent = tok;
      wrap.appendChild(span);
    }
  }
  return wrap;
}

function renderRoute(route) {
  $routeContent.innerHTML = "";

  if (!route || (!route.briefing && !route.plan)) {
    $routeCard.classList.add("hidden");
    return;
  }
  $routeCard.classList.remove("hidden");

  const briefing = route.briefing;
  const plan = route.plan;
  const cmp = route.comparison;

  if (briefing) {
    const info = document.createElement("p");
    info.className = "muted";
    info.style.margin = "0 0 8px";
    info.textContent =
      `PDF: ${briefing.departure_icao || "?"} → ${briefing.destination_icao || "?"}` +
      (briefing.alternate_icao ? ` (altn ${briefing.alternate_icao})` : "");
    $routeContent.appendChild(info);
  }

  if (plan) {
    const info = document.createElement("p");
    info.className = "muted";
    info.style.margin = "0 0 8px";
    info.textContent = `Plano apresentado: ${plan.departure_icao || "?"} → ${plan.arrival_icao || "?"}`;
    $routeContent.appendChild(info);
  }

  if (cmp && cmp.available) {
    const badge = document.createElement("span");
    badge.className = `notam-badge ${cmp.match ? "active" : "inactive"}`;
    badge.textContent = cmp.match ? "rotas idênticas" : `divergência · similaridade ${Math.round(cmp.similarity * 100)}%`;
    badge.style.marginBottom = "8px";
    badge.style.display = "inline-block";
    $routeContent.appendChild(badge);

    const lineA = document.createElement("div");
    lineA.className = "route-line";
    const labA = document.createElement("span");
    labA.className = "route-line-label";
    labA.textContent = "Briefing";
    lineA.appendChild(labA);
    lineA.appendChild(buildDiffLine(cmp.diff, "a"));
    $routeContent.appendChild(lineA);

    const lineB = document.createElement("div");
    lineB.className = "route-line";
    const labB = document.createElement("span");
    labB.className = "route-line-label";
    labB.textContent = "Plano";
    lineB.appendChild(labB);
    lineB.appendChild(buildDiffLine(cmp.diff, "b"));
    $routeContent.appendChild(lineB);
  } else if (briefing && briefing.route_tokens.length) {
    const lineA = document.createElement("div");
    lineA.className = "route-line";
    const labA = document.createElement("span");
    labA.className = "route-line-label";
    labA.textContent = "Briefing";
    lineA.appendChild(labA);
    const tokensWrap = document.createElement("div");
    tokensWrap.className = "route-tokens";
    for (const tok of briefing.route_tokens) {
      const span = document.createElement("span");
      span.className = "route-token";
      span.textContent = tok;
      tokensWrap.appendChild(span);
    }
    lineA.appendChild(tokensWrap);
    $routeContent.appendChild(lineA);

    const hint = document.createElement("p");
    hint.className = "muted";
    hint.style.margin = "8px 0 0";
    hint.textContent = "Cole o plano apresentado no campo acima para comparar a rota.";
    $routeContent.appendChild(hint);
  } else if (plan && !briefing) {
    const hint = document.createElement("p");
    hint.className = "muted";
    hint.textContent = "Não foi possível localizar a página ICAO FLIGHT PLAN neste PDF para comparar.";
    $routeContent.appendChild(hint);
  }
}

function checklistStatus(value) {
  if (value === true) return { cls: "ok", icon: "✓" };
  if (value === false) return { cls: "missing", icon: "✗" };
  return { cls: "unknown", icon: "?" };
}

function addChecklistItem(container, value, label) {
  const { cls, icon } = checklistStatus(value);
  const item = document.createElement("div");
  item.className = "checklist-item";
  const iconEl = document.createElement("span");
  iconEl.className = `checklist-icon ${cls}`;
  iconEl.textContent = icon;
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  item.appendChild(iconEl);
  item.appendChild(labelEl);
  container.appendChild(item);
}

function renderChecklist(route) {
  $checklistContent.innerHTML = "";
  const plan = route ? route.plan : null;

  if (!plan) {
    $checklistCard.classList.add("hidden");
    return;
  }
  $checklistCard.classList.remove("hidden");

  addChecklistItem($checklistContent, plan.handling_origem_confirmado, "Atendimento confirmado na origem");
  addChecklistItem($checklistContent, plan.handling_destino_confirmado, "Atendimento confirmado no destino");
  addChecklistItem($checklistContent, plan.fpl_aprovado, "FPL aprovado");
  addChecklistItem($checklistContent, plan.fpl_ok, "FPL OK (checagem final)");

  if (route.comparison && route.comparison.available) {
    addChecklistItem($checklistContent, route.comparison.match, "Rota do plano confere com o briefing");
  }

  for (const [icao, valor] of Object.entries(plan.slots || {})) {
    addChecklistItem($checklistContent, true, `Slot ${icao}: ${valor}`);
  }
  for (const [icao, valor] of Object.entries(plan.ppr || {})) {
    addChecklistItem($checklistContent, true, `PPR ${icao}: ${valor}`);
  }

  if (plan.obs && plan.obs.length) {
    const obsLabel = document.createElement("div");
    obsLabel.className = "weather-field-label";
    obsLabel.style.marginTop = "10px";
    obsLabel.textContent = "OBS do despachante";
    $checklistContent.appendChild(obsLabel);

    const obsText = document.createElement("div");
    obsText.className = "notam-text";
    wrapText(obsText, plan.obs.map((l) => `→ ${l}`).join("\n"));
    $checklistContent.appendChild(obsText);
  }
}

function setDocsStatus(msg, isError = false) {
  $docsStatus.textContent = msg;
  $docsStatus.classList.toggle("error", isError);
}

async function compararDocumentos() {
  const gedec = $docGedec.files[0];
  const eapis = $docEapis.files[0];
  const egar = $docEgar.files[0];
  const pax = $docPax.files[0];

  if (!gedec && !eapis && !egar && !pax) {
    setDocsStatus("Envie ao menos um PDF (GEDEC, eAPIS, eGAR ou lista de passageiros).", true);
    return;
  }

  $btnDocs.disabled = true;
  $docsResultados.classList.add("hidden");
  setDocsStatus("Lendo documentos...");

  try {
    const formData = new FormData();
    if (gedec) formData.append("gedec", gedec);
    if (eapis) formData.append("eapis", eapis);
    if (egar) formData.append("egar", egar);
    if (pax) formData.append("passenger_list", pax);

    const resp = await fetch(`${API_BASE}/api/traveldocs/compare`, {
      method: "POST",
      body: formData,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Erro ${resp.status}`);
    }

    const data = await resp.json();
    lastDocsResult = data;
    renderDocsComparison(data);
    setDocsStatus("");
  } catch (err) {
    setDocsStatus(`Erro: ${err.message}`, true);
  } finally {
    $btnDocs.disabled = false;
  }
}

const DOCS_FIELD_LABELS = {
  name: "Nome",
  nationality: "Nacionalidade",
  document_number: "Documento nº",
  dob_iso: "Nascimento",
};

function renderDocsComparison(data) {
  $docsComparacao.innerHTML = "";

  $docsOcrAviso.classList.toggle("hidden", !data.has_ocr);

  if (!data.comparison || !data.comparison.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "Nenhuma pessoa reconhecida nos documentos enviados.";
    $docsComparacao.appendChild(p);
    $docsResultados.classList.remove("hidden");
    return;
  }

  for (const group of data.comparison) {
    const card = document.createElement("div");
    card.className = "card";
    card.style.overflow = "hidden";
    card.style.maxWidth = "100%";

    const header = document.createElement("div");
    header.className = "notam-item-header";

    const nomeRepresentativo =
      group.people.reduce((a, b) => ((a.name || "").length >= (b.name || "").length ? a : b)).name ||
      "(sem nome)";
    const titulo = document.createElement("span");
    titulo.className = "notam-title";
    titulo.textContent = nomeRepresentativo;
    header.appendChild(titulo);

    const badge = document.createElement("span");
    badge.className = `notam-badge ${group.has_issue ? "inactive" : "active"}`;
    badge.textContent = group.has_issue ? "divergência" : "confere";
    header.appendChild(badge);

    card.appendChild(header);

    if (group.missing_from && group.missing_from.length) {
      const missing = document.createElement("p");
      missing.className = "muted";
      missing.style.margin = "4px 0 8px";
      missing.textContent = `Ausente em: ${group.missing_from.join(", ")}`;
      card.appendChild(missing);
    }

    const table = document.createElement("table");
    table.className = "docs-table";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    headRow.appendChild(document.createElement("th"));
    for (const label of Object.values(DOCS_FIELD_LABELS)) {
      const th = document.createElement("th");
      th.textContent = label;
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const person of group.people) {
      const tr = document.createElement("tr");

      const tdDoc = document.createElement("td");
      tdDoc.textContent = person._doc;
      if (person.ocr) {
        const tag = document.createElement("span");
        tag.className = "docs-ocr-tag";
        tag.textContent = "(OCR)";
        tdDoc.appendChild(tag);
      }
      tr.appendChild(tdDoc);

      for (const field of Object.keys(DOCS_FIELD_LABELS)) {
        const td = document.createElement("td");
        let value = person[field];
        if (field === "dob_iso" && !value && person.dob_raw) {
          value = `${person.dob_raw} (?)`;
        }
        td.textContent = value || "—";
        if (group.mismatched_fields.includes(field)) {
          td.classList.add("field-mismatch");
        }
        tr.appendChild(td);
      }

      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    card.appendChild(table);

    $docsComparacao.appendChild(card);
  }

  $docsResultados.classList.remove("hidden");
}

function setRelatorioStatus(msg, isError = false) {
  $relatorioStatus.textContent = msg;
  $relatorioStatus.classList.toggle("error", isError);
}

async function gerarRelatorio() {
  if (!lastBriefingResult && !lastDocsResult) {
    setRelatorioStatus(
      "Rode a leitura do briefing e/ou a comparação de documentos antes de gerar o relatório.",
      true
    );
    return;
  }

  $btnRelatorio.disabled = true;
  setRelatorioStatus("Gerando PDF...");

  try {
    const resp = await fetch(`${API_BASE}/api/report/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ briefing: lastBriefingResult, travel_docs: lastDocsResult }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Erro ${resp.status}`);
    }

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "flightops-relatorio.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setRelatorioStatus("");
  } catch (err) {
    setRelatorioStatus(`Erro: ${err.message}`, true);
  } finally {
    $btnRelatorio.disabled = false;
  }
}

$icao.addEventListener("input", () => {
  $icao.value = $icao.value.toUpperCase();
});

$btn.addEventListener("click", analisar);
$btnBriefing.addEventListener("click", analisarBriefing);
$btnDocs.addEventListener("click", compararDocumentos);
$btnRelatorio.addEventListener("click", gerarRelatorio);
$eventsMesSelect.addEventListener("change", () => {
  if (lastEventsData) renderCalendar(lastEventsData.calendar, $eventsMesSelect.value);
});
carregarSugestoes();
