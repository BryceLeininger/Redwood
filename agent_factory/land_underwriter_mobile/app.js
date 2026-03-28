const STORAGE_KEY = "land-underwriter-mobile-v1";
const API_BASE = "api";

const ROOT_PERCENT_FIELDS = new Set([
  "sales_commission_pct",
  "corporate_charge_pct",
  "home_sale_excise_tax_pct",
  "target_gross_margin_pct",
  "target_pre_gna_margin_pct",
  "target_irr_pct",
  "downside_sales_price_delta_pct",
  "downside_cost_delta_pct",
  "downside_absorption_delta_pct",
  "severe_downside_sales_price_delta_pct",
  "severe_downside_cost_delta_pct",
  "severe_downside_absorption_delta_pct",
]);

const ROW_PERCENT_FIELDS = new Set([
  "options_pct",
  "price_incentives_pct",
  "mortgage_incentives_pct",
  "direct_cost_contingency_pct",
]);

const PRODUCT_FIELDS = [
  { key: "name", label: "Series", type: "text", placeholder: "Series A" },
  { key: "lots", label: "Lots", type: "text", placeholder: "25" },
  { key: "avg_sqft", label: "Avg sqft", type: "text", placeholder: "2300" },
  { key: "base_house_price", label: "Base price", type: "text", placeholder: "775000" },
  { key: "lot_premium", label: "Lot premium", type: "text", placeholder: "0" },
  { key: "options_pct", label: "Options %", type: "text", placeholder: "0" },
  { key: "price_incentives_pct", label: "Price incentive %", type: "text", placeholder: "3" },
  { key: "mortgage_incentives_pct", label: "Mortgage incentive %", type: "text", placeholder: "3" },
  { key: "direct_cost_psf", label: "Direct $ / sqft", type: "text", placeholder: "90" },
  { key: "direct_cost_contingency_pct", label: "Cost contingency %", type: "text", placeholder: "2" },
  { key: "permit_fees_per_unit", label: "Permit / unit", type: "text", placeholder: "75000" },
  { key: "tap_fees_per_unit", label: "Tap / unit", type: "text", placeholder: "20000" },
  { key: "other_vertical_costs_per_unit", label: "Other vertical / unit", type: "text", placeholder: "0" },
  { key: "move_up", label: "Move-up product", type: "checkbox" },
];

const PHASE_FIELDS = [
  { key: "name", label: "Phase", type: "text", placeholder: "Phase 1" },
  { key: "month", label: "Close month", type: "text", placeholder: "0" },
  { key: "lots", label: "Lots", type: "text", placeholder: "25" },
  { key: "price_per_lot", label: "Price / lot", type: "text", placeholder: "67500" },
];

const COMPETITOR_FIELDS = [
  { key: "name", label: "Community", type: "text", placeholder: "Ridgeview" },
  { key: "monthly_absorption", label: "Pace / month", type: "text", placeholder: "2.9" },
  { key: "avg_price", label: "Net price", type: "text", placeholder: "742000" },
  { key: "avg_sqft", label: "Avg sqft", type: "text", placeholder: "2210" },
  { key: "status", label: "Status", type: "text", placeholder: "Actively selling" },
];

const RESALE_FIELDS = [
  { key: "name", label: "Address", type: "text", placeholder: "2211 Cedar Ridge Dr" },
  { key: "close_price", label: "Close price", type: "text", placeholder: "748000" },
  { key: "sqft", label: "Sqft", type: "text", placeholder: "2255" },
  { key: "distance_miles", label: "Miles away", type: "text", placeholder: "1.8" },
  { key: "close_date", label: "Close date", type: "date" },
];

const LIST_CONFIG = {
  product_series: {
    fields: PRODUCT_FIELDS,
    containerId: "productSeriesList",
    title: "Product series",
    empty: "Add at least one product series to define the deal.",
  },
  schedule_phases: {
    fields: PHASE_FIELDS,
    containerId: "schedulePhaseList",
    title: "Phase",
    empty: "Add phased land takedowns or rely on a bulk land price per lot.",
  },
  competitor_projects: {
    fields: COMPETITOR_FIELDS,
    containerId: "competitorList",
    title: "Competitor",
    empty: "Add competing communities to benchmark pace, pricing, and monthly revenue.",
  },
  resale_comps: {
    fields: RESALE_FIELDS,
    containerId: "resaleList",
    title: "Resale comp",
    empty: "Add recent resale support to test price per foot and market depth.",
  },
};

const state = {
  startPayload: null,
  selectedAgent: "",
  deal: null,
  result: null,
  fileName: "starter_deal.landdeal",
};

