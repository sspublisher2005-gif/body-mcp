/* Popup: connect / disconnect the CURRENT tab and show the extension id the user
 * has to allow on the Body-MCP side (python -m body_mcp.bridge --allow-extension-id). */
function send(action, extra) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(Object.assign({ action: action }, extra || {}), resolve);
  });
}

async function refresh() {
  const status = await send("status");
  const state = document.getElementById("state");
  const info = document.getElementById("status");
  const id = document.getElementById("extid");
  id.textContent = "extension id: " + (status && status.extensionId ? status.extensionId : "?");
  const rem = document.getElementById("remember");
  rem.textContent = status && status.remembered
    ? "will reattach automatically to: " + (status.remembered.title || status.remembered.url)
    : "not remembered — click Connect this tab once to grant permanent access to this tab";
  if (!status || !status.attached) {
    state.textContent = "not connected";
    state.style.color = "#9fb0c6";
    info.textContent = status && status.error ? status.error : "";
    info.className = status && status.error ? "id err" : "id";
    return;
  }
  const tab = (status.tabs || []).find((t) => t.connected);
  state.textContent = "connected" + (tab ? ": " + (tab.title || tab.url) : "");
  state.style.color = "#8fd6a0";
  info.textContent = (status.tabs || [])
    .map((t) => (t.connected ? "* " : "  ") + (t.title || t.url))
    .join("\n");
  info.className = "id";
  info.style.whiteSpace = "pre";
}

document.getElementById("connect").addEventListener("click", async () => {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs.length) return;
  const result = await send("connect", { tabId: tabs[0].id });
  if (result && !result.ok) {
    document.getElementById("status").textContent = "could not attach: " + result.error;
    document.getElementById("status").className = "id err";
  }
  refresh();
});

document.getElementById("disconnect").addEventListener("click", async () => {
  await send("disconnect");
  refresh();
});

refresh();
