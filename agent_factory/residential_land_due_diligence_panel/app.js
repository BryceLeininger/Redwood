const state = {
  startPayload: null,
  lastAssessment: null,
  lastQuestion: null,
};

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
const questionInput = document.getElementById("questionInput");
const resultsBody = document.getElementById("resultsBody");
const postureSummary = document.getElementById("postureSummary");
const confidenceSummary = document.getElementById("confidenceSummary");
const agentSummary = document.getElementById("agentSummary");

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

function selectedAgent() {
  return agentSelect.value || state.startPayload?.default_agent_dir || "";
}

function selectedAgentName() {
  const option = agentSelect.selectedOptions[0];
  return option ? option.textContent : "--";
}

function setAppState(message, tone = "idle") {
  appState.textContent = message;
  appState.dataset.tone = tone;
}

function setRunStatus(message) {
  runStatus.textContent = message;
}

function clearForm() {
  Object.values(fields).forEach((element) => {
    element.value = "";
  });
  state.lastAssessment = null;
  renderAll();
  setRunStatus("Form cleared.");
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
    option.textContent = `${agent.name} · ${agent.created_at_utc || "artifact"}`;
    if (agent.agent_dir === defaultAgentDir) {
      option.selected = true;
    }
    agentSelect.append(option);
  });

  const selected = agents.find((agent) => agent.agent_dir === selectedAgent()) || agents[0];
  agentMeta.textContent = selected?.topic || "Residential land acquisition due diligence guidance.";
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
  return [
    payload.opportunity_summary,
    payload.entitlement_and_zoning,
    payload.utilities_and_agencies,
    payload.title_and_access,
    payload.environmental_and_site,
    payload.contract_and_seller_items,
    payload.key_open_items,
  ].some((value) => value);
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

function renderClassDistribution(result) {
  const classes = result?.top_classes || [];
  if (!classes.length) {
    return "<p class=\"prose-muted\">No class probability data returned by the model.</p>";
  }

  return `
    <div class="class-list">
      ${classes
        .map((item) => {
          const pct = Number(item.confidence || 0) * 100;
          return `
            <div class="class-row">
              <span class="class-label">${escapeHtml(labelize(item.label))}</span>
              <div class="class-bar"><span style="width: ${Math.max(0, Math.min(100, pct))}%;"></span></div>
              <span>${pct.toFixed(1)}%</span>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderAssessment() {
  if (!state.lastAssessment) {
    return "";
  }

  const assessment = state.lastAssessment;
  const confidenceText = Number.isFinite(assessment.confidence_pct)
    ? `${assessment.confidence_pct.toFixed(1)}%`
    : "--";

  return `
    <section class="result-section">
      <div class="section-row">
        <span class="tone-chip ${escapeHtml(assessment.tone || "idle")}">${escapeHtml(assessment.posture_label || "Assessment")}</span>
        <span class="prose-muted">Top confidence: ${escapeHtml(confidenceText)}</span>
      </div>
      <h3>${escapeHtml(assessment.summary || "Assessment complete.")}</h3>
      <div class="callout">
        <strong>Recommended next step:</strong> ${escapeHtml(assessment.next_step || "Review the remaining diligence items.")}
      </div>
      <h3>Class confidence</h3>
      ${renderClassDistribution(assessment.result)}
      <details>
        <summary>View intake text sent to the agent</summary>
        <div class="intake-block">${escapeHtml(assessment.intake_text || "")}</div>
      </details>
    </section>
  `;
}

function renderQuestion() {
  if (!state.lastQuestion) {
    return "";
  }

  const questionResult = state.lastQuestion;
  const sources = questionResult.sources || [];
  return `
    <section class="result-section">
      <div class="section-row">
        <span class="tone-chip idle">Knowledge response</span>
      </div>
      <h3>${escapeHtml(questionResult.question || "Question")}</h3>
      <div class="answer-block">${escapeHtml(questionResult.answer || "No answer returned.")}</div>
      <div class="source-list">
        ${sources.length
          ? sources
              .map(
                (item) => `
                  <article class="source-item">
                    <p class="source-name">${escapeHtml(item.source || "Knowledge excerpt")}</p>
                    <p class="source-score">Relevance score: ${Number(item.score || 0).toFixed(3)}</p>
                  </article>
                `,
              )
              .join("")
          : '<p class="prose-muted">No supporting excerpts were returned.</p>'}
      </div>
    </section>
  `;
}

function renderAll() {
  postureSummary.textContent = state.lastAssessment?.posture_label || "No assessment yet";
  confidenceSummary.textContent = Number.isFinite(state.lastAssessment?.confidence_pct)
    ? `${state.lastAssessment.confidence_pct.toFixed(1)}%`
    : "--";
  agentSummary.textContent = selectedAgentName();

  const assessmentMarkup = renderAssessment();
  const questionMarkup = renderQuestion();

  if (!assessmentMarkup && !questionMarkup) {
    resultsBody.innerHTML = `
      <div class="empty-state">
        <p class="empty-kicker">No result yet</p>
        <h3>Run an assessment or ask a diligence question.</h3>
        <p>
          The panel will summarize the recommended posture, show class confidence, and surface the
          knowledge excerpts the agent used for follow-up questions.
        </p>
      </div>
    `;
    return;
  }

  resultsBody.innerHTML = `${assessmentMarkup}${questionMarkup}`;
}

async function initialize() {
  setAppState("Connecting", "idle");
  setRunStatus("Loading panel state.");

  try {
    const payload = await fetchJson("/api/start");
    state.startPayload = payload;
    populateAgents(payload.agents || [], payload.default_agent_dir);
    questionInput.value = payload.sample_question || "";
    setAppState("Ready", "success");
    setRunStatus("Panel ready. Load a sample or enter live diligence notes.");
  } catch (error) {
    setAppState("Unavailable", "danger");
    setRunStatus(error.message || "Failed to load panel state.");
  }

  renderAll();
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
  setRunStatus("Sample question loaded.");
});
document.getElementById("clearForm").addEventListener("click", clearForm);
document.querySelectorAll("[data-sample]").forEach((button) => {
  button.addEventListener("click", () => applySample(button.dataset.sample));
});
agentSelect.addEventListener("change", () => {
  const agents = state.startPayload?.agents || [];
  const selected = agents.find((agent) => agent.agent_dir === selectedAgent());
  agentMeta.textContent = selected?.topic || "Residential land acquisition due diligence guidance.";
  renderAll();
});

initialize();