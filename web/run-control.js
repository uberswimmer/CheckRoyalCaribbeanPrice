/* Fixed LAN check action. Remote report content is never interpreted as code. */
(() => {
  "use strict";
  const panel = document.getElementById("run-control");
  if (!panel) return;
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Run check now";
  button.disabled = true;
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  panel.append(button, status);
  let token = "", seenRun = null, wasRunning = false, submitting = false;
  let refreshing = false;

  async function request(options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch("/api/check", {
        ...options, cache: "no-store", signal: controller.signal
      });
      return {code: response.status, data: await response.json()};
    } finally {
      clearTimeout(timeout);
    }
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const {code, data} = await request();
      if (code !== 200) throw new Error("Status unavailable");
      token = data.token;
      panel.hidden = false;
      const running = data.state === "running";
      if (!running && (wasRunning || (seenRun && seenRun !== data.runId))) {
        window.location.reload();
        return;
      }
      seenRun = data.runId;
      wasRunning = running;
      const labels = {idle: "Ready to run a check.", running: "Check running. The report will refresh when it finishes.",
        completed: "Last check completed.", failed: "Last check failed. Review the report or container logs.",
        interrupted: "The previous check was interrupted. Its saved report may be incomplete."};
      status.textContent = labels[data.state] || "Check status unavailable.";
      if (!running && data.retryAfter > 0) status.textContent += ` You can run another check in ${data.retryAfter} seconds.`;
      button.disabled = submitting || running || data.retryAfter > 0;
    } catch (_) {
      button.disabled = true;
      status.textContent = "Run controls unavailable. Check the checker container if this persists.";
    } finally {
      refreshing = false;
    }
  }

  button.addEventListener("click", async () => {
    if (button.disabled || submitting) return;
    submitting = true;
    button.disabled = true;
    status.textContent = "Starting check…";
    try {
      const {code, data} = await request({method: "POST", headers: {"X-CSRF-Token": token}});
      if (code === 202) {
        seenRun = data.runId;
        wasRunning = true;
      } else if (code !== 409 && code !== 429) {
        status.textContent = data.error || "Unable to start check.";
      }
    } catch (_) {
      status.textContent = "Could not confirm the request. Checking whether a run started…";
    } finally {
      submitting = false;
      await refresh();
    }
  });
  setInterval(refresh, 5000);
  refresh();
})();
