const API_DATA = "/api/data";
const API_REFRESH = "/api/refresh";
const API_REFRESH_STATUS = "/api/refresh_status";

const state = {
  rows: [],
  nodes: [],
  nodeMeta: {},
  groupedEdges: [],
  network: null,
  edgeById: new Map(),
  poller: null,
};

const els = {
  meta: document.getElementById("meta"),
  graph: document.getElementById("graph"),
  refreshBtn: document.getElementById("refresh-btn"),
  nodeSearchInput: document.getElementById("node-search-input"),
  nodeSearchBtn: document.getElementById("node-search-btn"),
  statusText: document.getElementById("status-text"),
  statusLog: document.getElementById("status-log"),
  insights: document.getElementById("insights"),
  sectorLegend: document.getElementById("sector-legend"),
  edgeDetails: document.getElementById("edge-details"),
  closeDetails: document.getElementById("close-details"),
  detailsContent: document.getElementById("details-content"),
};

const SECTOR_COLORS = {
  general_ecommerce: "#2563eb",
  specialized_ecommerce: "#0ea5e9",
  aggregator: "#06b6d4",
  travel_agency: "#14b8a6",
  qa_platform: "#8b5cf6",
  ai: "#6366f1",
  payments: "#22c55e",
  enabler: "#f59e0b",
  enterprise_software: "#f97316",
  logistics_fulfillment: "#ef4444",
  social_commerce: "#ec4899",
};

