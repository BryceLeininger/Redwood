const chat = document.getElementById("chat");
const composer = document.getElementById("composer");
const input = document.getElementById("messageInput");

function addBubble(role, text, data = null) {
  const bubble = document.createElement("article");
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;

  if (data) {
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data, null, 2);
    bubble.appendChild(pre);
  }

  chat.appendChild(bubble);
  chat.scrollTop = chat.scrollHeight;
}

async function callApi(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API request failed (${response.status}): ${text}`);
  }
  return response.json();
}

async function startSession() {
  try {
    const payload = await callApi("/api/start", {});
    addBubble("agent", payload.reply, payload.data || null);
  } catch (error) {
    addBubble("agent", `Startup error: ${error.message}`);
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) {
    return;
  }

  addBubble("user", message);
  input.value = "";
  input.focus();

  const button = composer.querySelector("button");
  button.disabled = true;

  try {
    const payload = await callApi("/api/message", { message });
    addBubble("agent", payload.reply, payload.data || null);
  } catch (error) {
    addBubble("agent", `Error: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});

startSession();
