/* Body-MCP bridge - background service worker.
 *
 * The user clicks "Connect this tab" in the popup. That attaches the Chrome
 * debugger to that tab (Chromium shows its own "debugging this browser" bar, which
 * the user can cancel at any moment) and starts polling the native host for
 * commands. Nothing else happens on its own: no page is read until Body-MCP asks.
 */
const HOST = "body_mcp_bridge";
const POLL_MS = 300;

let attachedTabId = null;
let polling = false;
let lastError = "";

function log(...args) {
  console.log("[body-mcp-bridge]", ...args);
}

async function attachTab(tabId) {
  if (attachedTabId === tabId) return { ok: true, already: true };
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
    attachedTabId = tabId;
    lastError = "";
    log("attached to tab", tabId);
    await send({ type: "hello", extension_id: chrome.runtime.id, tabs: await tabInfo() });
    startPolling();
    return { ok: true };
  } catch (err) {
    lastError = String(err && err.message ? err.message : err);
    return { ok: false, error: lastError };
  }
}

async function detachTab() {
  if (attachedTabId === null) return { ok: true, detached: false };
  try {
    await chrome.debugger.detach({ tabId: attachedTabId });
  } catch (err) {
    /* already gone */
  }
  attachedTabId = null;
  stopPolling();
  await send({ type: "tabs", tabs: [] });
  return { ok: true, detached: true };
}

async function tabInfo() {
  const tabs = await chrome.tabs.query({});
  return tabs.map((t) => ({
    id: t.id,
    title: t.title || "",
    url: t.url || "",
    active: !!t.active,
    connected: t.id === attachedTabId,
  }));
}

async function send(message) {
  try {
    return await chrome.runtime.sendNativeMessage(HOST, message);
  } catch (err) {
    lastError = String(err && err.message ? err.message : err);
    return null;
  }
}

function startPolling() {
  if (polling) return;
  polling = true;
  (async () => {
    while (polling) {
      let reply = null;
      try {
        reply = await chrome.runtime.sendNativeMessage(HOST, { type: "poll" });
      } catch (err) {
        lastError = String(err && err.message ? err.message : err);
      }
      if (reply && reply.command) {
        try {
          const result = await runCommand(reply.command);
          await send({ type: "result", task_id: reply.command.task_id, result });
        } catch (err) {
          await send({
            type: "result",
            task_id: reply.command.task_id,
            result: { ok: false, error: String(err && err.message ? err.message : err) },
          });
        }
      }
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
  })();
}

function stopPolling() {
  polling = false;
}

async function runCommand(command) {
  const taskId = command.task_id;
  if (command.cmd === "navigate") {
    await chrome.debugger.sendCommand({ tabId: attachedTabId }, "Page.navigate", {
      url: command.url,
    });
    return { ok: true, navigated: command.url, task_id: taskId };
  }
  if (command.cmd === "read") {
    const result = await chrome.debugger.sendCommand(
      { tabId: attachedTabId },
      "Runtime.evaluate",
      {
        expression:
          "JSON.stringify({title: document.title, url: location.href, text: (document.body ? document.body.innerText : '').slice(0, 20000)})",
        returnByValue: true,
      }
    );
    let payload = {};
    try {
      payload = JSON.parse(result.result.value || "{}");
    } catch (err) {
      payload = { text: String(result.result.value || "") };
    }
    return { ok: true, title: payload.title, url: payload.url, text: payload.text, task_id: taskId };
  }
  if (command.cmd === "screenshot") {
    const shot = await chrome.debugger.sendCommand(
      { tabId: attachedTabId },
      "Page.captureScreenshot",
      { format: "png" }
    );
    return { ok: true, png_base64: shot.data, task_id: taskId };
  }
  if (command.cmd === "detach") {
    await detachTab();
    return { ok: true, detached: true, task_id: taskId };
  }
  return { ok: false, error: "unknown command", task_id: taskId };
}

chrome.debugger.onDetach.addListener((source) => {
  log("detached:", source);
  attachedTabId = null;
  stopPolling();
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message && message.action === "connect") {
      sendResponse(await attachTab(message.tabId));
      return true;
    }
    if (message && message.action === "disconnect") {
      sendResponse(await detachTab());
      return true;
    }
    if (message && message.action === "status") {
      sendResponse({
        ok: true,
        attached: attachedTabId !== null,
        tabId: attachedTabId,
        extensionId: chrome.runtime.id,
        tabs: await tabInfo(),
        error: lastError,
      });
      return true;
    }
    sendResponse({ ok: false, error: "unknown action" });
    return true;
  })();
  return true;
});