function esc(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function groupEdges(rows) {
  const map = new Map();
  for (const r of rows) {
    const src = r.source_actor;
    const tgt = r.target_actor;
    const t = r.relationship_type;
    if (!src || !tgt || !t) continue;
    const key = `${src}|${tgt}|${t}`;
    if (!map.has(key)) {
      map.set(key, { id: key, source: src, target: tgt, type: t, sources: [] });
    }
    map.get(key).sources.push({
      date: r.announcement_date || "",
      title: r.source_title || "",
      url: r.source_url || "",
      publisher: r.publisher || "",
    });
  }
  return Array.from(map.values());
}

function edgeColor(type) {
  const palette = {
    acquires: "#e11d48",
    partners_with: "#2563eb",
    integrates_with: "#7c3aed",
    uses_services_of: "#0f766e",
    powers: "#ea580c",
    invests_in: "#16a34a",
  };
  return palette[type] || "#95a4bd";
}

function sectorLabel(sector) {
  const labels = {
    general_ecommerce: "General e-commerce",
    specialized_ecommerce: "Specialized e-commerce",
    aggregator: "Aggregator",
    travel_agency: "Travel agency",
    qa_platform: "Q&A platform",
    ai: "AI",
    payments: "Payments",
    enabler: "Technology enabler",
    enterprise_software: "Enterprise software",
    logistics_fulfillment: "Logistics & fulfillment",
    social_commerce: "Social commerce",
  };
  return labels[sector] || "Technology enabler";
}

function typeLabel(meta) {
  const sector = meta && meta.sector;
  if (sector === "ai") return "AI company";
  if (meta && meta.is_ecommerce) return "E-commerce company";
  if (sector === "payments") return "Payments / fintech company";
  if (sector === "qa_platform") return "Q&A platform";
  if (sector === "travel_agency") return "Travel platform";
  if (sector === "enabler") return "Technology enabler";
  if (sector === "enterprise_software") return "Enterprise software company";
  if (sector === "logistics_fulfillment") return "Logistics / fulfillment company";
  if (sector === "social_commerce") return "Social commerce company";
  return "Technology enabler";
}

function sectorColor(sector) {
  return SECTOR_COLORS[sector] || SECTOR_COLORS.enabler;
}

function renderSectorLegend() {
  if (!els.sectorLegend) return;
  const used = new Set();
  for (const n of state.nodes) {
    const sector = (state.nodeMeta[n] && state.nodeMeta[n].sector) || "enabler";
    used.add(sector in SECTOR_COLORS ? sector : "enabler");
  }
  const html = Array.from(used)
    .sort((a, b) => sectorLabel(a).localeCompare(sectorLabel(b)))
    .map((sector) => `<div><span class="dot" style="background:${sectorColor(sector)}"></span> ${esc(sectorLabel(sector))}</div>`)
    .join("");
  els.sectorLegend.innerHTML = html || `<div><span class="dot" style="background:${sectorColor("enabler")}"></span> Technology enabler</div>`;
}

function renderInsights() {
  const degree = new Map();
  for (const e of state.groupedEdges) {
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
  }

  const bySector = new Map();
  for (const n of state.nodes) {
    const sector = (state.nodeMeta[n] && state.nodeMeta[n].sector) || "enabler";
    if (!bySector.has(sector)) bySector.set(sector, { count: 0, linked: 0 });
    const row = bySector.get(sector);
    row.count += 1;
    if ((degree.get(n) || 0) > 0) row.linked += 1;
  }
  const sectorLines = Array.from(bySector.entries())
    .sort((a, b) => b[1].count - a[1].count)
    .slice(0, 5)
    .map(([k, v]) => `${sectorLabel(k)}: ${v.linked}/${v.count} connected`)
    .join(" • ");
  els.insights.textContent = `Market insight view by sector (connected/total): ${sectorLines || "No sectors yet."}`;
}

function drawGraph() {
  const nodeSet = new Set(state.nodes);
  const degree = new Map();
  for (const e of state.groupedEdges) {
    nodeSet.add(e.source);
    nodeSet.add(e.target);
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
  }

  const nodes = Array.from(nodeSet).map((name) => {
    const d = degree.get(name) || 0;
    const meta = state.nodeMeta[name] || {};
    const sector = meta.sector || "enabler";
    const base = sectorColor(sector);
    return {
      id: name,
      label: name,
      value: Math.max(9, d * 5),
      color: {
        background: base,
        border: "#ffffff",
      },
      font: { color: "#334155", size: d > 0 ? 15 : 13, strokeWidth: 3, strokeColor: "#ffffff" },
    };
  });

  const edges = state.groupedEdges.map((e) => ({
    id: e.id,
    from: e.source,
    to: e.target,
    arrows: "to",
    label: e.type.replaceAll("_", " "),
    width: Math.min(1 + e.sources.length * 0.4, 4),
    color: { color: edgeColor(e.type), highlight: edgeColor(e.type) },
    font: { color: edgeColor(e.type), size: 10, strokeWidth: 0, align: "top" },
  }));

  state.edgeById = new Map(state.groupedEdges.map((e) => [e.id, e]));
  if (state.network) state.network.destroy();
  state.network = new vis.Network(
    els.graph,
    { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) },
    {
      interaction: { hover: true, dragNodes: true, dragView: true, zoomView: true },
      physics: {
        stabilization: { enabled: true, iterations: 600, fit: true },
        barnesHut: {
          springLength: 210,
          springConstant: 0.012,
          gravitationalConstant: -8200,
          damping: 0.16,
          avoidOverlap: 1,
        },
      },
      layout: {
        improvedLayout: true,
        randomSeed: 7,
      },
      nodes: {
        shape: "dot",
        borderWidth: 1.2,
        scaling: { min: 16, max: 34, label: { enabled: true, min: 13, max: 24 } },
      },
      edges: {
        selectionWidth: 2.4,
        smooth: { type: "dynamic", roundness: 0.25 },
        length: 230,
      },
    }
  );
  state.network.on("click", onGraphClick);
  els.meta.textContent = `${nodes.length} companies • ${edges.length} explicit connections`;
  renderInsights();
  renderSectorLegend();
}

