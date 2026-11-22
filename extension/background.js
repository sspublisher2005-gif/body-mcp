/* Body-MCP bridge - background service worker.

 * PERMANENT, CONSENT-BASED ROUTE TO THE USER'S OWN BROWSER:
 * - The user clicks "Connect this tab" ONCE. That is the consent.
 * - We save the exact tab URL in chrome.storage.local (persists across browser
 *   restarts) and reattach automatically on startup / tab restore.
 * - The user can revoke any time with "Disconnect & forget".
 * - Nothing else happens on its own: no page is read until Body-MCP asks, and
 *   Chromium still shows its own "debugging this browser" bar.
 *
 * Works in any Chromium-based browser (Chrome, Edge, Brave, Vivaldi, Opera).
 */
const HOST = "body_mcp_bridge";
const POLL_MS = 300;
const STORE_KEY = "rememberedTab"; // {url, title}

let attachedTabId = null;
let polling = false;
let lastError = "";
let restoring = false;

function log(...args) { console.log("[body-mcp-bridge]", ...args); }

async function remember(tab) {
  await chrome.storage.local.set({ [STORE_KEY]: { url: tab.url || "", title: tab.title || "" } });
}
async function forget() {
  await chrome.storage.local.remove(STORE_KEY);
}
async function remembered() {
  return (await chrome.storage.local.get(STORE_KEY))[STORE_KEY] || null;
}

async function attachTab(tabId, rememberIt = false) {
  if (attachedTabId === tabId) return { ok: true, already: true };
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
    attachedTabId = tabId;
    lastError = "";
    if (rememberIt) {
      const tabs = await chrome.tabs.query({ id: tabId });
      if (tabs.length) await remember(tabs[0]);
    }
    log("attached to tab", tabId, rememberIt ? "(remembered)" : "");
    await send({ type: "hello", extension_id: chrome.runtime.id, tabs: await tabInfo() });
    startPolling();
    return { ok: true };
  } catch (err) {
    lastError = String(err && err.message ? err.message : err);
    return { ok: false, error: lastError };
  }
}

async function restore() {
  if (attachedTabId !== null || restoring) return;
  const saved = await remembered();
  if (!saved || !saved.url) return;
  restoring = true;
  try {
    // Find the user's tab again after a browser restart (tab IDs change).
    const tabs = await chrome.tabs.query({});
    const match = tabs.find((t) => t.url === saved.url) ||
                  tabs.find((t) => t.url && saved.url && new URL(t.url).origin === new URL(saved.url).origin);
    if (match && match.id != null) {
      const result = await attachTab(match.id, true);
      log("auto-reattach:", result.ok ? "ok" : result.error);
    }
  } catch (err) {
    log("restore failed:", String(err));
  } finally {
    restoring = false;
  }
}

async function detachTab(forgetIt = false) {
  if (attachedTabId !== null) {
    try { await chrome.debugger.detach({ tabId: attachedTabId }); } catch (err) { /* gone */ }
  }
  const was = attachedTabId;
  attachedTabId = null;
  stopPolling();
  if (forgetIt) await forget();
  await send({ type: "tabs", tabs: [] });
  return { ok: true, detached: was !== null, forgotten: forgetIt };
}

async function tabInfo() {
  const tabs = await chrome.tabs.query({});
  return tabs.map((t) => ({ id: t.id, title: t.title || "", url: t.url || "",
                             active: !!t.active, connected: t.id === attachedTabId }));
}

async function send(message) {
  try { return await chrome.runtime.sendNativeMessage(HOST, message); }
  catch (err) { lastError = String(err && err.message ? err.message : err); return null; }
}

function startPolling() {
  if (polling) return;
  polling = true;
  (async () => {
    while (polling) {
      let reply = null;
      try { reply = await chrome.runtime.sendNativeMessage(HOST, { type: "poll" }); }
      catch (err) { lastError = String(err && err.message ? err.message : err); }
      if (reply && reply.command) {
        try {
          const result = await runCommand(reply.command);
          await send({ type: "result", task_id: reply.command.task_id, result });
        } catch (err) {
          await send({ type: "result", task_id: reply.command.task_id,
                       result: { ok: false, error: String(err && err.message ? err.message : err) } });
        }
      }
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
  })();
}
function stopPolling() { polling = false; }

async function runCommand(command) {
  if (attachedTabId === null) return { ok: false, error: "no tab connected" };
  const taskId = command.task_id;
  if (command.cmd === "navigate") {
    await chrome.debugger.sendCommand({ tabId: attachedTabId }, "Page.navigate", { url: command.url });
    return { ok: true, navigated: command.url, task_id: taskId };
  }
  if (command.cmd === "read") {
    const result = await chrome.debugger.sendCommand({ tabId: attachedTabId }, "Runtime.evaluate", {
      expression: "JSON.stringify({title: document.title, url: location.href, text: (document.body ? document.body.innerText : '').slice(0, 20000)})",
      returnByValue: true });
    let payload = {};
    try { payload = JSON.parse(result.result.value || "{}"); }
    catch (err) { payload = { text: String(result.result.value || "") }; }
    return { ok: true, title: payload.title, url: payload.url, text: payload.text, task_id: taskId };
  }
  if (command.cmd === "screenshot") {
    const shot = await chrome.debugger.sendCommand({ tabId: attachedTabId }, "Page.captureScreenshot", { format: "png" });
    return { ok: true, png_base64: shot.data, task_id: taskId };
  }
  if (command.cmd === "detach") {
    await detachTab(true);
    return { ok: true, detached: true, task_id: taskId };
  }
  return { ok: false, error: "unknown command", task_id: taskId };
}

// Reattach after the browser or the service worker restarts.
chrome.runtime.onStartup.addListener(() => { restore(); });
chrome.runtime.onInstalled.addListener(() => { restore(); });
chrome.tabs.onUpdated.addListener((id, change, tab) => {
  const saved = null; // cheap check below only when we are not attached
  if (attachedTabId === null) restore();
});
chrome.debugger.onDetach.addListener(() => {
  attachedTabId = null; stopPolling();
  setTimeout(() => restore(), 1500); // browser may still be restoring the tab
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message && message.action === "connect") {
      sendResponse(await attachTab(message.tabId, true)); return true;   // consent: remember
    }
    if (message && message.action === "disconnect") {
      sendResponse(await detachTab(true)); return true;                 // revoke: forget
    }
    if (message && message.action === "restore") {
      await restore(); sendResponse({ ok: attachedTabId !== null }); return true;
    }
    if (message && message.action === "status") {
      sendResponse({ ok: true, attached: attachedTabId !== null, tabId: attachedTabId,
                     extensionId: chrome.runtime.id,
                     remembered: await remembered(), tabs: await tabInfo(), error: lastError });
      return true;
    }
    sendResponse({ ok: false, error: "unknown action" }); return true;
  })();
  return true;
});