const appState = document.getElementById("appState");
const agentSelect = document.getElementById("agentSelect");
const agentMeta = document.getElementById("agentMeta");
const fileMeta = document.getElementById("fileMeta");
const runStatus = document.getElementById("runStatus");
const dealFileInput = document.getElementById("dealFileInput");
const snapshotGrid = document.getElementById("snapshotGrid");
const recommendationBanner = document.getElementById("recommendationBanner");
const headlineGrid = document.getElementById("headlineGrid");
const scenarioGrid = document.getElementById("scenarioGrid");
const scheduleView = document.getElementById("scheduleView");
const marketView = document.getElementById("marketView");
const sensitivityView = document.getElementById("sensitivityView");
const memoPreview = document.getElementById("memoPreview");
const rootInputs = Array.from(document.querySelectorAll("[data-root-field]"));

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("service-worker.js").catch(() => {});
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function trimNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "";
  }
  return String(Number(numeric.toFixed(4)));
}

function parseNumber(value) {
  if (value == null || value === "") {
    return null;
  }
  const cleaned = String(value).replaceAll(",", "").replaceAll("$", "").replaceAll("%", "").trim();
  if (!cleaned) {
    return null;
  }
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseRatioInput(value) {
  const parsed = parseNumber(value);
  if (parsed == null) {
    return null;
  }
  return Math.abs(parsed) > 1 ? parsed / 100 : parsed;
}

function safeDiv(numerator, denominator) {
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || Math.abs(denominator) < 1e-9) {
    return null;
  }
  return numerator / denominator;
}

function slugify(value) {
  return String(value || "land-deal")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "land-deal";
}

function formatCurrency(value, digits = 0) {
  if (value == null || !Number.isFinite(Number(value))) {
    return "-";
  }
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(Number(value));
}

function formatNumber(value, digits = 1) {
  if (value == null || !Number.isFinite(Number(value))) {
    return "-";
  }
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(Number(value));
}

function formatPct(value) {
  if (value == null || !Number.isFinite(Number(value))) {
    return "-";
  }
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function cardMarkup(label, value, note = "") {
  return `
    <article class="metric-card">
      <span class="metric-label">${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${note ? `<span class="metric-note">${escapeHtml(note)}</span>` : ""}
    </article>
  `;
}

function setAppState(message, tone = "idle") {
  appState.textContent = message;
  appState.dataset.tone = tone;
}

function setRunStatus(message) {
  runStatus.textContent = message;
}

function rowDefaults(fields, fallbackTitle) {
  const row = {};
  fields.forEach((field) => {
    row[field.key] = field.type === "checkbox" ? false : "";
  });
  if (fallbackTitle && "name" in row && !row.name) {
    row.name = fallbackTitle;
  }
  return row;
}

function editorValue(field, value) {
  if (value == null) {
    return "";
  }
  if (typeof value === "boolean") {
    return value;
  }
  if (ROOT_PERCENT_FIELDS.has(field) || ROW_PERCENT_FIELDS.has(field)) {
    return typeof value === "number" ? trimNumber(value * 100) : String(value);
  }
  if (typeof value === "number") {
    return trimNumber(value);
  }
  return String(value);
}

function normalizeRow(rawRow, fields, fallbackTitle) {
  const row = rowDefaults(fields, fallbackTitle);
  const source = rawRow || {};
  fields.forEach((field) => {
    if (field.type === "checkbox") {
      row[field.key] = Boolean(source[field.key]);
    } else {
      row[field.key] = editorValue(field.key, source[field.key]);
    }
  });
  return row;
}

function normalizeDeal(rawDeal) {
  const source = rawDeal || {};
  const draft = {};

  rootInputs.forEach((input) => {
    const key = input.dataset.rootField;
    if (input.type === "checkbox") {
      draft[key] = Boolean(source[key]);
    } else {
      draft[key] = editorValue(key, source[key]);
    }
  });

  draft.product_series = Array.isArray(source.product_series) && source.product_series.length
    ? source.product_series.map((row, index) => normalizeRow(row, PRODUCT_FIELDS, `Series ${index + 1}`))
    : [rowDefaults(PRODUCT_FIELDS, "Series 1")];

  draft.schedule_phases = Array.isArray(source.schedule_phases) && source.schedule_phases.length
    ? source.schedule_phases.map((row, index) => normalizeRow(row, PHASE_FIELDS, `Phase ${index + 1}`))
    : [rowDefaults(PHASE_FIELDS, "Phase 1")];

  draft.competitor_projects = Array.isArray(source.competitor_projects) && source.competitor_projects.length
    ? source.competitor_projects.map((row, index) => normalizeRow(row, COMPETITOR_FIELDS, `Competitor ${index + 1}`))
    : [rowDefaults(COMPETITOR_FIELDS, "Competitor 1")];

  draft.resale_comps = Array.isArray(source.resale_comps) && source.resale_comps.length
    ? source.resale_comps.map((row, index) => normalizeRow(row, RESALE_FIELDS, `Resale ${index + 1}`))
    : [rowDefaults(RESALE_FIELDS, "Resale 1")];

  return draft;
}

function serializeRow(row, fields) {
  const payload = {};
  fields.forEach((field) => {
    const raw = row[field.key];
    if (field.type === "checkbox") {
      if (raw) {
        payload[field.key] = true;
      }
      return;
    }
    if (raw == null || String(raw).trim() === "") {
      return;
    }
    payload[field.key] = ROW_PERCENT_FIELDS.has(field.key) ? parseRatioInput(raw) : String(raw).trim();
  });
  return payload;
}

function dealPayload() {
  const payload = {};
  rootInputs.forEach((input) => {
    const key = input.dataset.rootField;
    const raw = state.deal[key];
    if (input.type === "checkbox") {
      payload[key] = Boolean(raw);
      return;
    }
    if (raw == null || String(raw).trim() === "") {
      return;
    }
    payload[key] = ROOT_PERCENT_FIELDS.has(key) ? parseRatioInput(raw) : String(raw).trim();
  });

  payload.product_series = state.deal.product_series
    .map((row) => serializeRow(row, PRODUCT_FIELDS))
    .filter((row) => Object.keys(row).length > 0);
  payload.schedule_phases = state.deal.schedule_phases
    .map((row) => serializeRow(row, PHASE_FIELDS))
    .filter((row) => Object.keys(row).length > 0);
  payload.competitor_projects = state.deal.competitor_projects
    .map((row) => serializeRow(row, COMPETITOR_FIELDS))
    .filter((row) => Object.keys(row).length > 0);
  payload.resale_comps = state.deal.resale_comps
    .map((row) => serializeRow(row, RESALE_FIELDS))
    .filter((row) => Object.keys(row).length > 0);

  return payload;
}

function selectedAgentRecord() {
  const agents = state.startPayload?.agents || [];
  return agents.find((agent) => agent.agent_dir === state.selectedAgent) || null;
}

function populateAgents(agents, defaultAgentDir) {
  state.startPayload.agents = agents || [];
  agentSelect.innerHTML = "";

  const workbookOption = document.createElement("option");
  workbookOption.value = "";
  workbookOption.textContent = "Workbook logic only";
  agentSelect.append(workbookOption);

  (agents || []).forEach((agent) => {
    const option = document.createElement("option");
    option.value = agent.agent_dir || "";
    option.textContent = agent.created_at_utc
      ? `${agent.name} | ${agent.created_at_utc.slice(0, 10)}`
      : agent.name || "LandDealUnderwriter";
    if ((state.selectedAgent && state.selectedAgent === option.value) || (!state.selectedAgent && option.value === defaultAgentDir)) {
      option.selected = true;
    }
    agentSelect.append(option);
  });

  state.selectedAgent = agentSelect.value || defaultAgentDir || "";
  updateAgentMeta();
}

function updateAgentMeta() {
  const selected = selectedAgentRecord();
  if (!selected) {
    agentMeta.textContent = "Workbook underwriting stays available even without a trained artifact.";
    return;
  }
  const metricText = selected.metric_name && selected.metric_value != null
    ? `${selected.metric_name}: ${Number(selected.metric_value).toFixed(3)}`
    : "Artifact ready";
  agentMeta.textContent = `${selected.topic || "Land acquisition underwriting"} | ${metricText}`;
}

function persistDraft() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        selectedAgent: state.selectedAgent,
        deal: state.deal,
        fileName: state.fileName,
      })
    );
  } catch (error) {
    console.warn("Could not persist land draft", error);
  }
}