function onGraphClick(params) {
  if (params.nodes && params.nodes.length > 0) {
    const nodeName = params.nodes[0];
    const connected = state.groupedEdges.filter((e) => e.source === nodeName || e.target === nodeName);
    const meta = state.nodeMeta[nodeName] || {};
    const lines = connected
      .map((e) => {
        const other = e.source === nodeName ? e.target : e.source;
        const sourceItems = e.sources
          .map(
            (s) => `
            <div class="source-item">
              <div>${esc(s.date)} • ${esc(s.publisher)}</div>
              <strong>${esc(s.title)}</strong>
              <div><a href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.url)}</a></div>
            </div>`
          )
          .join("");
        return `
          <details class="node-connection">
            <summary class="node-connection-summary">
              <span><strong>${esc(other)}</strong> — ${esc(e.type.replaceAll("_", " "))}</span>
              <span class="source-count">${e.sources.length} source${e.sources.length === 1 ? "" : "s"}</span>
            </summary>
            <div class="node-connection-body">
              ${sourceItems || "<p>No sources.</p>"}
            </div>
          </details>
        `;
      })
      .join("");
    els.detailsContent.innerHTML = `
      <h3>${esc(nodeName)}</h3>
      <p>Sector: ${esc(sectorLabel(meta.sector || "enabler"))}</p>
      <p>Type: ${esc(typeLabel(meta))}</p>
      <p>Connected nodes: ${connected.length}</p>
      <div class="node-connections">${lines || "<p>No direct connections yet.</p>"}</div>
    `;
    els.edgeDetails.classList.remove("hidden");
    return;
  }

  if (!params.edges || params.edges.length === 0) return;
  const edge = state.edgeById.get(params.edges[0]);
  if (!edge) return;
  const html = edge.sources
    .map(
      (s) => `
      <div class="source-item">
        <div>${esc(s.date)} • ${esc(s.publisher)}</div>
        <strong>${esc(s.title)}</strong>
        <div><a href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.url)}</a></div>
      </div>`
    )
    .join("");
  els.detailsContent.innerHTML = `
    <h3>${esc(edge.source)} → ${esc(edge.target)}</h3>
    <p>Relationship type: <strong>${esc(edge.type)}</strong></p>
    ${html || "<p>No sources.</p>"}
  `;
  els.edgeDetails.classList.remove("hidden");
}

function focusNode() {
  const q = (els.nodeSearchInput.value || "").trim().toLowerCase();
  if (!q || !state.network) return;
  const exact = state.nodes.find((n) => n.toLowerCase() === q);
  const partial = state.nodes.find((n) => n.toLowerCase().includes(q));
  const target = exact || partial;
  if (!target) {
    els.meta.textContent = `No node match for "${q}"`;
    return;
  }
  state.network.selectNodes([target]);
  state.network.focus(target, { scale: 1.15, animation: { duration: 500, easingFunction: "easeInOutQuad" } });
}

async function loadData() {
  const res = await fetch(`${API_DATA}?t=${Date.now()}`);
  if (!res.ok) throw new Error(`Data load failed (${res.status})`);
  const payload = await res.json();
  state.rows = payload.rows || [];
  state.nodes = payload.nodes || [];
  state.nodeMeta = payload.node_meta || {};
  state.groupedEdges = groupEdges(state.rows);
  drawGraph();
}

async function pollStatus() {
  const res = await fetch(`${API_REFRESH_STATUS}?t=${Date.now()}`);
  if (!res.ok) return;
  const s = await res.json();
  els.statusLog.textContent = s.log_tail || "No log output yet.";
  if (s.running) {
    els.statusText.textContent = "Running...";
    return;
  }
  if (s.exit_code === 0) {
    els.statusText.textContent = "Completed";
    if (state.poller) {
      clearInterval(state.poller);
      state.poller = null;
    }
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = "Refresh with LLM";
    await loadData();
    return;
  }
  if (s.exit_code === 1) {
    els.statusText.textContent = "Failed";
    if (state.poller) {
      clearInterval(state.poller);
      state.poller = null;
    }
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = "Refresh with LLM";
    return;
  }
  els.statusText.textContent = "Idle";
}

async function refresh() {
  els.refreshBtn.disabled = true;
  els.refreshBtn.textContent = "Refreshing...";
  const res = await fetch(API_REFRESH, { method: "POST" });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = "Refresh with LLM";
    const msg = payload.detail || payload.error || "Refresh request failed.";
    els.statusText.textContent = "Failed";
    els.statusLog.textContent = msg;
    alert(msg);
    return;
  }
  els.statusText.textContent = "Starting...";
  els.statusLog.textContent = payload.message || "Refresh started.";
  if (state.poller) clearInterval(state.poller);
  await pollStatus();
  state.poller = setInterval(() => {
    pollStatus().catch(() => {});
  }, 1500);
}

function attachEvents() {
  els.refreshBtn.addEventListener("click", () => refresh().catch((e) => alert(String(e))));
  els.closeDetails.addEventListener("click", () => els.edgeDetails.classList.add("hidden"));
  els.nodeSearchBtn.addEventListener("click", focusNode);
  els.nodeSearchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") focusNode();
  });
}

async function init() {
  attachEvents();
  await loadData();
  await pollStatus();
}

init().catch((e) => {
  els.meta.textContent = `Error: ${e.message}`;
});
