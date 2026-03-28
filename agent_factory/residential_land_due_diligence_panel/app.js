const DRAFT_STORAGE_KEY = "due-diligence-panel-draft-v2";
const SUBSTANTIVE_FIELDS = [
  "opportunity_summary",
  "entitlement_and_zoning",
  "utilities_and_agencies",
  "title_and_access",
  "environmental_and_site",
  "contract_and_seller_items",
  "key_open_items",
];

const SCRATCHPAD_ROUTES = [
  { field: "entitlement_and_zoning", keywords: ["zone", "zoning", "map", "entitle", "annex", "rezone", "general plan", "density", "city", "county"] },
  { field: "utilities_and_agencies", keywords: ["sewer", "water", "utility", "storm", "fire flow", "agency", "will-serve", "offsite", "backbone", "booster", "lift station"] },
  { field: "title_and_access", keywords: ["title", "alta", "access", "frontage", "easement", "boundary", "lien", "ownership"] },
  { field: "environmental_and_site", keywords: ["wetland", "flood", "phase i", "geotech", "soil", "topo", "grading", "drainage", "species", "contamination", "remediation"] },
  { field: "contract_and_seller_items", keywords: ["psa", "deposit", "hard money", "extension", "seller", "deliverable", "closing", "consultant"] },
  { field: "key_open_items", keywords: ["need", "confirm", "validate", "open item", "remaining", "still need", "must clear", "unknown", "pending"] },
];

const state = {
  startPayload: null,
  lastAssessment: null,
  lastQuestion: null,
};
const API_BASE = "api";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("service-worker.js").catch(() => {});
  });
}

const fields = {
  opportunity_name: document.getElementById("opportunityName"),
  market: document.getElementById("market"),
  transaction_stage: document.getElementById("transactionStage"),
  opportunity_summary: document.getElementById("opportunitySummary"),
  entitlement_and_zoning: document.getElementById("entitlementAndZoning"),
  utilities_and_agencies: document.getElementById("utilitiesAndAgencies"),
  title_and_access: document.getElementById("titleAndAccess"),
  environmental_and_site: document.getElementById("environmentalAndSite"),
  contract_and_seller_items: document.getElementById("contractAndSellerItems"),
  key_open_items: document.getElementById("keyOpenItems"),
};

const appState = document.getElementById("appState");
const runStatus = document.getElementById("runStatus");
const agentSelect = document.getElementById("agentSelect");
const agentMeta = document.getElementById("agentMeta");
const scratchpadInput = document.getElementById("scratchpadInput");
const questionInput = document.getElementById("questionInput");
const promptSuggestions = document.getElementById("promptSuggestions");
const healthDial = document.getElementById("healthDial");
const healthPercent = document.getElementById("healthPercent");
const filledCount = document.getElementById("filledCount");
const detailedCount = document.getElementById("detailedCount");
const draftSignal = document.getElementById("draftSignal");
const missingTrail = document.getElementById("missingTrail");
const postureSummary = document.getElementById("postureSummary");
const readinessSummary = document.getElementById("readinessSummary");
const completenessSummary = document.getElementById("completenessSummary");
const confidenceSummary = document.getElementById("confidenceSummary");
const agentSummary = document.getElementById("agentSummary");
const decisionPanel = document.getElementById("decisionPanel");
const criticalList = document.getElementById("criticalList");
const strengthList = document.getElementById("strengthList");
const documentList = document.getElementById("documentList");
const sectionReviewGrid = document.getElementById("sectionReviewGrid");
const briefPreview = document.getElementById("briefPreview");
const knowledgeResponse = document.getElementById("knowledgeResponse");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function labelize(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function slugify(value) {
  return String(value || "due-diligence-intake")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "due-diligence-intake";
}

function selectedAgent() {
  return agentSelect.value || state.startPayload?.default_agent_dir || "";
}

function selectedAgentName() {
  const option = agentSelect.selectedOptions[0];
  return option ? option.textContent : "--";
}

function selectedAgentRecord() {
  const agents = state.startPayload?.agents || [];
  return agents.find((agent) => agent.agent_dir === selectedAgent()) || agents[0] || null;
}

function setAppState(message, tone = "idle") {
  appState.textContent = message;
  appState.dataset.tone = tone;
}

function setRunStatus(message) {
  runStatus.textContent = message;
}

function persistDraft() {
  const draft = {
    selectedAgent: selectedAgent(),
    fields: Object.fromEntries(Object.entries(fields).map(([key, element]) => [key, element.value])),
    scratchpad: scratchpadInput.value,
    question: questionInput.value,
  };

  try {
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
  } catch (error) {
    console.warn("Could not persist draft", error);
  }
}

function restoreDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) {
      return;
    }
    const draft = JSON.parse(raw);
    Object.entries(fields).forEach(([key, element]) => {
      if (draft.fields?.[key] != null) {
        element.value = draft.fields[key];
      }
    });
    scratchpadInput.value = draft.scratchpad || "";
    questionInput.value = draft.question || questionInput.value;
    if (draft.selectedAgent) {
      agentSelect.value = draft.selectedAgent;
    }
  } catch (error) {
    console.warn("Could not restore draft", error);
  }
}

