const STORAGE_KEY = "homebuilder-suite-backend-url";
const backendUrlInput = document.getElementById("backendUrlInput");
const connectBtn = document.getElementById("connectBtn");
const resetBtn = document.getElementById("resetBtn");
const openExternalBtn = document.getElementById("openExternalBtn");
const workspaceFrame = document.getElementById("workspaceFrame");
const framePlaceholder = document.getElementById("framePlaceholder");
const activeRouteLabel = document.getElementById("activeRouteLabel");
const statusPill = document.getElementById("statusPill");
const connectionHint = document.getElementById("connectionHint");
const tabButtons = Array.from(document.querySelectorAll(".tab-button"));

let activeRoute = "/underwrite/";

function normalizeBackendUrl(value) {
  const raw = String(value || "").trim().replace(/\/+$/, "");
  if (!raw) {
    return "";
  }
  if (/^https?:\/\//i.test(raw)) {
    return raw;
  }
  return `http://${raw}`;
}

function currentUrl() {
  const base = normalizeBackendUrl(backendUrlInput.value);
  return base ? `${base}${activeRoute}` : "";
}

function persistBackendUrl() {
  localStorage.setItem(STORAGE_KEY, normalizeBackendUrl(backendUrlInput.value));
}

function updateStatus(connected) {
  statusPill.textContent = connected ? "Connected" : "Not connected";
  statusPill.className = connected ? "status-pill connected" : "status-pill";
}

function updateFrame() {
  const url = currentUrl();
  activeRouteLabel.textContent = activeRoute;
  if (!url) {
    workspaceFrame.removeAttribute("src");
    framePlaceholder.classList.remove("hidden");
    updateStatus(false);
    connectionHint.textContent = "Start the backend on your computer first, then paste the phone-suite URL here.";
    return;
  }

  framePlaceholder.classList.add("hidden");
  workspaceFrame.src = url;
  updateStatus(true);
  connectionHint.textContent = `Loading ${url}`;
}

function setActiveRoute(route) {
  activeRoute = route;
  tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.route === route);
  });
  updateFrame();
}

connectBtn.addEventListener("click", () => {
  backendUrlInput.value = normalizeBackendUrl(backendUrlInput.value);
  persistBackendUrl();
  updateFrame();
});

resetBtn.addEventListener("click", () => {
  backendUrlInput.value = "";
  localStorage.removeItem(STORAGE_KEY);
  updateFrame();
});

openExternalBtn.addEventListener("click", () => {
  const url = currentUrl();
  if (!url) {
    return;
  }
  window.open(url, "_blank");
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => setActiveRoute(button.dataset.route));
});

backendUrlInput.value = localStorage.getItem(STORAGE_KEY) || "";
setActiveRoute(activeRoute);