function restoreDraft() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const draft = JSON.parse(raw);
    if (!draft?.deal) {
      return null;
    }
    state.selectedAgent = draft.selectedAgent || "";
    state.fileName = draft.fileName || state.fileName;
    return normalizeDeal(draft.deal);
  } catch (error) {
    console.warn("Could not restore land draft", error);
    return null;
  }
}

function renderRootFields() {
  rootInputs.forEach((input) => {
    const key = input.dataset.rootField;
    if (input.type === "checkbox") {
      input.checked = Boolean(state.deal[key]);
    } else {
      input.value = state.deal[key] ?? "";
    }
  });
}

function inputMarkup(group, index, field, value) {
  if (field.type === "checkbox") {
    return `
      <label class="toggle-field">
        <span class="field-label">${escapeHtml(field.label)}</span>
        <input type="checkbox" data-group="${group}" data-index="${index}" data-field="${field.key}" ${value ? "checked" : ""} />
      </label>
    `;
  }

  const inputType = field.type === "date" ? "date" : "text";
  const inputMode = field.type === "date" ? "" : 'inputmode="decimal"';
  return `
    <label>
      <span class="field-label">${escapeHtml(field.label)}</span>
      <input
        type="${inputType}"
        ${inputMode}
        data-group="${group}"
        data-index="${index}"
        data-field="${field.key}"
        value="${escapeHtml(value ?? "")}"
        placeholder="${escapeHtml(field.placeholder || "")}"
      />
    </label>
  `;
}