function clearForm() {
  Object.values(fields).forEach((element) => {
    element.value = "";
  });
  scratchpadInput.value = "";
  state.lastAssessment = null;
  persistDraft();
  updateDraftHealth();
  renderAll();
  setRunStatus("Structured draft cleared.");
}

function populateAgents(agents, defaultAgentDir) {
  agentSelect.innerHTML = "";

  if (!agents.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No ResidentialLandDueDiligenceAdvisor found";
    agentSelect.append(option);
    agentSelect.disabled = true;
    agentMeta.textContent = "Create the due diligence agent first, then reload the panel.";
    return;
  }

  agentSelect.disabled = false;
  agents.forEach((agent) => {
    const option = document.createElement("option");
    option.value = agent.agent_dir;
    option.textContent = `${agent.name} | ${agent.created_at_utc || "artifact"}`;
    if (agent.agent_dir === defaultAgentDir) {
      option.selected = true;
    }
    agentSelect.append(option);
  });

  restoreDraft();
  updateAgentMeta();
}

function updateAgentMeta() {
  const selected = selectedAgentRecord();
  if (!selected) {
    agentMeta.textContent = "Residential land acquisition due diligence guidance.";
    return;
  }

  const metricText = selected.metric_name && selected.metric_value != null
    ? `${selected.metric_name}: ${Number(selected.metric_value).toFixed(3)}`
    : "Artifact ready";

  agentMeta.textContent = `${selected.topic || "Residential land acquisition due diligence guidance."} | ${metricText}`;
}

function applySample(sampleName) {
  const sample = state.startPayload?.sample_intakes?.[sampleName];
  if (!sample) {
    setRunStatus("Sample intake was not available.");
    return;
  }

  Object.entries(fields).forEach(([key, element]) => {
    element.value = sample[key] || "";
  });

  persistDraft();
  updateDraftHealth();
  renderAll();
  setRunStatus(`${labelize(sampleName)} sample loaded.`);
}

function collectIntakePayload() {
  const payload = { agent_dir: selectedAgent() };
  Object.entries(fields).forEach(([key, element]) => {
    payload[key] = element.value.trim();
  });
  return payload;
}

function hasMeaningfulIntake(payload) {
  return SUBSTANTIVE_FIELDS.some((key) => payload[key]);
}

