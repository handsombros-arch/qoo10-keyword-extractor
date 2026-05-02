async function refresh() {
  const status = await new Promise((resolve) =>
    chrome.runtime.sendMessage({ type: "GET_STATUS" }, resolve),
  );

  const badge = document.getElementById("status-badge");
  if (status.isRunning) {
    badge.textContent = "작업 중";
    badge.className = "badge working";
  } else {
    badge.textContent = "대기 중";
    badge.className = "badge idle";
  }

  document.getElementById("job-id").textContent = status.job_id || "없음";

  if (status.total > 0) {
    const pct = Math.round((status.index / status.total) * 100);
    document.getElementById("progress").textContent =
      `${status.index} / ${status.total} (${pct}%)`;
  } else {
    document.getElementById("progress").textContent = "—";
  }

  document.getElementById("success-error").textContent =
    `${status.successCount} / ${status.errorCount}`;

  const ul = document.getElementById("recent-list");
  ul.innerHTML = "";
  if (!status.recent || status.recent.length === 0) {
    ul.innerHTML = '<li class="empty">없음</li>';
  } else {
    for (const r of status.recent.slice().reverse()) {
      const li = document.createElement("li");
      li.className = r.status === "ok" ? "ok" : "err";
      const mark = r.status === "ok" ? "✓" : "✗";
      const ms = `${r.ms}ms`;
      const url = r.url.length > 50 ? r.url.slice(0, 50) + "…" : r.url;
      const errPart = r.error ? ` — ${r.error.slice(0, 60)}` : "";
      li.textContent = `${mark} ${ms} · ${url}${errPart}`;
      ul.appendChild(li);
    }
  }

  const errEl = document.getElementById("last-error");
  errEl.textContent = status.lastError ? `최근 오류: ${status.lastError}` : "";

  // 백엔드 ping
  chrome.runtime.sendMessage({ type: "PING_BACKEND" }, (r) => {
    const el = document.getElementById("backend-status");
    if (r?.ok) {
      el.textContent = `연결됨 (${r.status})`;
      el.className = "value ok";
    } else {
      el.textContent = `연결 실패: ${r?.error || "?"}`;
      el.className = "value err";
    }
  });
}

document.getElementById("btn-poll").addEventListener("click", async () => {
  await new Promise((r) => chrome.runtime.sendMessage({ type: "POLL_NOW" }, r));
  await refresh();
});
document.getElementById("btn-refresh").addEventListener("click", refresh);

refresh();