function renderList(group) {
  const config = LIST_CONFIG[group];
  const container = document.getElementById(config.containerId);
  const rows = state.deal[group] || [];

  if (!rows.length) {
    container.innerHTML = `<div class="placeholder-block">${escapeHtml(config.empty)}</div>`;
    return;
  }

  container.innerHTML = rows
    .map((row, index) => {
      const title = row.name || `${config.title} ${index + 1}`;
      return `
        <article class="row-card">
          <div class="row-card-header">
            <h4>${escapeHtml(title)}</h4>
            <button type="button" class="remove-row-button" data-remove-row="${group}" data-index="${index}">Remove</button>
          </div>
          <div class="row-card-grid">
            ${config.fields.map((field) => inputMarkup(group, index, field, row[field.key])).join("")}
          </div>
        </article>
      `;
    })
    .join("");
}

function rowCollection(group) {
  return state.deal[group] || [];
}

function numericListSummary() {
  const productRows = rowCollection("product_series");
  const phaseRows = rowCollection("schedule_phases");
  const competitors = rowCollection("competitor_projects");
  const resales = rowCollection("resale_comps");

  const totalLots = productRows.reduce((sum, row) => sum + (parseNumber(row.lots) || 0), 0);
  const weightedNetSales = productRows.reduce((sum, row) => {
    const lots = parseNumber(row.lots) || 0;
    const base = parseNumber(row.base_house_price) || 0;
    const premium = parseNumber(row.lot_premium) || 0;
    const options = parseRatioInput(row.options_pct) || 0;
    const priceIncentive = parseRatioInput(row.price_incentives_pct) || 0;
    const mortgageIncentive = parseRatioInput(row.mortgage_incentives_pct) || 0;
    const netPrice = base + premium + base * options - base * (priceIncentive + mortgageIncentive);
    return sum + lots * netPrice;
  }, 0);
  const avgNetSales = safeDiv(weightedNetSales, totalLots);

  const weightedBuildCost = productRows.reduce((sum, row) => {
    const lots = parseNumber(row.lots) || 0;
    const sqft = parseNumber(row.avg_sqft) || 0;
    const direct = parseNumber(row.direct_cost_psf) || 0;
    const contingency = parseRatioInput(row.direct_cost_contingency_pct) || 0;
    const permit = parseNumber(row.permit_fees_per_unit) || 0;
    const tap = parseNumber(row.tap_fees_per_unit) || 0;
    const other = parseNumber(row.other_vertical_costs_per_unit) || 0;
    const buildCost = direct * sqft * (1 + contingency) + permit + tap + other;
    return sum + lots * buildCost;
  }, 0);
  const avgBuildCost = safeDiv(weightedBuildCost, totalLots);

  const phaseBasis = phaseRows.reduce((sum, row) => sum + (parseNumber(row.lots) || 0) * (parseNumber(row.price_per_lot) || 0), 0);
  const bulkBasis = (parseNumber(state.deal.land_purchase_price_per_lot) || 0) * totalLots;
  const landBasis = phaseBasis || bulkBasis;

  const competitorAvgPrice = safeDiv(
    competitors.reduce((sum, row) => sum + (parseNumber(row.avg_price) || 0), 0),
    competitors.filter((row) => parseNumber(row.avg_price)).length
  );
  const competitorAvgPace = safeDiv(
    competitors.reduce((sum, row) => sum + (parseNumber(row.monthly_absorption) || 0), 0),
    competitors.filter((row) => parseNumber(row.monthly_absorption)).length
  );

  const resalePpsfValues = resales
    .map((row) => safeDiv(parseNumber(row.close_price) || 0, parseNumber(row.sqft) || 0))
    .filter((value) => value != null);
  const avgResalePpsf = safeDiv(resalePpsfValues.reduce((sum, value) => sum + value, 0), resalePpsfValues.length);

  return {
    totalLots,
    avgNetSales,
    avgBuildCost,
    landBasis,
    competitorAvgPrice,
    competitorAvgPace,
    avgResalePpsf,
    subjectRevenuePerMonth: (avgNetSales || 0) * (parseNumber(state.deal.monthly_absorption) || 0),
  };
}

function renderSnapshot() {
  const summary = numericListSummary();
  const cards = [
    cardMarkup("Lots", formatNumber(summary.totalLots, 0), `${state.deal.product_series.length} product row${state.deal.product_series.length === 1 ? "" : "s"}`),
    cardMarkup("Net price", formatCurrency(summary.avgNetSales), summary.competitorAvgPrice ? `vs comps ${formatPct(safeDiv((summary.avgNetSales || 0) - summary.competitorAvgPrice, summary.competitorAvgPrice))}` : "Add competitor pricing"),
    cardMarkup("Build cost / unit", formatCurrency(summary.avgBuildCost), "Weighted across the product mix"),
    cardMarkup("Land basis", formatCurrency(summary.landBasis), state.deal.schedule_phases.some((row) => parseNumber(row.lots)) ? "Phase schedule is driving lot basis" : "Bulk land price is driving lot basis"),
    cardMarkup("Pace", formatNumber(parseNumber(state.deal.monthly_absorption), 2), summary.competitorAvgPace ? `vs comps ${formatPct(safeDiv((parseNumber(state.deal.monthly_absorption) || 0) - summary.competitorAvgPace, summary.competitorAvgPace))}` : "Add competitor pace"),
    cardMarkup("Resale support", formatCurrency(summary.avgResalePpsf, 0), summary.avgResalePpsf ? "Average resale price per foot" : "Add recent resales"),
  ];
  snapshotGrid.innerHTML = cards.join("");
}