function draftHealth() {
  const filled = SUBSTANTIVE_FIELDS.filter((key) => fields[key].value.trim()).length;
  const detailed = SUBSTANTIVE_FIELDS.filter((key) => fields[key].value.trim().split(/\s+/).filter(Boolean).length >= 22).length;
  const pct = Math.round((filled / SUBSTANTIVE_FIELDS.length) * 100);
  const missing = SUBSTANTIVE_FIELDS.filter((key) => !fields[key].value.trim()).map((key) => labelize(key));

  let signal = "Thin";
  if (pct >= 85 && detailed >= 4) {
    signal = "Decision-grade";
  } else if (pct >= 60) {
    signal = "Usable";
  } else if (pct >= 35) {
    signal = "Partial";
  }

  return { filled, detailed, pct, missing, signal };
}

function updateDraftHealth() {
  const health = draftHealth();
  healthDial.style.setProperty("--dial-angle", `${Math.round(health.pct * 3.6)}deg`);
  healthPercent.textContent = `${health.pct}%`;
  filledCount.textContent = `${health.filled} / ${SUBSTANTIVE_FIELDS.length}`;
  detailedCount.textContent = String(health.detailed);
  draftSignal.textContent = health.signal;

  if (!health.missing.length) {
    missingTrail.innerHTML = '<span class="coverage-chip">All key sections filled</span>';
  } else {
    missingTrail.innerHTML = health.missing
      .slice(0, 5)
      .map((item) => `<span class="coverage-chip">${escapeHtml(item)}</span>`)
      .join("");
  }
}

function appendToField(fieldKey, text) {
  const element = fields[fieldKey];
  const chunk = text.trim();
  if (!element || !chunk) {
    return false;
  }
  const existing = element.value.trim();
  if (existing.toLowerCase().includes(chunk.toLowerCase())) {
    return false;
  }
  element.value = existing ? `${existing}\n${chunk}` : chunk;
  return true;
}

function classifyScratchpadChunk(chunk) {
  const normalized = chunk.toLowerCase();
  let bestField = "";
  let bestScore = 0;

  SCRATCHPAD_ROUTES.forEach((route) => {
    const score = route.keywords.reduce((sum, keyword) => sum + (normalized.includes(keyword) ? 1 : 0), 0);
    if (score > bestScore) {
      bestScore = score;
      bestField = route.field;
    }
  });

  if (!bestField) {
    if (/(need|confirm|validate|remaining|still|pending|unknown|open)/.test(normalized)) {
      return "key_open_items";
    }
    return "opportunity_summary";
  }

  return bestField;
}

function distributeScratchpad() {
  const raw = scratchpadInput.value.trim();
  if (!raw) {
    setRunStatus("Paste notes into rapid ingest before distributing them.");
    return;
  }

  const chunks = raw
    .split(/\n+|(?<=[.!?])\s+/)
    .map((item) => item.trim())
    .filter(Boolean);

  let appended = 0;
  const touched = new Set();

  chunks.forEach((chunk) => {
    const fieldKey = classifyScratchpadChunk(chunk);
    if (appendToField(fieldKey, chunk)) {
      appended += 1;
      touched.add(fieldKey);
    }
  });

  persistDraft();
  updateDraftHealth();
  renderAll();

  if (!appended) {
    setRunStatus("Nothing new was distributed from the raw notes.");
    return;
  }

  setRunStatus(`Distributed ${appended} note fragments across ${touched.size} intake sections.`);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data?.detail || `Request failed with status ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

async function copyText(text, successMessage) {
  if (!text) {
    setRunStatus("There is nothing to copy yet.");
    return;
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ghost = document.createElement("textarea");
      ghost.value = text;
      document.body.appendChild(ghost);
      ghost.select();
      document.execCommand("copy");
      ghost.remove();
    }
    setRunStatus(successMessage);
  } catch (error) {
    setRunStatus("Copy failed in this browser context.");
  }
}

function exportSnapshot() {
  const snapshot = {
    generatedAt: new Date().toISOString(),
    input: collectIntakePayload(),
    assessment: state.lastAssessment,
    knowledge: state.lastQuestion,
  };

  const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${slugify(fields.opportunity_name.value || "due-diligence-intake")}.landdue`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  setRunStatus("Deal file downloaded.");
}

