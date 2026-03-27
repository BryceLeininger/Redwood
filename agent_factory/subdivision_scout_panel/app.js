const elements = {
  agentSelect: document.getElementById("agentSelect"),
  agentMeta: document.getElementById("agentMeta"),
  resultsMeta: document.getElementById("resultsMeta"),
  loadSamplesBtn: document.getElementById("loadSamplesBtn"),
  refreshAgentsBtn: document.getElementById("refreshAgentsBtn"),
  samplePromptBtn: document.getElementById("samplePromptBtn"),
  sampleSingleBtn: document.getElementById("sampleSingleBtn"),
  sampleCsvBtn: document.getElementById("sampleCsvBtn"),
  sampleWatchBtn: document.getElementById("sampleWatchBtn"),
  promptSearchBtn: document.getElementById("promptSearchBtn"),
  screenTextBtn: document.getElementById("screenTextBtn"),
  screenCsvBtn: document.getElementById("screenCsvBtn"),
  watchBtn: document.getElementById("watchBtn"),
  fullSweepBtn: document.getElementById("fullSweepBtn"),
  promptSearchInput: document.getElementById("promptSearchInput"),
  promptLookbackInput: document.getElementById("promptLookbackInput"),
  promptMaxResultsInput: document.getElementById("promptMaxResultsInput"),
  parcelIdInput: document.getElementById("parcelIdInput"),
  marketInput: document.getElementById("marketInput"),
  singleParcelInput: document.getElementById("singleParcelInput"),
  topInput: document.getElementById("topInput"),
  minScoreInput: document.getElementById("minScoreInput"),
  csvInput: document.getElementById("csvInput"),
  lookbackInput: document.getElementById("lookbackInput"),
  maxResultsInput: document.getElementById("maxResultsInput"),
  watchlistInput: document.getElementById("watchlistInput"),
  csvFileInput: document.getElementById("csvFileInput"),
  watchFileInput: document.getElementById("watchFileInput"),
  statusPill: document.getElementById("statusPill"),
  summaryCards: document.getElementById("summaryCards"),
  resultBody: document.getElementById("resultBody"),
};