function renderBuilder() {
  renderRootFields();
  Object.keys(LIST_CONFIG).forEach(renderList);
  renderSnapshot();
  fileMeta.textContent = `Deal file: ${state.fileName}`;
}

function memoTextFromResult() {
  const memo = state.result?.investment_committee_memo;
  if (!memo) {
    return "Run the underwrite to generate a decision memo.";
  }

  const lines = [memo.headline || "Investment committee memo", ""];
  if (memo.summary) {
    lines.push(memo.summary, "");
  }
  if (memo.strengths?.length) {
    lines.push("Strengths:");
    memo.strengths.forEach((item) => lines.push(`- ${item}`));
    lines.push("");
  }
  if (memo.risks?.length) {
    lines.push("Risks:");
    memo.risks.forEach((item) => lines.push(`- ${item}`));
    lines.push("");
  }
  if (memo.next_steps?.length) {
    lines.push("Next steps:");
    memo.next_steps.forEach((item) => lines.push(`- ${item}`));
    lines.push("");
  }
  if (memo.reason_snapshot?.length) {
    lines.push("Decision snapshot:");
    memo.reason_snapshot.forEach((item) => lines.push(`- ${item}`));
  }
  return lines.join("\n").trim();
}

function renderRecommendation() {
  const result = state.result;
  if (!result) {
    recommendationBanner.className = "recommendation-banner idle";
    recommendationBanner.innerHTML = `
      <strong>Run the underwrite to build the decision packet.</strong>
      <span>The banner, scenario view, market read, and memo will populate here.</span>
    `;
    return;
  }

  const score = result.deal_score?.score != null ? `${result.deal_score.score}/100` : "Unscored";
  const reasons = (result.recommendation_reasons || []).slice(0, 3).join(" | ");
  recommendationBanner.className = `recommendation-banner ${escapeHtml(result.recommendation || "idle")}`;
  recommendationBanner.innerHTML = `
    <strong>${escapeHtml(String(result.recommendation || "watch").toUpperCase())} | Deal score ${escapeHtml(score)}</strong>
    <span>${escapeHtml(reasons || "Review the scenario deck and market layer before deciding.")}</span>
  `;
}

function renderHeadlineMetrics() {
  const result = state.result;
  if (!result?.scenarios?.base_case) {
    headlineGrid.innerHTML = "";
    return;
  }

  const base = result.scenarios.base_case;
  const investment = base.investment_summary || {};
  const income = base.income_statement || {};
  const cash = base.cash_flow_metrics || {};
  const schedule = base.schedule || {};

  headlineGrid.innerHTML = [
    cardMarkup("Gross margin", formatPct(income.gross_margin_pct), formatCurrency(income.gross_margin)),
    cardMarkup("Pre-G&A", formatPct(income.pre_gna_margin_pct), formatCurrency(income.pre_gna_contribution)),
    cardMarkup("IRR", formatPct(cash.irr_pre_gna_pct), "Pre-G&A cash flow view"),
    cardMarkup("Residual / lot", formatCurrency(investment.residual_max_land_cost_per_lot), formatCurrency(investment.land_value_gap_to_residual, 0) + " gap"),
    cardMarkup("Peak investment", formatCurrency(cash.peak_investment), `Month ${formatNumber(cash.peak_investment_month, 0)}`),
    cardMarkup("Sellout", formatNumber(schedule.sellout_months, 0) + " months", schedule.date_summary?.last_close_date || "Date not set"),
  ].join("");
}

function renderScenarios() {
  const result = state.result;
  if (!result?.scenarios) {
    scenarioGrid.innerHTML = '<div class="placeholder-block">Run the underwrite to compare base, downside, and severe downside scenarios.</div>';
    return;
  }

  const order = ["base_case", "downside_case", "severe_downside_case"];
  const cards = order
    .filter((key) => result.scenarios[key])
    .map((key) => {
      const scenario = result.scenarios[key];
      const income = scenario.income_statement || {};
      const cash = scenario.cash_flow_metrics || {};
      const investment = scenario.investment_summary || {};
      const adjustments = scenario.scenario_adjustments || {};
      const label = key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
      return `
        <article class="scenario-card">
          <h4>${escapeHtml(label)}</h4>
          <div class="scenario-stat"><span>Price move</span><strong>${escapeHtml(formatPct(adjustments.sales_price_delta_pct))}</strong></div>
          <div class="scenario-stat"><span>Cost move</span><strong>${escapeHtml(formatPct(adjustments.cost_delta_pct))}</strong></div>
          <div class="scenario-stat"><span>Pace move</span><strong>${escapeHtml(formatPct(adjustments.absorption_delta_pct))}</strong></div>
          <div class="scenario-stat"><span>Gross margin</span><strong>${escapeHtml(formatPct(income.gross_margin_pct))}</strong></div>
          <div class="scenario-stat"><span>Pre-G&amp;A</span><strong>${escapeHtml(formatPct(income.pre_gna_margin_pct))}</strong></div>
          <div class="scenario-stat"><span>IRR</span><strong>${escapeHtml(formatPct(cash.irr_pre_gna_pct))}</strong></div>
          <div class="scenario-stat"><span>Residual gap</span><strong>${escapeHtml(formatCurrency(investment.land_value_gap_to_residual, 0))}</strong></div>
        </article>
      `;
    });

  scenarioGrid.innerHTML = `<div class="scenario-grid">${cards.join("")}</div>`;
}