function renderPromptSuggestions() {
  const prompts = state.lastAssessment?.follow_up_prompts || state.startPayload?.follow_up_starters || [];
  if (!prompts.length) {
    promptSuggestions.innerHTML = '<div class="placeholder-block">Run an assessment to surface smarter follow-up prompts.</div>';
    return;
  }

  promptSuggestions.innerHTML = prompts
    .map((prompt) => `<button type="button" class="prompt-pill" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`)
    .join("");
}

function renderList(target, items, kind, emptyMessage) {
  if (!items?.length) {
    target.innerHTML = `<div class="placeholder-block">${escapeHtml(emptyMessage)}</div>`;
    return;
  }

  target.innerHTML = `
    <div class="list-stack">
      ${items.map((item) => `<article class="list-item ${kind}"><strong>${escapeHtml(item)}</strong></article>`).join("")}
    </div>
  `;
}

function renderSectionReviews() {
  const reviews = state.lastAssessment?.section_reviews || [];
  if (!reviews.length) {
    sectionReviewGrid.innerHTML = '<div class="placeholder-block">Run an assessment to see a bucket-by-bucket diligence read.</div>';
    return;
  }

  sectionReviewGrid.innerHTML = reviews
    .map((review) => {
      const hitTags = [];
      review.blocker_hits?.forEach((item) => hitTags.push(`<span class="hit-tag danger">${escapeHtml(item)}</span>`));
      review.warning_hits?.forEach((item) => hitTags.push(`<span class="hit-tag warning">${escapeHtml(item)}</span>`));
      review.positive_hits?.forEach((item) => hitTags.push(`<span class="hit-tag positive">${escapeHtml(item)}</span>`));

      return `
        <article class="section-card ${escapeHtml(review.status)}">
          <div class="section-card-head">
            <span class="status-chip ${escapeHtml(review.status)}">${escapeHtml(review.status_label)}</span>
            <span class="coverage-chip">${escapeHtml(review.coverage_band)}</span>
          </div>
          <h4>${escapeHtml(review.label)}</h4>
          <p class="section-headline">${escapeHtml(review.headline)}</p>
          <p class="section-detail">${escapeHtml(review.detail)}</p>
          <div class="hit-cluster">${hitTags.join("") || '<span class="hit-tag">No distinct signal tags</span>'}</div>
        </article>
      `;
    })
    .join("");
}

function renderKnowledgeResponse() {
  if (!state.lastQuestion) {
    knowledgeResponse.innerHTML = '<div class="placeholder-block">Ask the playbook to pull supporting excerpts from the due-diligence knowledge base.</div>';
    return;
  }

  const sources = state.lastQuestion.sources || [];
  knowledgeResponse.innerHTML = `
    <div class="knowledge-answer">${escapeHtml(state.lastQuestion.answer || "No answer returned.")}</div>
    <div class="source-list">
      ${sources.length
        ? sources
            .map((item) => {
              const sourceName = String(item.source || "Knowledge excerpt").split(/[\\/]/).pop();
              return `
                <article class="source-item">
                  <strong>${escapeHtml(sourceName)}</strong>
                  <p class="source-score">Relevance score: ${Number(item.score || 0).toFixed(3)}</p>
                </article>
              `;
            })
            .join("")
        : '<div class="placeholder-block">No supporting excerpts were returned.</div>'}
    </div>
  `;
}

