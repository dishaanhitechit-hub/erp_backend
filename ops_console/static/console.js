/* PRAX Ops Console — page logic (no framework, no external files). */
(function () {
  "use strict";

  // ── helpers ──────────────────────────────────────────────────────────────
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function api(path, opts = {}) {
    const r = await fetch("api/" + path, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json", "X-Prax-Console": "1" },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (r.status === 401) { window.location.href = "login"; throw new Error("signed out"); }
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `Request failed (${r.status})`);
    return body;
  }

  function toast(msg, bad = false) {
    const t = document.createElement("div");
    t.className = "toast" + (bad ? " bad" : "");
    t.textContent = msg;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), bad ? 7000 : 4000);
  }

  const bytes = (n) => {
    if (n == null) return "—";
    const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; n = Number(n);
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(1) : n.toFixed(0)) + " " + u[i];
  };
  const when = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  };
  const ago = (iso) => {
    if (!iso) return "never";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 90) return "just now";
    if (s < 5400) return Math.round(s / 60) + " min ago";
    if (s < 172800) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " days ago";
  };
  const dur = (s) => s == null ? "—" : s < 90 ? s + " s" : Math.round(s / 60) + " min";
  const statusBadge = (s) => {
    const k = { SUCCESS: "b-ok", PASSED: "b-ok", success: "b-ok", PARTIAL: "b-warn", PROBLEMS: "b-warn", running: "b-info", queued: "b-info" }[s] || "b-bad";
    const label = { PARTIAL: "LOCAL ONLY" }[s] || String(s).toUpperCase();
    return `<span class="badge ${k}">${esc(label)}</span>`;
  };
  const JOB_NAMES = {
    backup_now: "Back up now", verify: "Restore test", refresh_remote: "Refresh Drive list",
    restore_db: "Restore database", apply_media: "Put back missing files", restore_file: "Restore one file",
    switch_live: "Switch live database", switch_back: "Switch back", drop_db: "Delete restored database",
  };

  // ── modal ────────────────────────────────────────────────────────────────
  function openModal(title, bodyHtml, buttons = []) {
    $("#modal-title").textContent = title;
    $("#modal-body").innerHTML = bodyHtml;
    const foot = $("#modal-foot");
    foot.innerHTML = "";
    buttons.forEach((b) => {
      const el = document.createElement("button");
      el.className = "btn " + (b.cls || "");
      el.textContent = b.label;
      el.addEventListener("click", b.onClick);
      foot.appendChild(el);
    });
    $("#modal").classList.remove("hidden");
    const first = $("#modal-body input");
    if (first) first.focus();
  }
  function closeModal() { $("#modal").classList.add("hidden"); stopJobPoll(); }
  $("#modal-close").addEventListener("click", closeModal);
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modal").classList.contains("hidden")) closeModal(); });

  /** Ask for the password (and optionally a typed confirmation), then start a job. */
  function confirmJob({ kind, params, title, warning, confirmText, confirmLabel, buttonLabel, danger }) {
    const confirmHtml = confirmText
      ? `<label>${esc(confirmLabel || "Type to confirm")} <span class="mono">${esc(confirmText)}</span><input id="cf-confirm" autocomplete="off"></label>` : "";
    openModal(title, `
      ${warning ? `<div class="${danger ? "danger-box" : "notice info"}">${warning}</div>` : ""}
      ${confirmHtml}
      <label>Your console password<input id="cf-password" type="password" autocomplete="current-password"></label>
      <div class="form-error" id="cf-error"></div>`, [
      { label: "Cancel", onClick: closeModal },
      { label: buttonLabel || "Start", cls: danger ? "btn-danger" : "btn-primary", onClick: async (e) => {
        e.target.disabled = true;
        try {
          const res = await api("jobs", { method: "POST", body: {
            kind, params, password: $("#cf-password").value, confirm: confirmText ? $("#cf-confirm").value : undefined } });
          showJob(res.job.id);
        } catch (ex) { $("#cf-error").textContent = ex.message; e.target.disabled = false; }
      } },
    ]);
  }

  async function startSimpleJob(kind, params = {}) {
    try {
      const res = await api("jobs", { method: "POST", body: { kind, params } });
      showJob(res.job.id);
    } catch (ex) { toast(ex.message, true); }
  }

  // ── job output viewer ────────────────────────────────────────────────────
  let jobPoll = null;
  function stopJobPoll() { if (jobPoll) { clearTimeout(jobPoll); jobPoll = null; } }

  function showJob(id) {
    stopJobPoll();
    openModal("Job", `<div id="job-head" class="toolbar"></div><pre class="logbox" id="job-out"></pre><div id="job-result"></div>`,
      [{ label: "Close", onClick: closeModal }]);
    let offset = 0;
    const tick = async () => {
      try {
        const res = await api(`jobs/${encodeURIComponent(id)}?offset=${offset}`);
        offset = res.offset;
        const j = res.job;
        $("#modal-title").textContent = JOB_NAMES[j.kind] || j.kind;
        $("#job-head").innerHTML = `${statusBadge(j.status)} <span class="muted tiny">by ${esc(j.user)} · started ${esc(when(j.started || j.created))}</span>`;
        if (res.output) appendLog($("#job-out"), res.output);
        if (j.status === "running" || j.status === "queued") { jobPoll = setTimeout(tick, 1500); return; }
        renderJobResult(j);
        refreshAll();
      } catch (ex) { $("#job-head").textContent = ex.message; }
    };
    tick();
  }

  function renderJobResult(j) {
    const box = $("#job-result");
    if (!box) return;
    if (j.status !== "success") {
      box.innerHTML = `<div class="danger-box">${esc(j.error || "The job did not finish.")}</div>`;
      return;
    }
    const r = j.result || {};
    if (j.kind === "restore_file" && r.file) {
      box.innerHTML = `<p><a class="btn btn-primary" href="api/jobs/${encodeURIComponent(j.id)}/file">Download ${esc(r.file)}</a>
        ${r.put_back ? '<span class="badge b-ok">put back in live folder</span>' : ""}</p>`;
    } else if (j.kind === "restore_db") {
      box.innerHTML = `<div class="notice info">Database <b class="mono">${esc(r.target_db)}</b> is ready (${esc(r.tables)} tables).
        It is <b>not live</b>. Check it, then use <b>Switch live</b> in step 3.${r.media_staging ? " Restored pictures are waiting in step 3." : ""}</div>`;
    }
  }

  function appendLog(pre, text) {
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
    text.split("\n").forEach((ln, i, arr) => {
      if (i === arr.length - 1 && ln === "") return;
      const span = document.createElement("span");
      if (/ERROR|FAILED|Traceback|PROBLEM/.test(ln)) span.className = "e";
      else if (/WARNING|warning/.test(ln)) span.className = "w";
      span.textContent = ln + "\n";
      pre.appendChild(span);
    });
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  }

  // ── navigation ───────────────────────────────────────────────────────────
  const loaders = {};
  function showTab(name) {
    if (!$("#tab-" + name)) name = "overview";
    $$(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== "tab-" + name));
    $$(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.tab === name));
    $("#sidebar").classList.remove("open");
    if (loaders[name]) loaders[name]();
  }
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
  $("#nav-toggle").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  $("#logout-btn").addEventListener("click", async () => {
    await api("logout", { method: "POST" }).catch(() => {});
    window.location.href = "login";
  });

  // ── overview ─────────────────────────────────────────────────────────────
  let overviewData = null;
  loaders.overview = async () => {
    const o = await api("overview");
    overviewData = o;
    $("#env-pill").textContent = o.environment;
    $("#live-pill").textContent = "live DB: " + (o.live_db || "?");
    renderJobBanner(o.job);

    const h = o.hours_since_success;
    let cls = "ok", icon = "✅", title = "Backups are healthy", detail = `Last successful backup ${ago(o.last_success_at)} (${when(o.last_success_at)}).`;
    if (h == null) { cls = "bad"; icon = "🔴"; title = "No successful backup yet"; detail = "Run “Back up now”."; }
    else if (h > o.max_gap_hours) { cls = "bad"; icon = "🔴"; title = `No backup for ${h} hours`; detail += " Data entered since then is not protected."; }
    else if (o.last_error) { cls = "warn"; icon = "⚠️"; title = "Last attempt had a problem"; detail += " " + o.last_error.slice(0, 200); }
    else if (o.last_verify && o.last_verify.status !== "PASSED") { cls = "warn"; icon = "⚠️"; title = "Backups OK — restore test found problems"; }
    $("#health-hero").className = "hero " + cls;
    $("#health-hero").innerHTML = `<div class="icon">${icon}</div><div><div class="title">${esc(title)}</div><div class="detail">${esc(detail)}</div></div>`;

    const c7 = o.counts["7d"], c30 = o.counts["30d"];
    const v = o.last_verify;
    $("#stat-cards").innerHTML = [
      stat("Backups · 7 days", c7.SUCCESS + c7.PARTIAL, `${c7.FAILED} failed · ${c7.PARTIAL} local only`),
      stat("Backups · 30 days", c30.SUCCESS + c30.PARTIAL, `${c30.FAILED} failed of ${c30.total} attempts`),
      stat("Average time", dur(o.avg_duration_s), "per backup"),
      stat("Kept copies", `${o.local_sets} / ${o.remote.count ?? "?"}`, "server disk / Google Drive"),
      stat("Restore test", v ? v.status : "never", v ? when(v.at) : "runs Sundays 05:00"),
    ].join("");

    let storage = "";
    if (o.disk) storage += bar(`Backup disk ${o.disk.path}`, (100 * o.disk.used) / o.disk.total, `${bytes(o.disk.free)} free of ${bytes(o.disk.total)}`);
    storage += `<dl class="kv"><dt>Google Drive</dt><dd>${o.remote.configured ? `${o.remote.count ?? "?"} backups · listed ${esc(ago(o.remote.listed_at))}` : "not configured"}</dd>
      <dt>Pictures &amp; files</dt><dd>${o.sources.map((s) => `<span class="mono">${esc(s.path)}</span>`).join("<br>") || "none configured"}</dd>
      <dt>Mode</dt><dd>${o.media_mode === "full" ? "Full copy every backup" : "Mirror (sync)"}</dd></dl>`;
    $("#storage").innerHTML = storage;
    $("#schedule").innerHTML = `<dl class="kv">
      <dt>Windows</dt><dd>${o.windows.map(esc).join(" and ")} IST</dd>
      <dt>Next window</dt><dd>${esc(when(o.next_window))}</dd>
      <dt>Rule</dt><dd>Waits for the server to be idle; never more than ${o.max_gap_hours} h without a backup</dd>
      <dt>Last check</dt><dd>${o.last_decision ? esc(when(o.last_decision.at) + " — " + o.last_decision.reason) : "—"}</dd>
      <dt>Kept</dt><dd>${o.retention.daily_days} days rolling + ${o.retention.weekly} weekly + ${o.retention.monthly} monthly</dd></dl>`;
  };
  const stat = (label, value, sub) => `<div class="card stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="sub">${esc(sub)}</div></div>`;
  function bar(label, pct, detail) {
    pct = Math.max(0, Math.min(100, Math.round(pct)));
    const cls = pct >= 90 ? "bad" : pct >= 80 ? "warn" : "";
    const id = "bar-" + Math.random().toString(36).slice(2);
    setTimeout(() => { const el = document.getElementById(id); if (el) el.style.width = Math.max(pct, 1) + "%"; });
    return `<div class="bar"><div class="bar-head"><span>${esc(label)}</span><b>${pct}%</b></div>
      <div class="bar-track"><div class="bar-fill ${cls}" id="${id}"></div></div><div class="tiny muted">${esc(detail)}</div></div>`;
  }
  function renderJobBanner(job) {
    const b = $("#job-banner");
    if (!job) { b.classList.add("hidden"); return; }
    b.classList.remove("hidden");
    b.innerHTML = `<span class="spinner"></span><span>${esc(JOB_NAMES[job.kind] || job.kind)} is running (by ${esc(job.user)})</span>
      <button class="btn btn-sm" id="job-banner-open">Show</button>`;
    $("#job-banner-open").addEventListener("click", () => showJob(job.id));
  }
  $$("[data-action]").forEach((b) => b.addEventListener("click", () => {
    const kind = b.dataset.action;
    if (kind === "verify") return startSimpleJob("verify", { from_remote: true });
    startSimpleJob(kind);
  }));

  // ── history ──────────────────────────────────────────────────────────────
  let runsData = null;
  loaders.history = async () => {
    runsData = await api("runs");
    renderRuns();
    $("#tests-table tbody").innerHTML = runsData.verifies.map((v) => `<tr>
      <td>${esc(when(v.at))}</td><td>${statusBadge(v.status)}</td><td class="mono">${esc(v.backup_id || "—")}</td>
      <td>${esc(v.source || "—")}</td><td class="tiny">${(v.notes || []).map(esc).join("<br>")}${(v.problems || []).map((p) => `<br><span class="badge b-bad">!</span> ${esc(p)}`).join("")}</td></tr>`).join("")
      || `<tr><td colspan="5" class="empty">No restore tests yet</td></tr>`;
  };
  function renderRuns() {
    const f = $("#run-filter").value;
    const rows = runsData.runs.filter((r) => !f || r.status === f);
    $("#run-count").textContent = `${rows.length} of ${runsData.runs.length} attempts`;
    const tb = $("#runs-table tbody");
    tb.innerHTML = rows.map((r, i) => `<tr class="clickable" data-i="${runsData.runs.indexOf(r)}">
      <td>${esc(when(r.started_at))}</td><td>${statusBadge(r.status)}</td><td>${esc(r.trigger)}</td><td>${esc(dur(r.duration_s))}</td>
      <td>${esc(bytes(r.db_bytes))}</td><td>${r.media_files != null ? esc(r.media_files) + " · " + esc(bytes(r.media_bytes)) : "—"}</td>
      <td>${r.uploaded ? "✅" : "—"}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">No backups recorded yet</td></tr>`;
    $$("tr.clickable", tb).forEach((tr) => tr.addEventListener("click", () => showRun(runsData.runs[tr.dataset.i])));
  }
  $("#run-filter").addEventListener("change", renderRuns);

  async function showRun(r) {
    openModal(r.backup_id || "Backup attempt", `
      <dl class="kv"><dt>Result</dt><dd>${statusBadge(r.status)}</dd><dt>Started</dt><dd>${esc(when(r.started_at))}</dd>
      <dt>Finished</dt><dd>${esc(when(r.finished_at))} (${esc(dur(r.duration_s))})</dd><dt>Trigger</dt><dd>${esc(r.trigger)}</dd>
      <dt>Database dump</dt><dd>${esc(bytes(r.db_bytes))}</dd><dt>Pictures &amp; files</dt><dd>${esc(r.media_files ?? "—")} files · ${esc(bytes(r.media_bytes))}</dd>
      <dt>On Google Drive</dt><dd>${r.uploaded ? "yes" : "no"}</dd></dl>
      ${r.error ? `<h3>Problem</h3><div class="danger-box">${esc(r.error)}</div>` : ""}
      ${(r.warnings || []).length ? `<h3>Warnings</h3>${r.warnings.map((w) => `<div class="notice warn">${esc(w)}</div>`).join("")}` : ""}
      <h3>Log of this run</h3><pre class="logbox" id="run-log">loading…</pre>`, [{ label: "Close", onClick: closeModal }]);
    try {
      const until = r.finished_at || new Date(new Date(r.started_at).getTime() + 3 * 3600e3).toISOString();
      const res = await api(`log?since=${encodeURIComponent(r.started_at)}&until=${encodeURIComponent(until)}&limit=2000`);
      const pre = $("#run-log"); pre.textContent = "";
      appendLog(pre, res.lines.join("\n") || "(no log lines for this time)");
    } catch (ex) { $("#run-log").textContent = ex.message; }
  }

  $$("#history-seg button").forEach((b) => b.addEventListener("click", () => {
    $$("#history-seg button").forEach((x) => x.classList.toggle("active", x === b));
    ["runs", "tests", "log"].forEach((v) => $("#history-" + v).classList.toggle("hidden", v !== b.dataset.view));
    if (b.dataset.view === "log" && !$("#log-box").textContent) loadLog();
  }));
  async function loadLog() {
    const d = $("#log-date").value;
    const qs = new URLSearchParams({ limit: "3000" });
    if (d) { qs.set("since", d + "T00:00:00"); qs.set("until", d + "T23:59:59"); }
    if ($("#log-level").value) qs.set("level", $("#log-level").value);
    if ($("#log-q").value) qs.set("q", $("#log-q").value);
    const pre = $("#log-box"); pre.textContent = "loading…";
    try {
      const res = await api("log?" + qs);
      pre.textContent = "";
      appendLog(pre, res.lines.join("\n") || "(nothing found)");
      pre.scrollTop = pre.scrollHeight;
    } catch (ex) { pre.textContent = ex.message; }
  }
  $("#log-go").addEventListener("click", loadLog);
  $("#log-q").addEventListener("keydown", (e) => { if (e.key === "Enter") loadLog(); });

  // ── restore ──────────────────────────────────────────────────────────────
  let setsData = null, chosenSet = null, chosenSrc = "local";
  loaders.restore = async () => {
    const [sets, dbs, jobList] = await Promise.all([api("sets"), api("databases"), api("jobs")]);
    setsData = sets;
    renderSets();
    renderDatabases(dbs);
    renderStaging(jobList.jobs);
    if (!$("#target-db").value) {
      const d = new Date();
      $("#target-db").value = `${(overviewData && overviewData.live_db) || "erp_db"}_r${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`.replace(/_r\d+_r/, "_r");
    }
  };
  const TIER_LABELS = { daily: "Daily", weekly: "Weekly", monthly: "Monthly", manual: "Manual", legacy: "Old name" };
  function tierBadge(t) {
    return t ? `<span class="badge ${t === "monthly" || t === "weekly" ? "b-ok" : "b-info"}">${esc(TIER_LABELS[t] || t)}</span>` : "";
  }
  function renderSets() {
    const list = chosenSrc === "local" ? setsData.local : setsData.drive;
    $("#drive-note").textContent = chosenSrc === "drive"
      ? `Google Drive list from ${ago(setsData.drive_listed_at)} — “Refresh Drive list” on Overview updates it. Restoring from Drive downloads the backup first.`
      : "Backups kept on the server's backup disk (newest ones). Fastest to restore.";
    $("#set-list").innerHTML = list.map((s) => `<div class="set-item ${chosenSet === s.id ? "selected" : ""}" data-id="${esc(s.id)}">
        <input type="radio" name="set" ${chosenSet === s.id ? "checked" : ""} tabindex="-1">
        <span class="when">${esc(when(s.at))}</span>
        <span class="meta">${chosenSrc === "local"
          ? `${esc(bytes(s.size))} · ${esc(s.tables)} tables · ${esc(s.rows)} rows · ${esc(s.files)} files ${s.verified ? '<span class="badge b-ok">tested</span>' : ""} ${s.on_drive ? '<span class="badge b-info">on Drive</span>' : ""}`
          : `${tierBadge(s.tier)} <span class="mono tiny">${esc((s.path || s.id).split("/").pop())}</span> ${s.local ? '<span class="badge b-info">also on server</span>' : ""}`}</span></div>`).join("")
      || `<div class="empty">No backups here${chosenSrc === "drive" ? " (or the list was not loaded yet)" : ""}</div>`;
    $$(".set-item").forEach((el) => el.addEventListener("click", () => { chosenSet = el.dataset.id; renderSets(); }));
  }
  $$("#src-seg button").forEach((b) => b.addEventListener("click", () => {
    $$("#src-seg button").forEach((x) => x.classList.toggle("active", x === b));
    chosenSrc = b.dataset.src; chosenSet = null; renderSets();
  }));
  $$("#what-seg button").forEach((b) => b.addEventListener("click", () => {
    $$("#what-seg button").forEach((x) => x.classList.toggle("active", x === b));
    $("#what-db").classList.toggle("hidden", b.dataset.what !== "db");
    $("#what-file").classList.toggle("hidden", b.dataset.what !== "file");
  }));

  $("#restore-db-btn").addEventListener("click", () => {
    if (!chosenSet) return toast("Choose a backup first (step 1)", true);
    const target = $("#target-db").value.trim();
    if (!/^[a-z][a-z0-9_]{2,62}$/.test(target)) return toast("Database name: lowercase letters, digits and _", true);
    confirmJob({
      kind: "restore_db", title: "Restore into a new database",
      params: { set: chosenSet, target_db: target, with_media: $("#with-media").checked, from_remote: chosenSrc === "drive" },
      warning: `Backup <b>${esc(when(setsData[chosenSrc === "local" ? "local" : "drive"].find((s) => s.id === chosenSet)?.at))}</b>
        → new database <b class="mono">${esc(target)}</b>. The live ERP is <b>not</b> touched.`,
      buttonLabel: "Restore",
    });
  });

  async function searchFiles() {
    if (!chosenSet) return toast("Choose a backup first (step 1)", true);
    if (chosenSrc !== "local") return toast("File search works on backups stored on the server disk", true);
    const box = $("#file-results"); box.innerHTML = '<div class="empty">searching…</div>';
    try {
      const res = await api(`sets/${encodeURIComponent(chosenSet)}/files?q=${encodeURIComponent($("#file-q").value)}`);
      box.innerHTML = res.files.map((f) => `<div class="file-row"><span class="mono">${esc(f.p)}</span>
        <span class="muted tiny">${esc(bytes(f.s))}</span><button class="btn btn-sm" data-p="${esc(f.p)}">Restore</button></div>`).join("")
        || '<div class="empty">No matching files</div>';
      $$("button[data-p]", box).forEach((b) => b.addEventListener("click", () => confirmJob({
        kind: "restore_file", title: "Restore one file",
        params: { set: chosenSet, path: b.dataset.p, put_back: $("#file-putback").checked },
        warning: `<span class="mono">${esc(b.dataset.p)}</span><br>${$("#file-putback").checked ? "Will be put back in the live folder only if it is missing there." : "Will be prepared for download only."}`,
        buttonLabel: "Restore file",
      })));
    } catch (ex) { box.innerHTML = `<div class="empty">${esc(ex.message)}</div>`; }
  }
  $("#file-search").addEventListener("click", searchFiles);
  $("#file-q").addEventListener("keydown", (e) => { if (e.key === "Enter") searchFiles(); });

  function renderDatabases(d) {
    if (d.error) { $("#db-list").innerHTML = `<div class="notice warn">${esc(d.error)}</div>`; }
    else {
      $("#db-list").innerHTML = d.databases.map((db) => `<div class="db-row">
        <span class="name">${esc(db.name)}</span>
        ${db.live ? '<span class="badge b-live">LIVE</span>' : ""}
        ${db.created_by_console ? `<span class="badge b-info">restored ${esc(when(db.created_by_console.created))} by ${esc(db.created_by_console.by)}</span>` : ""}
        <span class="grow muted tiny">${esc(bytes(db.size))}</span>
        ${db.live ? "" : `<button class="btn btn-sm btn-primary" data-switch="${esc(db.name)}">Switch live…</button>`}
        ${!db.live && db.created_by_console ? `<button class="btn btn-sm" data-drop="${esc(db.name)}">Delete…</button>` : ""}
      </div>`).join("") || '<div class="empty">No databases</div>';
    }
    $$("[data-switch]").forEach((b) => b.addEventListener("click", () => confirmJob({
      kind: "switch_live", params: { target_db: b.dataset.switch }, danger: true,
      title: "Switch the LIVE ERP database",
      warning: `The ERP will <b>stop for about a minute</b> and then use <b class="mono">${esc(b.dataset.switch)}</b> instead of
        <b class="mono">${esc(d.live)}</b>.<br>Everything entered in <b>${esc(d.live)}</b> after that backup will not be in the new database.
        If the ERP does not come up healthy, it switches back automatically.`,
      confirmText: b.dataset.switch, confirmLabel: "Type the database name", buttonLabel: "Switch live now",
    })));
    $$("[data-drop]").forEach((b) => b.addEventListener("click", () => confirmJob({
      kind: "drop_db", params: { name: b.dataset.drop }, danger: true, title: "Delete restored database",
      warning: `Permanently deletes <b class="mono">${esc(b.dataset.drop)}</b>. It is not live. This cannot be undone.`,
      confirmText: b.dataset.drop, confirmLabel: "Type the database name", buttonLabel: "Delete",
    })));
    const last = d.switch_history[0];
    $("#switch-back-box").innerHTML = d.can_switch_back
      ? `<div class="notice warn">Last switch: <b class="mono">${esc(last.from)}</b> → <b class="mono">${esc(last.to)}</b> by ${esc(last.by)}, ${esc(when(last.at))}.
         <button class="btn btn-sm" id="switch-back">Switch back to ${esc(last.from)}…</button></div>` : "";
    if (d.can_switch_back) $("#switch-back").addEventListener("click", () => confirmJob({
      kind: "switch_back", params: {}, danger: true, title: "Switch back",
      warning: `The ERP will stop for about a minute and go back to <b class="mono">${esc(last.from)}</b>. Data entered since the switch stays in <b class="mono">${esc(last.to)}</b> only.`,
      confirmText: "SWITCH BACK", buttonLabel: "Switch back now",
    }));
  }

  function renderStaging(jobsList) {
    const items = jobsList.filter((j) => j.kind === "restore_db" && j.status === "success" && j.result && j.result.media_staging);
    $("#staging-list").innerHTML = items.slice(0, 5).map((j) => `<div class="db-row">
      <span class="grow">From backup <span class="mono">${esc(j.params.set)}</span> <span class="muted tiny">(${esc(when(j.finished))})</span></span>
      <button class="btn btn-sm" data-stage="${esc(j.id)}">Put back missing files…</button></div>`).join("")
      || '<div class="empty">None — restore with “Also restore pictures” to see them here.</div>';
    $$("[data-stage]").forEach((b) => b.addEventListener("click", () => confirmJob({
      kind: "apply_media", params: { staging: b.dataset.stage }, title: "Put back missing pictures & files",
      warning: "Copies restored files into the live folders <b>only where the file is missing</b>. Existing files are never overwritten or deleted.",
      buttonLabel: "Put back",
    })));
  }

  // ── alert recipients ─────────────────────────────────────────────────────
  let rec = null, recDirty = false;
  loaders.alerts = async () => {
    if (recDirty && rec) return renderMatrix();
    rec = await api("recipients");
    rec.data.contacts = rec.data.contacts || {};
    // everyone who appears anywhere becomes a column
    Object.values(rec.data.categories).flat().forEach((e) => { if (!(e in rec.data.contacts)) rec.data.contacts[e] = ""; });
    rec.categories.forEach((c) => { if (!rec.data.categories[c.key]) rec.data.categories[c.key] = []; });
    renderMatrix();
  };
  function setDirty(v) { recDirty = v; $("#save-recipients").disabled = !v; }
  function renderMatrix() {
    $("#recipients-note").innerHTML = rec.configured ? ""
      : `<div class="notice warn">Not saved yet — the shared file <span class="mono">${esc(rec.path)}</span> does not exist, so every sender still uses its own built-in list (shown below where known; server alerts keep the list inside the alert scripts). Saving here makes this table the one list for everyone.</div>`;
    const people = Object.keys(rec.data.contacts).sort();
    let html = `<thead><tr><th>Alert</th>${people.map((p) => `<th class="person">${esc(rec.data.contacts[p] || p.split("@")[0])}
      <div class="email">${esc(p)}</div><button class="btn btn-sm" data-edit="${esc(p)}">Edit</button></th>`).join("")}<th>Test</th></tr></thead><tbody>`;
    let group = "";
    rec.categories.forEach((c) => {
      if (c.group !== group) { group = c.group; html += `<tr class="group"><td colspan="${people.length + 2}">${esc(group)}</td></tr>`; }
      const list = rec.data.categories[c.key] || [];
      html += `<tr class="${list.length ? "" : "nobody"}"><td><div class="cat-label">${esc(c.label)}</div><div class="cat-desc">${esc(c.description)}${list.length ? "" : " — <b>nobody receives this</b>"}</div></td>
        ${people.map((p) => `<td class="cell"><input type="checkbox" aria-label="${esc(c.label)} → ${esc(p)}" data-cat="${esc(c.key)}" data-p="${esc(p)}" ${list.includes(p) ? "checked" : ""}></td>`).join("")}
        <td><button class="btn btn-sm" data-test="${esc(c.key)}" ${recDirty ? "disabled title='Save first'" : ""}>Send test</button></td></tr>`;
    });
    $("#matrix").innerHTML = html + "</tbody>";
    $$("#matrix input[data-cat]").forEach((cb) => cb.addEventListener("change", () => {
      const list = rec.data.categories[cb.dataset.cat];
      const i = list.indexOf(cb.dataset.p);
      if (cb.checked && i < 0) list.push(cb.dataset.p);
      if (!cb.checked && i >= 0) list.splice(i, 1);
      setDirty(true);
      cb.closest("tr").classList.toggle("nobody", list.length === 0);
      $$("#matrix [data-test]").forEach((b) => (b.disabled = true));
    }));
    $$("#matrix [data-test]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { const r = await api("recipients/test", { method: "POST", body: { category: b.dataset.test } }); toast("Test sent to " + r.sent_to.join(", ")); }
      catch (ex) { toast(ex.message, true); }
      b.disabled = false;
    }));
    $$("#matrix [data-edit]").forEach((b) => b.addEventListener("click", () => editPerson(b.dataset.edit)));
  }
  function editPerson(email) {
    const isNew = !email;
    openModal(isNew ? "Add person" : "Edit person", `
      <label>Email<input id="p-email" type="email" value="${esc(email || "")}" ${isNew ? "" : "readonly"}></label>
      <label>Name (shown in this table)<input id="p-name" value="${esc((email && rec.data.contacts[email]) || "")}"></label>
      <div class="form-error" id="p-error"></div>`, [
      ...(isNew ? [] : [{ label: "Remove from all alerts", cls: "btn-danger", onClick: () => {
        delete rec.data.contacts[email];
        Object.values(rec.data.categories).forEach((l) => { const i = l.indexOf(email); if (i >= 0) l.splice(i, 1); });
        setDirty(true); closeModal(); renderMatrix();
      } }]),
      { label: "Cancel", onClick: closeModal },
      { label: isNew ? "Add" : "Done", cls: "btn-primary", onClick: () => {
        const e = $("#p-email").value.trim().toLowerCase();
        if (!/^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$/.test(e)) { $("#p-error").textContent = "Enter a valid email address"; return; }
        if (isNew && e in rec.data.contacts) { $("#p-error").textContent = "Already in the table"; return; }
        rec.data.contacts[e] = $("#p-name").value.trim();
        setDirty(true); closeModal(); renderMatrix();
      } },
    ]);
  }
  $("#add-contact").addEventListener("click", () => editPerson(null));
  $("#save-recipients").addEventListener("click", async () => {
    const empty = rec.categories.filter((c) => !(rec.data.categories[c.key] || []).length);
    if (empty.length && !confirm(`Nobody will receive: ${empty.map((c) => c.label).join(", ")}.\nSave anyway?`)) return;
    try {
      const res = await api("recipients", { method: "PUT", body: { contacts: rec.data.contacts, categories: rec.data.categories } });
      rec.data = res.data; rec.configured = true;
      Object.values(rec.data.categories).flat().forEach((e) => { if (!(e in rec.data.contacts)) rec.data.contacts[e] = ""; });
      setDirty(false); renderMatrix();
      toast(`Saved (${res.changed} alert type${res.changed === 1 ? "" : "s"} changed)`);
    } catch (ex) { toast(ex.message, true); }
  });
  window.addEventListener("beforeunload", (e) => { if (recDirty) { e.preventDefault(); e.returnValue = ""; } });

  // ── activity ─────────────────────────────────────────────────────────────
  loaders.activity = async () => {
    const [j, a] = await Promise.all([api("jobs"), api("audit")]);
    $("#jobs-table tbody").innerHTML = j.jobs.map((x) => `<tr class="clickable" data-job="${esc(x.id)}"><td>${esc(when(x.created))}</td>
      <td>${esc(JOB_NAMES[x.kind] || x.kind)}</td><td>${esc(x.user)}</td><td>${statusBadge(x.status)}</td></tr>`).join("")
      || `<tr><td colspan="4" class="empty">No jobs yet</td></tr>`;
    $$("#jobs-table [data-job]").forEach((tr) => tr.addEventListener("click", () => showJob(tr.dataset.job)));
    $("#audit-table tbody").innerHTML = a.entries.map((x) => `<tr><td>${esc(when(x.at))}</td><td>${esc(x.user)}</td>
      <td>${esc(x.action)}</td><td class="mono">${esc(x.ip)}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">Nothing yet</td></tr>`;
  };

  // ── start ────────────────────────────────────────────────────────────────
  function refreshAll() {
    const tab = location.hash.slice(1) || "overview";
    if (tab !== "overview") loaders.overview().catch(() => {});
    if (loaders[tab]) loaders[tab]().catch((ex) => toast(ex.message, true));
  }
  api("me").then((m) => { $("#backup-version").textContent = "Backup tool v" + m.backup_version; }).catch(() => {});
  loaders.overview().catch((ex) => toast(ex.message, true));
  showTab(location.hash.slice(1) || "overview");
  setInterval(() => { if ($("#modal").classList.contains("hidden") && !document.hidden) loaders.overview().catch(() => {}); }, 30000);
})();
