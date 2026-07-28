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
const $btnBriefing = document.getElementById("analisar-briefing");
const $briefingStatus = document.getElementById("briefing-status");
const $briefingResultados = document.getElementById("briefing-resultados");
const $briefingWeather = document.getElementById("briefing-weather");
const $briefingNotamResumo = document.getElementById("briefing-notam-resumo");
const $briefingNotams = document.getElementById("briefing-notams");

let chartCategorias, chartMes, chartHora;

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
  setStatus(`Buscando histórico METAR de ${icao} (${periodoLabel(periodo)})...`);

  // ATIS é só um complemento (só existe pra parte dos aeroportos dos EUA) —
  // buscamos em paralelo e nunca deixamos ele travar a análise principal.
  buscarAtis(icao);

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

    const resp = await fetch(`${API_BASE}/api/briefing/upload`, {
      method: "POST",
      body: formData,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Erro ${resp.status}`);
    }

    const data = await resp.json();
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

$icao.addEventListener("input", () => {
  $icao.value = $icao.value.toUpperCase();
});

$btn.addEventListener("click", analisar);
$btnBriefing.addEventListener("click", analisarBriefing);
carregarSugestoes();