function renderDecisionPanel() {
  const health = draftHealth();
  if (!state.lastAssessment) {
    decisionPanel.className = "spotlight-panel idle";
    decisionPanel.innerHTML = `
      <div class="spotlight-head">
        <div>
          <span class="status-chip idle">Draft mode</span>
          <h2>Build the intake until the deal is explicit enough to test.</h2>
        </div>
      </div>
      <p class="spotlight-copy">
        The panel is tracking draft completeness in real time. Once the basics are in place, run the assessment to get posture,
        section reviews, document requests, and follow-up prompts.
      </p>
      <div class="mini-grid">
        <article>
          <span class="metric-label">Coverage now</span>
          <strong>${health.pct}%</strong>
        </article>
        <article>
          <span class="metric-label">Detailed buckets</span>
          <strong>${health.detailed}</strong>
        </article>
        <article>
          <span class="metric-label">Missing buckets</span>
          <strong>${health.missing.length}</strong>
        </article>
      </div>
    `;
    return;
  }

  const assessment = state.lastAssessment;
  decisionPanel.className = `spotlight-panel ${assessment.tone || "idle"}`;
  decisionPanel.innerHTML = `
    <div class="spotlight-head">
      <div>
        <span class="status-chip ${escapeHtml(assessment.tone || "idle")}">${escapeHtml(assessment.posture_label)}</span>
        <h2>${escapeHtml(assessment.summary || "Assessment complete.")}</h2>
      </div>
      <span class="coverage-chip">${escapeHtml(assessment.confidence_band || "Unscored")}</span>
    </div>
    <p class="spotlight-copy">${escapeHtml(assessment.next_step || "Review the remaining diligence items.")}</p>
    <div class="decision-callout">
      <strong>Immediate next move:</strong>
      <span class="decision-meta"> ${escapeHtml(assessment.next_step || "Review the remaining diligence items.")}</span>
    </div>
    <div class="mini-grid">
      <article>
        <span class="metric-label">Readiness</span>
        <strong>${escapeHtml(String(assessment.readiness?.score ?? "--"))}/100</strong>
        <p class="decision-meta">${escapeHtml(assessment.readiness?.band || "")}</p>
      </article>
      <article>
        <span class="metric-label">Coverage</span>
        <strong>${escapeHtml(String(assessment.coverage?.coverage_pct ?? "--"))}%</strong>
        <p class="decision-meta">${escapeHtml(String(assessment.coverage?.filled_sections ?? 0))}/${escapeHtml(String(assessment.coverage?.total_sections ?? 0))} sections filled</p>
      </article>
      <article>
        <span class="metric-label">Top confidence</span>
        <strong>${Number.isFinite(assessment.confidence_pct) ? `${assessment.confidence_pct.toFixed(1)}%` : "--"}</strong>
        <p class="decision-meta">${escapeHtml(assessment.confidence_band || "")}</p>
      </article>
    </div>
  `;
}

function renderBrief() {
  briefPreview.textContent = state.lastAssessment?.brief || "Run an assessment to build a copy-ready diligence brief.";
}

function renderSummaryStrip() {
  const health = draftHealth();
  postureSummary.textContent = state.lastAssessment?.posture_label || "Drafting";
  readinessSummary.textContent = state.lastAssessment?.readiness
    ? `${state.lastAssessment.readiness.score}/100`
    : "--";
  completenessSummary.textContent = state.lastAssessment?.coverage
    ? `${Number(state.lastAssessment.coverage.coverage_pct || 0).toFixed(0)}%`
    : `${health.pct}%`;
  confidenceSummary.textContent = Number.isFinite(state.lastAssessment?.confidence_pct)
    ? `${state.lastAssessment.confidence_pct.toFixed(1)}%`
    : "--";
  agentSummary.textContent = selectedAgentName();
}

function renderAll() {
  renderSummaryStrip();
  renderDecisionPanel();
  renderList(
    criticalList,
    state.lastAssessment?.signal_summary?.critical_risks,
    "critical",
    "No critical issues surfaced yet. Run an assessment to see the current risk stack.",
  );
  renderList(
    strengthList,
    state.lastAssessment?.signal_summary?.strengths,
    "strength",
    "No de-risking signals are summarized yet.",
  );
  renderList(
    documentList,
    state.lastAssessment?.document_requests,
    "document",
    "No document request list yet. Run an assessment to surface what backup the team should ask for.",
  );
  renderSectionReviews();
  renderBrief();
  renderKnowledgeResponse();
  renderPromptSuggestions();
}