function renderSchedule() {
  const result = state.result;
  const payload = dealPayload();
  const phases = payload.schedule_phases || [];
  if (!phases.length && !result?.scenarios?.base_case?.schedule) {
    scheduleView.innerHTML = '<div class="placeholder-block">Add phases or run the deal to see the schedule view.</div>';
    return;
  }

  const phaseMarkup = phases.length
    ? `
      <div class="timeline-strip">
        ${phases
          .map(
            (phase) => `
              <article class="timeline-item">
                <div class="timeline-head">
                  <span>${escapeHtml(phase.name || "Phase")}</span>
                  <span>Month ${escapeHtml(String(phase.month || 0))}</span>
                </div>
                <div class="timeline-note">${escapeHtml(formatNumber(phase.lots, 0))} lots | ${escapeHtml(formatCurrency(phase.price_per_lot))} / lot</div>
              </article>
            `
          )
          .join("")}
      </div>
    `
    : "";

  const schedule = result?.scenarios?.base_case?.schedule || {};
  const dateSummary = schedule.date_summary || {};
  const milestones = [
    ["First home start", dateSummary.first_home_start_date],
    ["Sales open", dateSummary.sales_open_date],
    ["First close", dateSummary.first_close_date],
    ["Peak investment", dateSummary.peak_investment_date],
    ["Last close", dateSummary.last_close_date],
  ].filter(([, value]) => value);

  const milestoneMarkup = milestones.length
    ? `
      <div class="timeline-strip">
        ${milestones
          .map(
            ([label, value]) => `
              <article class="timeline-item">
                <div class="timeline-head">
                  <span>${escapeHtml(label)}</span>
                  <span>${escapeHtml(String(value))}</span>
                </div>
                <div class="timeline-note">
                  ${escapeHtml(formatNumber(schedule.sellout_months, 0))} month sellout | ${escapeHtml(formatNumber(schedule.total_project_months, 0))} total project months
                </div>
              </article>
            `
          )
          .join("")}
      </div>
    `
    : '<div class="placeholder-block">Milestones will appear after the underwrite runs.</div>';

  scheduleView.innerHTML = `${phaseMarkup}${milestoneMarkup}`;
}

function renderMarket() {
  const market = state.result?.market_intelligence;
  if (!market) {
    marketView.innerHTML = '<div class="placeholder-block">Add competitors or resale comps, then run the underwrite to see price, pace, and revenue positioning.</div>';
    return;
  }

  const positioning = market.positioning || {};
  const subject = market.subject || {};
  const competitors = market.competitors || {};
  const resales = market.resales || {};
  const revenueRows = [
    { label: "Subject", value: subject.revenue_per_month, subject: true },
    ...((competitors.rows || []).slice(0, 4).map((item) => ({ label: item.name, value: item.revenue_per_month, subject: false }))),
  ].filter((row) => row.value != null);
  const maxRevenue = Math.max(...revenueRows.map((row) => Number(row.value) || 0), 1);

  marketView.innerHTML = `
    <div class="market-cards">
      ${cardMarkup("Subject net price", formatCurrency(subject.average_net_price), formatCurrency(subject.price_psf, 0) + " / sqft")}
      ${cardMarkup("Competitor average", formatCurrency(competitors.average_price), formatNumber(competitors.average_absorption, 2) + " / month")}
      ${cardMarkup("Price gap", formatPct(positioning.subject_vs_competitor_price_pct), "Subject vs competitor average")}
      ${cardMarkup("Pace gap", formatPct(positioning.subject_vs_competitor_absorption_pct), "Subject vs competitor absorption")}
      ${cardMarkup("Resale PPSF gap", formatPct(positioning.subject_vs_resale_psf_pct), formatCurrency(resales.average_price_psf, 0) + " resale PPSF")}
      ${cardMarkup("Competitor count", formatNumber(competitors.count, 0), formatNumber(resales.count, 0) + " resale comps")}
    </div>

    <div class="pill-row">
      ${(market.upside_flags || []).map((item) => `<span class="signal-pill good">${escapeHtml(item)}</span>`).join("")}
      ${(market.risk_flags || []).map((item) => `<span class="signal-pill risk">${escapeHtml(item)}</span>`).join("")}
    </div>

    <div class="split-panel">
      <div>
        <h4>Revenue velocity</h4>
        <div class="revenue-bars">
          ${revenueRows
            .map(
              (row) => `
                <div class="bar-row">
                  <div class="bar-meta">
                    <span>${escapeHtml(row.label)}</span>
                    <strong>${escapeHtml(formatCurrency(row.value, 0))}</strong>
                  </div>
                  <div class="bar-track">
                    <div class="bar-fill ${row.subject ? "subject" : ""}" style="width:${((Number(row.value) || 0) / maxRevenue) * 100}%"></div>
                  </div>
                </div>
              `
            )
            .join("")}
        </div>
      </div>

      <div>
        <h4>Resale support</h4>
        ${
          resales.rows?.length
            ? `<div class="resale-stack">
                ${resales.rows
                  .slice(0, 5)
                  .map(
                    (item) => `
                      <article class="resale-item">
                        <strong>${escapeHtml(item.name)}</strong>
                        <span>${escapeHtml(formatCurrency(item.close_price))} | ${escapeHtml(formatCurrency(item.price_psf, 0))} / sqft</span><br />
                        <span>${escapeHtml(formatNumber(item.distance_miles, 1))} miles | ${escapeHtml(item.close_date || "Date n/a")}</span>
                      </article>
                    `
                  )
                  .join("")}
              </div>`
            : '<div class="placeholder-block">No resale comps supplied.</div>'
        }
      </div>
    </div>
  `;
}

