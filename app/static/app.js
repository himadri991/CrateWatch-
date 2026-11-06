const tokenMeta = document.querySelector('meta[name="cratewatch-token"]');
const demoMeta = document.querySelector('meta[name="cratewatch-demo"]');
const adminToken = tokenMeta ? tokenMeta.content : "";
const demoMode = demoMeta ? demoMeta.content === "true" : false;

const state = {
  fleet: null,
  incidents: [],
  sla: null,
  selectedCrate: "CW-01",
  connected: true,
};

const chart = document.getElementById("history-chart");
const chartEmpty = document.getElementById("chart-empty");
const crateSelect = document.getElementById("crate-select");
const incidentList = document.getElementById("incident-list");
const toast = document.getElementById("toast");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return Number(value).toFixed(digits);
}

function formatSeconds(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  if (value < 60) {
    return `${formatNumber(value, 1)} s`;
  }
  const minutes = value / 60;
  return `${formatNumber(minutes, 2)} min`;
}

function formatAge(isoString) {
  if (!isoString) {
    return "--";
  }
  const seconds = Math.max(0, (Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 60) {
    return `${Math.round(seconds)}s ago`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) {
    return `${minutes}m ${rest}s ago`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m ago`;
}

function statusClass(status) {
  return ["OK", "WARNING", "CRITICAL", "OFFLINE"].includes(status) ? status : "OFFLINE";
}

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (body.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch (error) {
      // keep the status message
    }
    throw new Error(detail);
  }
  return response.json();
}

function updateClock() {
  const now = new Date();
  document.getElementById("clock").textContent = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function updateKpis() {
  if (!state.sla) {
    return;
  }
  const observed = state.sla.observed;
  const availability = observed.availability_pct;
  document.getElementById("kpi-availability").textContent =
    availability === null ? "--" : `${formatNumber(availability, 2)}%`;
  document.getElementById("kpi-availability-foot").textContent =
    `${observed.samples_received} samples received, ${observed.samples_missing} missing`;

  document.getElementById("kpi-open").textContent = String(observed.open_incidents);
  document.getElementById("kpi-open-foot").textContent = `${observed.resolved_incidents} resolved in this session`;

  document.getElementById("kpi-alert").textContent = formatSeconds(observed.alert_latency_p95_seconds);
  const ttrSeconds = observed.ttr_s1_p95_seconds;
  document.getElementById("kpi-ttr").textContent =
    ttrSeconds === null ? "--" : `${formatNumber(ttrSeconds / 60, 2)} min`;
}

function renderCrates(crates) {
  const selectValue = state.selectedCrate;
  crateSelect.innerHTML = crates
    .map(
      (crate) =>
        `<option value="${escapeHtml(crate.id)}" ${crate.id === selectValue ? "selected" : ""}>${escapeHtml(
          crate.id
        )} - ${escapeHtml(crate.artwork)}</option>`
    )
    .join("");

  const grid = document.getElementById("crate-grid");
  grid.innerHTML = crates
    .map((crate) => {
      const reading = crate.reading;
      const status = statusClass(crate.status);
      const temp = reading ? `${formatNumber(reading.temp_c, 1)} C` : "--";
      const humidity = reading ? `${formatNumber(reading.humidity_pct, 1)}%` : "--";
      const shock = reading ? `${formatNumber(reading.shock_g, 2)} g` : "--";
      const battery = reading ? `${formatNumber(reading.battery_pct, 0)}%` : "--";
      const door = reading ? (reading.door_open ? "OPEN" : "CLOSED") : "--";
      const tempAlarm = reading && (reading.temp_c < 15 || reading.temp_c > 25) ? "alarm" : "";
      const humidityAlarm =
        reading && (reading.humidity_pct < 40 || reading.humidity_pct > 60) ? "alarm" : "";
      const shockAlarm = reading && reading.shock_g >= 8 ? "alarm" : "";
      const doorAlarm = reading && reading.door_open ? "alarm" : "";
      const incidentText =
        crate.open_incidents > 0
          ? `${crate.open_incidents} active`
          : reading
          ? `updated ${formatAge(reading.received_ts)}`
          : "no telemetry";

      return `
        <article class="crate-card ${crate.id === state.selectedCrate ? "selected" : ""}" data-crate="${escapeHtml(
          crate.id
        )}" role="button" tabindex="0" aria-pressed="${crate.id === state.selectedCrate}" aria-label="${escapeHtml(
          `${crate.id}, ${crate.artwork}, ${status}`
        )}">
          <div class="crate-top">
            <span class="crate-id">${escapeHtml(crate.id)}</span>
            <span class="status ${status}"><span class="dot"></span>${status}</span>
          </div>
          <div class="crate-art">${escapeHtml(crate.artwork)}</div>
          <div class="crate-sub">${escapeHtml(crate.medium)} | ${escapeHtml(crate.crate)}</div>
          <div class="reading-grid">
            <div class="reading">
              <div class="reading-label">Temp</div>
              <div class="reading-value ${tempAlarm}">${temp}</div>
            </div>
            <div class="reading">
              <div class="reading-label">Humidity</div>
              <div class="reading-value ${humidityAlarm}">${humidity}</div>
            </div>
            <div class="reading">
              <div class="reading-label">Shock</div>
              <div class="reading-value ${shockAlarm}">${shock}</div>
            </div>
            <div class="reading">
              <div class="reading-label">Door</div>
              <div class="reading-value ${doorAlarm}">${door}</div>
            </div>
          </div>
          <div class="crate-foot">
            <span>Battery ${battery}</span>
            <span class="${crate.open_incidents > 0 ? "incident-chip" : ""}">${incidentText}</span>
          </div>
        </article>
      `;
    })
    .join("");

  grid.querySelectorAll(".crate-card").forEach((card) => {
    const selectCrate = () => {
      state.selectedCrate = card.dataset.crate;
      crateSelect.value = state.selectedCrate;
      renderCrates(state.fleet ? state.fleet.crates : []);
      refreshChart();
    };

    card.addEventListener("click", selectCrate);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectCrate();
      }
    });
  });
}

function renderIncidents(incidents) {
  if (!incidents.length) {
    incidentList.innerHTML = '<div class="empty-state">No active incidents</div>';
    return;
  }

  incidentList.innerHTML = incidents
    .map((incident) => {
      const ackButton =
        incident.status === "OPEN"
          ? `<button type="button" data-action="ack" data-id="${incident.id}">Acknowledge</button>`
          : "";
      const resolveButton = `<button type="button" class="primary" data-action="resolve" data-id="${incident.id}">Resolve</button>`;
      const age = formatAge(incident.detected_at);
      return `
        <article class="incident-item ${escapeHtml(incident.severity)}">
          <div class="incident-head">
            <span class="severity ${escapeHtml(incident.severity)}">${escapeHtml(incident.severity)}</span>
            <span>${escapeHtml(incident.crate_id)}</span>
            <span>${escapeHtml(incident.status)}</span>
            <span style="margin-left:auto">${age}</span>
          </div>
          <div class="incident-title">${escapeHtml(incident.title)}</div>
          <div class="incident-meta">Threshold ${escapeHtml(incident.threshold || "")} | value ${formatNumber(
            incident.breach_value,
            2
          )}</div>
          <div class="incident-actions">
            ${ackButton}
            ${resolveButton}
          </div>
        </article>
      `;
    })
    .join("");
}

function slaValue(check, sla) {
  const observed = sla.observed;
  if (check === "availability") {
    return observed.availability_pct === null ? "--" : `${formatNumber(observed.availability_pct, 2)}%`;
  }
  if (check === "alert_latency") {
    return formatSeconds(observed.alert_latency_p95_seconds);
  }
  if (check === "api_latency") {
    return observed.api_latency_p95_ms === null ? "--" : `${formatNumber(observed.api_latency_p95_ms, 1)} ms`;
  }
  if (check === "ttr_s1") {
    return observed.ttr_s1_p95_seconds === null
      ? "--"
      : `${formatNumber(observed.ttr_s1_p95_seconds / 60, 2)} min`;
  }
  return observed.ingestion_delay_p95_seconds === null
    ? "--"
    : formatSeconds(observed.ingestion_delay_p95_seconds);
}

function renderSla(sla) {
  const pill = document.getElementById("overall-pill");
  pill.textContent = sla.overall.replaceAll("_", " ");
  pill.className = `overall-pill ${sla.overall}`;

  const labels = {
    availability: "Telemetry availability",
    alert_latency: "Alert latency P95",
    api_latency: "API latency P95",
    ttr_s1: "TTR P95, S1",
    ingestion_delay: "Ingestion delay P95",
  };
  const targets = {
    availability: "min 99.5%",
    alert_latency: "max 5 s",
    api_latency: "max 300 ms",
    ttr_s1: "max 15 min",
    ingestion_delay: "max 30 s",
  };

  document.getElementById("sla-table").innerHTML = Object.keys(labels)
    .map((key) => {
      const status = sla.checks[key] || "NO_DATA";
      return `
        <div class="sla-row">
          <span class="sla-name">${labels[key]}<br><small>target ${targets[key]}</small></span>
          <span class="sla-value">${slaValue(key, sla)}</span>
          <span class="sla-badge ${status}">${status.replaceAll("_", " ")}</span>
        </div>
      `;
    })
    .join("");
}

function drawChart(readings) {
  const context = chart.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const width = chart.clientWidth;
  const height = 240;
  chart.width = Math.max(1, Math.round(width * ratio));
  chart.height = Math.round(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);

  if (!readings || readings.length < 2) {
    chartEmpty.classList.add("show");
    return;
  }
  chartEmpty.classList.remove("show");

  const padding = { top: 18, right: 48, bottom: 26, left: 42 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const tempMin = 14;
  const tempMax = 28;
  const humidityMin = 30;
  const humidityMax = 70;

  const times = readings.map((reading) => new Date(reading.event_ts).getTime());
  const start = times[0];
  const end = times[times.length - 1];
  const span = Math.max(1, end - start);
  const xFor = (time) => padding.left + ((time - start) / span) * plotWidth;
  const yForTemp = (value) =>
    padding.top + (1 - (Math.min(tempMax, Math.max(tempMin, value)) - tempMin) / (tempMax - tempMin)) * plotHeight;
  const yForHumidity = (value) =>
    padding.top +
    (1 - (Math.min(humidityMax, Math.max(humidityMin, value)) - humidityMin) / (humidityMax - humidityMin)) *
      plotHeight;

  context.fillStyle = "rgba(40, 82, 118, 0.075)";
  const bandTop = yForTemp(25);
  const bandBottom = yForTemp(15);
  context.fillRect(padding.left, bandTop, plotWidth, bandBottom - bandTop);

  context.strokeStyle = "#e7e3db";
  context.lineWidth = 1;
  context.fillStyle = "#7b817f";
  context.font = '10px "SFMono-Regular", Menlo, monospace';
  context.textAlign = "right";
  context.textBaseline = "middle";

  [14, 17, 20, 23, 26, 28].forEach((value) => {
    const y = yForTemp(value);
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(padding.left + plotWidth, y);
    context.stroke();
    context.fillText(`${value}`, padding.left - 7, y);
  });

  context.textAlign = "left";
  [30, 40, 50, 60, 70].forEach((value) => {
    const y = yForHumidity(value);
    context.fillText(`${value}`, padding.left + plotWidth + 7, y);
  });

  context.lineWidth = 2;
  context.strokeStyle = "#285276";
  context.beginPath();
  readings.forEach((reading, index) => {
    const x = xFor(times[index]);
    const y = yForTemp(reading.temp_c);
    if (index === 0) {
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.stroke();

  context.lineWidth = 1.6;
  context.strokeStyle = "#a85734";
  context.beginPath();
  readings.forEach((reading, index) => {
    const x = xFor(times[index]);
    const y = yForHumidity(reading.humidity_pct);
    if (index === 0) {
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.stroke();

  const last = readings[readings.length - 1];
  const lastX = xFor(times[times.length - 1]);
  context.fillStyle = "#285276";
  context.beginPath();
  context.arc(lastX, yForTemp(last.temp_c), 3, 0, Math.PI * 2);
  context.fill();
  context.fillStyle = "#a85734";
  context.beginPath();
  context.arc(lastX, yForHumidity(last.humidity_pct), 2.7, 0, Math.PI * 2);
  context.fill();

  context.fillStyle = "#7b817f";
  context.textBaseline = "top";
  context.textAlign = "left";
  const firstLabel = new Date(times[0]).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const lastLabel = new Date(times[times.length - 1]).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  context.fillText(firstLabel, padding.left, height - padding.bottom + 8);
  context.textAlign = "right";
  context.fillText(lastLabel, padding.left + plotWidth, height - padding.bottom + 8);
}

async function refreshChart() {
  try {
    const data = await fetchJson(
      `/api/crates/${encodeURIComponent(state.selectedCrate)}/history?minutes=15&limit=180`
    );
    drawChart(data.readings);
  } catch (error) {
    chartEmpty.classList.add("show");
  }
}

async function refresh() {
  try {
    const [fleet, incidents, sla] = await Promise.all([
      fetchJson("/api/fleet"),
      fetchJson("/api/incidents?status=active&limit=30"),
      fetchJson("/api/sla"),
    ]);
    state.fleet = fleet;
    state.incidents = incidents.incidents;
    state.sla = sla;
    state.connected = true;
    renderCrates(fleet.crates);
    renderIncidents(incidents.incidents);
    renderSla(sla);
    updateKpis();
  } catch (error) {
    if (state.connected) {
      showToast("Connection to the CrateWatch API was lost", true);
      state.connected = false;
    }
  }
}

async function postIncidentAction(id, action) {
  try {
    const result = await fetchJson(`/api/incidents/${id}/${action}`, {
      method: "POST",
      body: JSON.stringify({ notes: `${action} from dashboard` }),
    });
    if (action === "resolve" && result.ttr_seconds !== null) {
      showToast(`Incident resolved. TTR ${formatSeconds(result.ttr_seconds)}`);
    } else {
      showToast(`Incident ${action === "ack" ? "acknowledged" : "resolved"}`);
    }
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function injectBreach(kind) {
  const crateByKind = {
    shock: "CW-03",
    heat: "CW-02",
    humidity: "CW-04",
    door: "CW-01",
    battery: "CW-05",
  };
  const crateId = crateByKind[kind] || state.selectedCrate;
  try {
    await fetchJson("/api/demo/breach", {
      method: "POST",
      headers: { "X-Admin-Token": adminToken },
      body: JSON.stringify({ crate_id: crateId, kind }),
    });
    showToast(`${kind} breach injected on ${crateId}`);
    await refresh();
    await refreshChart();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function resetDemo() {
  const confirmed = window.confirm("Clear all telemetry and incidents for this demo?");
  if (!confirmed) {
    return;
  }
  try {
    await fetchJson("/api/demo/reset", {
      method: "POST",
      headers: { "X-Admin-Token": adminToken },
      body: "{}",
    });
    showToast("Demo data cleared");
    await refresh();
    await refreshChart();
  } catch (error) {
    showToast(error.message, true);
  }
}

incidentList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }
  postIncidentAction(button.dataset.id, button.dataset.action);
});

crateSelect.addEventListener("change", () => {
  state.selectedCrate = crateSelect.value;
  renderCrates(state.fleet ? state.fleet.crates : []);
  refreshChart();
});

document.getElementById("refresh-button").addEventListener("click", () => {
  refresh();
  refreshChart();
});

if (demoMode) {
  document.querySelectorAll("[data-breach]").forEach((button) => {
    button.addEventListener("click", () => injectBreach(button.dataset.breach));
  });
  document.getElementById("reset-button").addEventListener("click", resetDemo);
} else {
  const panel = document.getElementById("demo-panel");
  if (panel) {
    panel.style.display = "none";
  }
}

window.addEventListener("resize", () => {
  if (state.fleet) {
    refreshChart();
  }
});

updateClock();
setInterval(updateClock, 1000);
refresh();
refreshChart();
setInterval(refresh, 2000);
setInterval(refreshChart, 3000);