async function initialize() {
  setAppState("Connecting", "idle");
  setRunStatus("Loading panel state.");

  try {
    const payload = await fetchJson("/api/start");
    state.startPayload = payload;
    populateAgents(payload.agents || [], payload.default_agent_dir);
    if (!questionInput.value) {
      questionInput.value = payload.sample_question || "";
    }
    updateDraftHealth();
    renderAll();
    setAppState("Ready", "success");
    setRunStatus("Studio ready. Paste notes, distribute them, and run an assessment when the draft is usable.");
  } catch (error) {
    setAppState("Unavailable", "danger");
    setRunStatus(error.message || "Failed to load panel state.");
    renderAll();
  }
}

async function runAssessment() {
  const payload = collectIntakePayload();
  if (!hasMeaningfulIntake(payload)) {
    setRunStatus("Add diligence notes before running the assessment.");
    return;
  }

  setRunStatus("Assessing diligence posture.");
  setAppState("Working", "warning");

  try {
    state.lastAssessment = await fetchJson("/api/intake", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setAppState("Ready", state.lastAssessment.tone || "success");
    setRunStatus(`Assessment complete: ${state.lastAssessment.posture_label}.`);
  } catch (error) {
    setAppState("Issue", "danger");
    setRunStatus(error.message || "Assessment failed.");
  }

  renderAll();
}

async function askQuestion() {
  const question = questionInput.value.trim();
  if (!question) {
    setRunStatus("Enter a question before asking the agent.");
    return;
  }

  setRunStatus("Querying the due diligence knowledge base.");
  setAppState("Working", "warning");

  try {
    state.lastQuestion = await fetchJson("/api/ask", {
      method: "POST",
      body: JSON.stringify({
        agent_dir: selectedAgent(),
        question,
        top_k: 3,
      }),
    });
    setAppState("Ready", "success");
    setRunStatus("Knowledge response ready.");
  } catch (error) {
    setAppState("Issue", "danger");
    setRunStatus(error.message || "Question failed.");
  }

  renderAll();
}

document.getElementById("runAssessment").addEventListener("click", runAssessment);
document.getElementById("askQuestion").addEventListener("click", askQuestion);
document.getElementById("loadQuestion").addEventListener("click", () => {
  questionInput.value = state.startPayload?.sample_question || "";
  persistDraft();
  setRunStatus("Sample question loaded.");
});
document.getElementById("clearForm").addEventListener("click", clearForm);
document.getElementById("distributeNotes").addEventListener("click", distributeScratchpad);
document.getElementById("clearScratchpad").addEventListener("click", () => {
  scratchpadInput.value = "";
  persistDraft();
  setRunStatus("Rapid-ingest notes cleared.");
});
document.getElementById("copyBrief").addEventListener("click", () => copyText(state.lastAssessment?.brief, "Diligence brief copied."));
document.getElementById("copyBriefInline").addEventListener("click", () => copyText(state.lastAssessment?.brief, "Diligence brief copied."));
document.getElementById("exportJson").addEventListener("click", exportSnapshot);
document.querySelectorAll("[data-sample]").forEach((button) => {
  button.addEventListener("click", () => applySample(button.dataset.sample));
});

promptSuggestions.addEventListener("click", (event) => {
  const target = event.target.closest("[data-prompt]");
  if (!target) {
    return;
  }
  questionInput.value = target.dataset.prompt || "";
  persistDraft();
  setRunStatus("Follow-up prompt loaded into the question box.");
});

agentSelect.addEventListener("change", () => {
  updateAgentMeta();
  persistDraft();
  renderAll();
});

[...Object.values(fields), scratchpadInput, questionInput].forEach((element) => {
  element.addEventListener("input", () => {
    persistDraft();
    updateDraftHealth();
    renderAll();
  });
});

initialize();