function renderSensitivity() {
  const matrix = state.result?.sensitivity_matrix;
  if (!matrix?.rows?.length) {
    sensitivityView.innerHTML = '<div class="placeholder-block">Run the underwrite to see the sensitivity matrix.</div>';
    return;
  }

  const counts = { clear: 0, watch: 0, fail: 0 };
  matrix.rows.forEach((row) => row.cells.forEach((cell) => {
    counts[cell.status] = (counts[cell.status] || 0) + 1;
  }));

  const headers = (matrix.price_deltas_pct || [])
    .map((value) => `<th>${escapeHtml(formatPct(value))} price</th>`)
    .join("");
  const rows = (matrix.rows || [])
    .map(
      (row) => `
        <tr>
          <th>${escapeHtml(formatPct(row.cost_delta_pct))} cost</th>
          ${(row.cells || [])
            .map(
              (cell) => `
                <td class="status-${escapeHtml(cell.status || "fail")}">
                  <div class="sensitivity-cell">
                    <strong>${escapeHtml(String(cell.status || "fail").toUpperCase())}</strong>
                    <span>${escapeHtml(formatPct(cell.pre_gna_margin_pct))}</span>
                    <small>${escapeHtml(formatPct(cell.irr_pre_gna_pct))} IRR</small>
                  </div>
                </td>
              `
            )
            .join("")}
        </tr>
      `
    )
    .join("");

  sensitivityView.innerHTML = `
    <div class="sensitivity-summary">
      ${cardMarkup("Clear cells", formatNumber(counts.clear, 0), "Meets hurdles")}
      ${cardMarkup("Watch cells", formatNumber(counts.watch || 0, 0), "Near the line")}
      ${cardMarkup("Fail cells", formatNumber(counts.fail, 0), "Misses hurdles")}
    </div>
    <div class="sensitivity-table">
      <table>
        <thead>
          <tr>
            <th>Cost \\ Price</th>
            ${headers}
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderMemo() {
  memoPreview.textContent = memoTextFromResult();
}

function renderResults() {
  renderRecommendation();
  renderHeadlineMetrics();
  renderScenarios();
  renderSchedule();
  renderMarket();
  renderSensitivity();
  renderMemo();
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data?.detail || `Request failed with status ${response.status}`);
  }
  return data;
}

async function copyText(text, successMessage) {
  if (!text || text.startsWith("Run the underwrite")) {
    setRunStatus("There is no memo to copy yet.");
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

function blankRowForGroup(group) {
  const config = LIST_CONFIG[group];
  const existing = rowCollection(group).length + 1;
  return rowDefaults(config.fields, `${config.title} ${existing}`);
}

function addRow(group) {
  state.deal[group].push(blankRowForGroup(group));
  persistDraft();
  renderList(group);
  renderSnapshot();
}

function removeRow(group, index) {
  state.deal[group].splice(index, 1);
  if (!state.deal[group].length) {
    state.deal[group].push(blankRowForGroup(group));
  }
  persistDraft();
  renderList(group);
  renderSnapshot();
}

function handleRootInput(event) {
  const key = event.target.dataset.rootField;
  if (!key) {
    return;
  }
  state.deal[key] = event.target.type === "checkbox" ? event.target.checked : event.target.value;
  persistDraft();
  renderSnapshot();
}

function handleListInput(event) {
  const field = event.target.dataset.field;
  const group = event.target.dataset.group;
  const index = Number(event.target.dataset.index);
  if (!field || !group || !Number.isInteger(index)) {
    return;
  }
  state.deal[group][index][field] = event.target.type === "checkbox" ? event.target.checked : event.target.value;
  persistDraft();
  renderSnapshot();
}

function handleListClick(event) {
  const removeButton = event.target.closest("[data-remove-row]");
  if (!removeButton) {
    return;
  }
  removeRow(removeButton.dataset.removeRow, Number(removeButton.dataset.index));
}

async function refreshAgents() {
  setAppState("Refreshing", "warning");
  try {
    const payload = await fetchJson(`${API_BASE}/agents`);
    populateAgents(payload.agents || [], state.startPayload?.default_agent_dir || "");
    persistDraft();
    setAppState("Ready", "idle");
    setRunStatus("Model list refreshed.");
  } catch (error) {
    setAppState("Error", "danger");
    setRunStatus(error.message);
  }
}

function loadStarterDeal() {
  state.deal = normalizeDeal(state.startPayload?.starter_deal || {});
  state.result = null;
  state.fileName = state.startPayload?.starter_file_name || "starter_deal.landdeal";
  persistDraft();
  renderBuilder();
  renderResults();
  setRunStatus("Starter deal loaded.");
}

function saveDealFile() {
  const deal = dealPayload();
  const blob = new Blob([JSON.stringify(deal, null, 2)], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${slugify(state.deal.community_name || "land-deal")}.landdeal`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  setRunStatus("Deal file downloaded.");
}