const state = {
  agents: [],
  defaultAgentDir: null,
  sampleSearchPrompt: "",
  sampleSingleParcelText: "",
  sampleParcelCsv: "",
  sampleWatchlist: "",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function selectedAgentDir() {
  return elements.agentSelect.value || null;
}

function selectedAgent() {
  return state.agents.find((agent) => agent.agent_dir === selectedAgentDir()) || state.agents[0] || null;
}

function selectedAgentName() {
  return selectedAgent()?.name || "ResidentialSubdivisionScout";
}

function formatDateTime(value) {
  if (!value) {
    return "unknown";
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatRunTime() {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date());
}

function setResultsMeta(text) {
  if (elements.resultsMeta) {
    elements.resultsMeta.textContent = text;
  }
}

function setStatus(text, tone = "idle") {
  elements.statusPill.textContent = text;
  elements.statusPill.className = `status-pill ${tone}`;
}

function setBusy(isBusy) {
  [
    elements.loadSamplesBtn,
    elements.refreshAgentsBtn,
    elements.samplePromptBtn,
    elements.sampleSingleBtn,
    elements.sampleCsvBtn,
    elements.sampleWatchBtn,
    elements.promptSearchBtn,
    elements.screenTextBtn,
    elements.screenCsvBtn,
    elements.watchBtn,
    elements.fullSweepBtn,
    elements.agentSelect,
    elements.csvFileInput,
    elements.watchFileInput,
  ].forEach((node) => {
    node.disabled = isBusy;
  });
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch (error) {
      detail = await response.text();
    }
    throw new Error(detail || `Request failed with status ${response.status}`);
  }
  return response.json();
}

function populateAgents(agents, defaultAgentDir) {
  state.agents = Array.isArray(agents) ? agents : [];
  state.defaultAgentDir = defaultAgentDir || null;

  elements.agentSelect.innerHTML = "";

  if (!state.agents.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No ResidentialSubdivisionScout found";
    elements.agentSelect.appendChild(option);
    elements.agentMeta.textContent =
      "Create the agent first with `python -m agent_factory.cli create-agent ...` or use the bootstrap helper.";
    setResultsMeta("No scout agents were found. Create one first, then refresh the registry.");
    return;
  }

  state.agents.forEach((agent) => {
    const option = document.createElement("option");
    option.value = agent.agent_dir || "";
    option.textContent = agent.created_at_utc
      ? `${agent.name} | ${agent.created_at_utc.slice(0, 10)}`
      : agent.name || agent.agent_dir;
    if (agent.agent_dir === state.defaultAgentDir) {
      option.selected = true;
    }
    elements.agentSelect.appendChild(option);
  });

  updateAgentMeta();
}

function updateAgentMeta() {
  const current = selectedAgent();
  if (!current) {
    elements.agentMeta.textContent = "No agent selected.";
    return;
  }

  const metricValue =
    typeof current.metric_value === "number" ? current.metric_value.toFixed(2) : current.metric_value ?? "n/a";
  const metricName = current.metric_name || "metric";
  const created = formatDateTime(current.created_at_utc);
  elements.agentMeta.textContent = `${metricName}: ${metricValue} | created ${created}`;
}

function loadSamplesIntoFields() {
  elements.promptSearchInput.value = state.sampleSearchPrompt;
  elements.singleParcelInput.value = state.sampleSingleParcelText;
  elements.csvInput.value = state.sampleParcelCsv;
  elements.watchlistInput.value = state.sampleWatchlist;
  setResultsMeta("Sample prompt, parcel notes, CSV, and watchlist loaded into the workspace.");
}

function renderSummary(cards) {
  if (!cards.length) {
    elements.summaryCards.innerHTML = "";
    return;
  }

  elements.summaryCards.innerHTML = cards
    .map(
      (card) => `
        <article class="summary-card">
          <p class="summary-label">${escapeHtml(card.label)}</p>
          <p class="summary-value">${escapeHtml(card.value)}</p>
          ${card.note ? `<p class="summary-note">${escapeHtml(card.note)}</p>` : ""}
        </article>
      `
    )
    .join("");
}

function renderRawResponse(payload) {
  return `
    <details class="raw-response">
      <summary>View raw response</summary>
      <pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    </details>
  `;
}

function recommendationClass(recommendation) {
  if (recommendation === "watch") {
    return "watch";
  }
  if (recommendation === "pass") {
    return "pass";
  }
  return "prioritize";
}

function renderParcelCard(result) {
  const positives = Array.isArray(result.positive_signals) ? result.positive_signals : [];
  const risks = Array.isArray(result.risk_signals) ? result.risk_signals : [];

  return `
    <article class="result-card">
      <div class="result-card-header">
        <div>
          <h3 class="card-title">${escapeHtml(result.parcel_id || "parcel")}</h3>
          <div class="meta-row">
            <span>${escapeHtml(result.market || "unknown market")}</span>
            <span>${escapeHtml((result.model_prediction || "").replaceAll("_", " "))}</span>
          </div>
        </div>
        <div class="score-pill ${recommendationClass(result.recommendation)}">
          ${escapeHtml(result.recommendation || "watch")} | ${escapeHtml(result.priority_score ?? "n/a")}
        </div>
      </div>

      <p class="rationale">${escapeHtml(result.rationale || "")}</p>

      ${
        positives.length
          ? `<div class="tag-row">${positives
              .slice(0, 6)
              .map((item) => `<span class="tag positive">${escapeHtml(item)}</span>`)
              .join("")}</div>`
          : ""
      }

      ${
        risks.length
          ? `<div class="tag-row">${risks
              .slice(0, 6)
              .map((item) => `<span class="tag risk">${escapeHtml(item)}</span>`)
              .join("")}</div>`
          : ""
      }

      <p class="source-text">${escapeHtml(result.source_text || "")}</p>
    </article>
  `;
}

function renderWatchStage(title, stageClass, items) {
  const rows = Array.isArray(items) ? items : [];
  return `
    <article class="section-card">
      <div class="watch-stage-header">
        <h3>${escapeHtml(title)}</h3>
        <span class="tag ${stageClass}">${rows.length} hit${rows.length === 1 ? "" : "s"}</span>
      </div>
      ${
        rows.length
          ? `<div class="watch-list">${rows
              .map(
                (item) => `
                  <article class="watch-card">
                    <div class="watch-card-header">
                      <div>
                        <h4 class="card-title">${escapeHtml(item.title || "Untitled item")}</h4>
                        <div class="meta-row">
                          <span>${escapeHtml(item.jurisdiction || "")}</span>
                          <span>${escapeHtml(item.source_domain || "")}</span>
                        </div>
                      </div>
                      <span class="tag ${stageClass}">${escapeHtml(item.stage || "")}</span>
                    </div>
                    <p class="rationale">${escapeHtml(item.snippet || "")}</p>
                    <div class="watch-meta">
                      <span>${escapeHtml(item.published_at ? new Date(item.published_at).toLocaleString() : "Undated source")}</span>
                      <span>${escapeHtml(item.matched_query || "")}</span>
                    </div>
                    <div class="tag-row">
                      <a class="watch-link" href="${escapeHtml(item.url || "#")}" target="_blank" rel="noreferrer">Open source</a>
                    </div>
                  </article>
                `
              )
              .join("")}</div>`
          : `<article class="empty-state"><p class="empty-title">No matches returned.</p><p>Try expanding the watchlist or increasing the lookback window.</p></article>`
      }
    </article>
  `;
}

function renderInterpretationCard(spec) {
  const requestedAreas = Array.isArray(spec.requested_areas) ? spec.requested_areas : [];
  const searchAreas = Array.isArray(spec.search_areas) ? spec.search_areas : [];
  const stages = Array.isArray(spec.stages) ? spec.stages : [];

  return `
    <article class="interpretation-card">
      <div class="watch-stage-header">
        <h3>Interpreted Search</h3>
        <span class="tag">${escapeHtml(spec.housing_type || "residential")}</span>
      </div>
      <div class="tag-row">
        ${requestedAreas.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}
      </div>
      <div class="meta-row">
        <span>Expanded search areas: ${escapeHtml(searchAreas.join(", ") || "n/a")}</span>
        <span>Min acres: ${escapeHtml(spec.min_acres ?? "n/a")}</span>
        <span>Min lots: ${escapeHtml(spec.min_lots ?? "n/a")}</span>
      </div>
      <div class="tag-row">
        ${stages.map((item) => `<span class="tag">${escapeHtml(item.replaceAll("_", " "))}</span>`).join("")}
      </div>
    </article>
  `;
}

function renderSearchResultCard(item) {
  const notes = Array.isArray(item.qualification_notes) ? item.qualification_notes : [];
  const stageClass = item.stage === "approved_recently" ? "stage-approved" : "stage-upcoming";
  const qualificationClass = item.qualification === "qualified" ? "positive" : "risk";

  return `
    <article class="watch-card">
      <div class="watch-card-header">
        <div>
          <h4 class="card-title">${escapeHtml(item.title || "Untitled item")}</h4>
          <div class="meta-row">
            <span>${escapeHtml(item.requested_area || "")}</span>
            <span>${escapeHtml(item.search_area || "")}</span>
            <span>${escapeHtml(item.source_domain || "")}</span>
          </div>
        </div>
        <div class="tag-row">
          <span class="tag ${stageClass}">${escapeHtml(item.stage || "")}</span>
          <span class="tag ${qualificationClass}">${escapeHtml(item.qualification || "")}</span>
          <span class="tag">Score ${escapeHtml(item.score ?? "n/a")}</span>
        </div>
      </div>

      <p class="rationale">${escapeHtml(item.snippet || "")}</p>

      <div class="meta-row">
        <span>Acres: ${escapeHtml(item.extracted_acres ?? "not found")}</span>
        <span>Lots: ${escapeHtml(item.extracted_lots ?? "not found")}</span>
        <span>${escapeHtml(item.published_at ? new Date(item.published_at).toLocaleString() : "Undated source")}</span>
      </div>

      ${
        notes.length
          ? `<div class="tag-row">${notes.map((note) => `<span class="tag">${escapeHtml(note)}</span>`).join("")}</div>`
          : ""
      }

      <div class="tag-row">
        <a class="watch-link" href="${escapeHtml(item.url || "#")}" target="_blank" rel="noreferrer">Open source</a>
      </div>
    </article>
  `;
}

function renderPromptSearch(payload) {
  const qualified = Array.isArray(payload.qualified_results) ? payload.qualified_results : [];
  const review = Array.isArray(payload.review_results) ? payload.review_results : [];
  const interpreted = payload.interpreted_search || {};

  renderSummary([
    {
      label: "Requested Areas",
      value: Array.isArray(interpreted.requested_areas) ? interpreted.requested_areas.length : 0,
      note: Array.isArray(interpreted.requested_areas) ? interpreted.requested_areas.join(", ") : "",
    },
    { label: "Qualified Results", value: qualified.length, note: "Matches the parsed thresholds" },
    { label: "Needs Review", value: review.length, note: "Stage matched but acreage or lots need confirmation" },
    {
      label: "Filters",
      value: `${interpreted.min_acres ?? "?"} ac / ${interpreted.min_lots ?? "?"} lots`,
      note: (interpreted.housing_type || "residential").replaceAll("_", " "),
    },
  ]);

  const qualifiedSection = qualified.length
    ? `<article class="section-card"><div class="watch-stage-header"><h3>Qualified Results</h3><span class="tag positive">${qualified.length} hit${qualified.length === 1 ? "" : "s"}</span></div>${qualified
        .map(renderSearchResultCard)
        .join("")}</article>`
    : `<article class="empty-state"><p class="empty-title">No fully qualified matches yet.</p><p>Try widening the areas, reducing the thresholds, or increasing the lookback window.</p></article>`;

  const reviewSection = review.length
    ? `<article class="section-card"><div class="watch-stage-header"><h3>Needs Review</h3><span class="tag risk">${review.length} hit${review.length === 1 ? "" : "s"}</span></div>${review
        .map(renderSearchResultCard)
        .join("")}</article>`
    : "";

  elements.resultBody.innerHTML = `
    ${renderInterpretationCard(interpreted)}
    ${qualifiedSection}
    ${reviewSection}
    ${renderRawResponse(payload)}
  `;
}

function renderScreenText(payload) {
  const result = payload.result;
  renderSummary([
    { label: "Recommendation", value: result.recommendation || "n/a", note: result.model_prediction || "" },
    { label: "Priority Score", value: result.priority_score ?? "n/a", note: result.market || "" },
    {
      label: "Positive Signals",
      value: Array.isArray(result.positive_signals) ? result.positive_signals.length : 0,
      note: "Matched parcel upside markers",
    },
    {
      label: "Risk Signals",
      value: Array.isArray(result.risk_signals) ? result.risk_signals.length : 0,
      note: "Entitlement and infrastructure flags",
    },
  ]);

  elements.resultBody.innerHTML = `${renderParcelCard(result)}${renderRawResponse(payload)}`;
}

function renderScreenCsv(payload) {
  const results = Array.isArray(payload.results) ? payload.results : [];
  const prioritized = results.filter((item) => item.recommendation === "prioritize").length;
  const watchCount = results.filter((item) => item.recommendation === "watch").length;

  renderSummary([
    { label: "Rows Returned", value: results.length, note: "After top and score filters" },
    { label: "Prioritize", value: prioritized, note: "High conviction parcels" },
    { label: "Watch", value: watchCount, note: "Needs more diligence" },
    {
      label: "Top Score",
      value: results.length ? results[0].priority_score : 0,
      note: results.length ? results[0].parcel_id : "No parcels met the filter",
    },
  ]);

  elements.resultBody.innerHTML = results.length
    ? `${results.map(renderParcelCard).join("")}${renderRawResponse(payload)}`
    : `<article class="empty-state"><p class="empty-title">No parcels matched the filter.</p><p>Lower the minimum score or increase the top count.</p></article>${renderRawResponse(
        payload
      )}`;
}

function renderWatch(payload) {
  const approved = Array.isArray(payload.approved_recently) ? payload.approved_recently : [];
  const upcoming = Array.isArray(payload.approaching_approval) ? payload.approaching_approval : [];

  renderSummary([
    { label: "Jurisdictions", value: Array.isArray(payload.jurisdictions) ? payload.jurisdictions.length : 0 },
    { label: "Approved Recently", value: approved.length, note: "Recent tentative map approvals" },
    { label: "Approaching Approval", value: upcoming.length, note: "Agenda and hearing-stage items" },
    { label: "Lookback Days", value: payload.lookback_days ?? "n/a", note: "Current watch window" },
  ]);

  elements.resultBody.innerHTML = `
    ${renderWatchStage("Approved Recently", "stage-approved", approved)}
    ${renderWatchStage("Approaching Approval", "stage-upcoming", upcoming)}
    ${renderRawResponse(payload)}
  `;
}

function renderFullSweep(payload) {
  const parcels = Array.isArray(payload.screened_parcels) ? payload.screened_parcels : [];
  const planningActivity = payload.planning_activity || null;
  const approved = Array.isArray(planningActivity?.approved_recently) ? planningActivity.approved_recently : [];
  const upcoming = Array.isArray(planningActivity?.approaching_approval) ? planningActivity.approaching_approval : [];

  renderSummary([
    { label: "Screened Parcels", value: parcels.length, note: "Returned after score filtering" },
    { label: "Prioritize", value: parcels.filter((item) => item.recommendation === "prioritize").length },
    { label: "Approved Hits", value: approved.length, note: "Recent approvals from the watch" },
    { label: "Upcoming Hits", value: upcoming.length, note: "Near-term hearing activity" },
  ]);

  const parcelSection = parcels.length
    ? `<article class="section-card"><div class="watch-stage-header"><h3>Ranked Parcels</h3><span class="tag">${parcels.length} parcel${parcels.length === 1 ? "" : "s"}</span></div>${parcels
        .map(renderParcelCard)
        .join("")}</article>`
    : `<article class="empty-state"><p class="empty-title">No parcels returned.</p><p>Add a parcel feed or lower the minimum score threshold.</p></article>`;

  const planningSection = planningActivity
    ? `
      ${renderWatchStage("Approved Recently", "stage-approved", approved)}
      ${renderWatchStage("Approaching Approval", "stage-upcoming", upcoming)}
    `
    : `<article class="empty-state"><p class="empty-title">Planning watch not included.</p><p>Paste a watchlist to bring recent approvals into the sweep.</p></article>`;

  elements.resultBody.innerHTML = `${parcelSection}${planningSection}${renderRawResponse(payload)}`;
}

async function runAction(statusText, requestFactory, renderer) {
  if (!state.agents.length) {
    setStatus("No Agent", "error");
    setResultsMeta("No scout agent is available. Create or refresh a ResidentialSubdivisionScout agent first.");
    elements.resultBody.innerHTML =
      '<article class="empty-state"><p class="empty-title">No scout agent is available.</p><p>Create `ResidentialSubdivisionScout` first, then refresh the registry.</p></article>';
    return;
  }

  setBusy(true);
  setStatus(statusText, "loading");
  setResultsMeta(`${statusText} with ${selectedAgentName()}...`);

  try {
    const { path, body } = requestFactory();
    const payload = await fetchJson(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    renderer(payload);
    setStatus("Completed", "success");
    setResultsMeta(`${statusText} completed at ${formatRunTime()}.`);
  } catch (error) {
    renderSummary([]);
    elements.resultBody.innerHTML = `
      <article class="empty-state">
        <p class="empty-title">Run failed.</p>
        <p>${escapeHtml(error.message)}</p>
      </article>
    `;
    setStatus("Error", "error");
    setResultsMeta(`${statusText} failed. Review the response below and adjust the inputs.`);
  } finally {
    setBusy(false);
  }
}

async function loadStartData() {
  setBusy(true);
  setStatus("Loading", "loading");
  setResultsMeta("Loading the scout workspace.");

  try {
    const payload = await fetchJson("/api/start");
    state.sampleSearchPrompt = payload.sample_search_prompt || "";
    state.sampleSingleParcelText = payload.sample_single_parcel_text || "";
    state.sampleParcelCsv = payload.sample_parcel_csv || "";
    state.sampleWatchlist = payload.sample_watchlist || "";
    populateAgents(payload.agents || [], payload.default_agent_dir || null);
    setStatus("Ready", "idle");
    if ((payload.agents || []).length) {
      setResultsMeta("Choose a workflow on the left to start screening opportunities.");
    }
  } catch (error) {
    elements.resultBody.innerHTML = `
      <article class="empty-state">
        <p class="empty-title">Startup failed.</p>
        <p>${escapeHtml(error.message)}</p>
      </article>
    `;
    setStatus("Error", "error");
    setResultsMeta("Startup failed. The dashboard could not load its initial data.");
  } finally {
    setBusy(false);
  }
}

async function refreshAgents() {
  setBusy(true);
  setStatus("Refreshing", "loading");
  setResultsMeta("Refreshing the available scout agents.");

  try {
    const payload = await fetchJson("/api/agents");
    populateAgents(payload.agents || [], selectedAgentDir() || state.defaultAgentDir);
    setStatus("Ready", "idle");
    if ((payload.agents || []).length) {
      setResultsMeta("Agent list refreshed. Pick a version and run a workflow.");
    }
  } catch (error) {
    setStatus("Error", "error");
    elements.resultBody.innerHTML = `
      <article class="empty-state">
        <p class="empty-title">Could not refresh the agent list.</p>
        <p>${escapeHtml(error.message)}</p>
      </article>
    `;
    setResultsMeta("Agent refresh failed. Check the message below and try again.");
  } finally {
    setBusy(false);
  }
}

async function importFile(file, target) {
  if (!file) {
    return;
  }
  target.value = await file.text();
  setResultsMeta(`${file.name} imported into the current workflow.`);
}

elements.agentSelect.addEventListener("change", updateAgentMeta);
elements.loadSamplesBtn.addEventListener("click", loadSamplesIntoFields);
elements.samplePromptBtn.addEventListener("click", () => {
  elements.promptSearchInput.value = state.sampleSearchPrompt;
  setResultsMeta("Sample market brief loaded.");
});
elements.sampleSingleBtn.addEventListener("click", () => {
  elements.singleParcelInput.value = state.sampleSingleParcelText;
  setResultsMeta("Sample parcel notes loaded.");
});
elements.sampleCsvBtn.addEventListener("click", () => {
  elements.csvInput.value = state.sampleParcelCsv;
  setResultsMeta("Sample parcel CSV loaded.");
});
elements.sampleWatchBtn.addEventListener("click", () => {
  elements.watchlistInput.value = state.sampleWatchlist;
  setResultsMeta("Sample watchlist loaded.");
});
elements.refreshAgentsBtn.addEventListener("click", refreshAgents);
elements.csvFileInput.addEventListener("change", async (event) => {
  await importFile(event.target.files?.[0], elements.csvInput);
});
elements.watchFileInput.addEventListener("change", async (event) => {
  await importFile(event.target.files?.[0], elements.watchlistInput);
});

elements.promptSearchBtn.addEventListener("click", () => {
  runAction(
    "Searching",
    () => ({
      path: "/api/search-prompt",
      body: {
        agent_dir: selectedAgentDir(),
        query: elements.promptSearchInput.value,
        lookback_days: Number(elements.promptLookbackInput.value || 365),
        max_results_per_query: Number(elements.promptMaxResultsInput.value || 6),
      },
    }),
    renderPromptSearch
  );
});

elements.screenTextBtn.addEventListener("click", () => {
  runAction(
    "Scoring",
    () => ({
      path: "/api/screen-text",
      body: {
        agent_dir: selectedAgentDir(),
        text: elements.singleParcelInput.value,
        market: elements.marketInput.value || "unknown",
        parcel_id: elements.parcelIdInput.value || "parcel-1",
      },
    }),
    renderScreenText
  );
});

elements.screenCsvBtn.addEventListener("click", () => {
  runAction(
    "Ranking",
    () => ({
      path: "/api/screen-csv",
      body: {
        agent_dir: selectedAgentDir(),
        csv_text: elements.csvInput.value,
        top: Number(elements.topInput.value || 12),
        min_score: Number(elements.minScoreInput.value || 0),
      },
    }),
    renderScreenCsv
  );
});

elements.watchBtn.addEventListener("click", () => {
  runAction(
    "Watching",
    () => ({
      path: "/api/watch",
      body: {
        agent_dir: selectedAgentDir(),
        watchlist_text: elements.watchlistInput.value,
        lookback_days: Number(elements.lookbackInput.value || 120),
        max_results_per_query: Number(elements.maxResultsInput.value || 5),
      },
    }),
    renderWatch
  );
});

elements.fullSweepBtn.addEventListener("click", () => {
  runAction(
    "Sweeping",
    () => ({
      path: "/api/full-sweep",
      body: {
        agent_dir: selectedAgentDir(),
        csv_text: elements.csvInput.value,
        single_parcel_text: elements.singleParcelInput.value,
        market: elements.marketInput.value || "unknown",
        parcel_id: elements.parcelIdInput.value || "parcel-1",
        watchlist_text: elements.watchlistInput.value,
        top: Number(elements.topInput.value || 12),
        min_score: Number(elements.minScoreInput.value || 0),
        lookback_days: Number(elements.lookbackInput.value || 120),
        max_results_per_query: Number(elements.maxResultsInput.value || 5),
      },
    }),
    renderFullSweep
  );
});

loadStartData();