async function loadDealFile(file) {
  if (!file) {
    return;
  }
  try {
    const parsed = JSON.parse(await file.text());
    state.deal = normalizeDeal(parsed);
    state.result = null;
    state.fileName = file.name || "opened_deal.landdeal";
    persistDraft();
    renderBuilder();
    renderResults();
    setRunStatus("Deal file loaded.");
  } catch (error) {
    setRunStatus("That deal file could not be opened.");
  }
}

async function runUnderwrite() {
  setAppState("Running", "warning");
  setRunStatus("Running the workbook underwrite.");
  try {
    const result = await fetchJson(`${API_BASE}/underwrite`, {
      method: "POST",
      body: JSON.stringify({
        agent_dir: state.selectedAgent || null,
        deal: dealPayload(),
      }),
    });
    state.result = result;
    renderResults();
    setAppState("Ready", "success");
    setRunStatus(`Recommendation ready: ${(result.recommendation || "watch").toUpperCase()}.`);
  } catch (error) {
    setAppState("Error", "danger");
    setRunStatus(error.message);
  }
}

async function loadStartData() {
  setAppState("Loading", "warning");
  setRunStatus("Loading the mobile underwriter.");

  try {
    state.startPayload = await fetchJson(`${API_BASE}/start`);
    const restored = restoreDraft();
    state.fileName = state.fileName || state.startPayload.starter_file_name || "starter_deal.landdeal";
    state.deal = restored || normalizeDeal(state.startPayload.starter_deal || {});
    populateAgents(state.startPayload.agents || [], state.startPayload.default_agent_dir || "");
    renderBuilder();
    renderResults();
    setAppState("Ready", "idle");
    setRunStatus("Deal workspace ready.");
  } catch (error) {
    setAppState("Error", "danger");
    setRunStatus(error.message || "The underwriter could not start.");
  }
}

rootInputs.forEach((input) => {
  const eventName = input.type === "checkbox" || input.tagName === "SELECT" ? "change" : "input";
  input.addEventListener(eventName, handleRootInput);
});

Object.values(LIST_CONFIG).forEach((config) => {
  const container = document.getElementById(config.containerId);
  container.addEventListener("input", handleListInput);
  container.addEventListener("change", handleListInput);
  container.addEventListener("click", handleListClick);
});

document.querySelectorAll("[data-add-row]").forEach((button) => {
  button.addEventListener("click", () => addRow(button.dataset.addRow));
});

agentSelect.addEventListener("change", () => {
  state.selectedAgent = agentSelect.value || "";
  persistDraft();
  updateAgentMeta();
});

document.getElementById("refreshAgentsBtn").addEventListener("click", refreshAgents);
document.getElementById("loadStarterBtn").addEventListener("click", loadStarterDeal);
document.getElementById("openDealBtn").addEventListener("click", () => dealFileInput.click());
dealFileInput.addEventListener("change", async (event) => {
  await loadDealFile(event.target.files?.[0]);
  dealFileInput.value = "";
});
document.getElementById("saveDealBtn").addEventListener("click", saveDealFile);
document.getElementById("runUnderwriteBtn").addEventListener("click", runUnderwrite);
document.getElementById("copyMemoBtn").addEventListener("click", () => copyText(memoTextFromResult(), "IC memo copied."));
document.getElementById("copyMemoInline").addEventListener("click", () => copyText(memoTextFromResult(), "IC memo copied."));

loadStartData();
