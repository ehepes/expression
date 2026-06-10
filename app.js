/* EXPRESSION — media team hub. UI layer. */

const BRANCHES = {
  social: { name: "Social Media Team", short: "Social", color: "#3B82F6", desc: "Instagram posts, stories & captions" },
  media: { name: "Photo & Media Team", short: "Media", color: "#8B5CF6", desc: "Photography, filming & visuals" },
  editing: { name: "Editing Team", short: "Editing", color: "#10B981", desc: "YouTube & Spotify content" },
};

const REEL_STATUSES = [
  ["idea", "Idea"],
  ["approved", "Approved"],
  ["filming", "Filming"],
  ["editing", "Editing"],
  ["ready", "Ready to post"],
  ["posted", "Posted"],
];

const STATUS_COLORS = {
  idea: "#EAF1FF;color:#1E5BD6",
  approved: "#E8E2FB;color:#6D3FE0",
  filming: "#FFF1DF;color:#C26A00",
  editing: "#FFE9EF;color:#D03A6B",
  ready: "#DFF7EA;color:#0E8A50",
  posted: "#EDF1F7;color:#5B6B8C",
};

const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// ----- app state -----
let tab = ["week", "reels", "teams"].includes(location.hash.slice(1))
  ? location.hash.slice(1)
  : "week";
let branchFilter = "all";
let weekStart = startOfWeek(new Date());

// ----- date helpers (local time, Monday-start weeks) -----
function ymd(d) {
  return (
    d.getFullYear() +
    "-" +
    String(d.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(d.getDate()).padStart(2, "0")
  );
}

function startOfWeek(d) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}

function addDays(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

function fmtShort(d) {
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ----- derived data -----
function itemsForDate(date) {
  const { items } = Store.get();
  const dateStr = ymd(date);
  const dow = (date.getDay() + 6) % 7;
  return items.filter((it) => {
    if (branchFilter !== "all" && it.branch !== branchFilter) return false;
    return it.recurring ? it.dow === dow : it.date === dateStr;
  });
}

function weekStats(filterBranch) {
  let total = 0;
  let done = 0;
  for (let i = 0; i < 7; i++) {
    const date = addDays(weekStart, i);
    const dateStr = ymd(date);
    const dow = i;
    Store.get().items.forEach((it) => {
      if (filterBranch && it.branch !== filterBranch) return;
      if (branchFilter !== "all" && !filterBranch && it.branch !== branchFilter) return;
      const onDay = it.recurring ? it.dow === dow : it.date === dateStr;
      if (!onDay) return;
      total++;
      if (Store.isDone(it.id, dateStr)) done++;
    });
  }
  return { total, done };
}

// ----- rendering -----
function render() {
  renderSyncBadge();
  renderBanner();
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  const view = document.getElementById("view");
  if (tab === "week") view.innerHTML = renderWeek();
  else if (tab === "reels") view.innerHTML = renderReels();
  else view.innerHTML = renderTeams();
}

function renderSyncBadge() {
  const el = document.getElementById("sync-badge");
  const mode = Store.getMode();
  if (mode === "remote") {
    el.className = "sync-badge on";
    el.innerHTML = '<span class="dot"></span>Team sync';
  } else {
    el.className = "sync-badge";
    el.innerHTML = '<span class="dot"></span>This device';
  }
}

function renderBanner() {
  const el = document.getElementById("banner");
  const mode = Store.getMode();
  if (mode === "local") {
    el.innerHTML =
      "<b>Local mode:</b> changes are saved on this device only. To share one calendar with the whole team, set up free team sync — see the README in the project.";
  } else if (mode === "local-error") {
    el.innerHTML =
      "<b>Couldn’t reach the team database.</b> Working from this device for now — check the keys in config.js or your connection, then reload.";
  } else {
    el.innerHTML = "";
  }
}

function chipsHtml() {
  const chips = [["all", "All teams"]].concat(
    Object.entries(BRANCHES).map(([k, b]) => [k, b.short])
  );
  return (
    '<div class="chips">' +
    chips
      .map(
        ([k, label]) =>
          `<button class="chip ${branchFilter === k ? "active" : ""}" data-action="filter" data-branch="${k}">${label}</button>`
      )
      .join("") +
    "</div>"
  );
}

function taskRowHtml(it, dateStr, opts) {
  const done = Store.isDone(it.id, dateStr);
  const b = BRANCHES[it.branch] || BRANCHES.social;
  const meta = [
    `<span class="bdot" style="background:${b.color}"></span><span>${esc(b.short)}</span>`,
    it.assignee ? `<span>&#128100; ${esc(it.assignee)}</span>` : "",
    it.recurring ? '<span class="repeat-tag">&#8635; weekly</span>' : "",
  ]
    .filter(Boolean)
    .join("");
  return `
    <div class="task ${done ? "done-row" : ""}" data-action="edit-item" data-id="${it.id}" data-date="${dateStr}">
      <button class="checkbox ${done ? "done" : ""}" data-action="toggle-done" data-id="${it.id}" data-date="${dateStr}" aria-label="Mark done">&#10003;</button>
      <div class="task-main">
        <div class="task-title">${esc(it.title)}</div>
        <div class="task-meta">${meta}</div>
      </div>
    </div>`;
}

function renderWeek() {
  const today = ymd(new Date());
  const { total, done } = weekStats();
  const pct = total ? Math.round((done / total) * 100) : 0;
  const range = `${fmtShort(weekStart)} – ${fmtShort(addDays(weekStart, 6))}`;

  let days = "";
  for (let i = 0; i < 7; i++) {
    const date = addDays(weekStart, i);
    const dateStr = ymd(date);
    const items = itemsForDate(date);
    const isToday = dateStr === today;
    days += `
      <div class="day-card ${isToday ? "today" : ""}">
        <div class="day-head">
          <span class="dname">${DAY_NAMES[i]}</span>
          <span class="ddate">${fmtShort(date)}</span>
          ${isToday ? '<span class="today-tag">TODAY</span>' : ""}
          <button class="day-add" data-action="add-item" data-date="${dateStr}" aria-label="Add to ${DAY_NAMES[i]}">+</button>
        </div>
        ${
          items.length
            ? items.map((it) => taskRowHtml(it, dateStr)).join("")
            : '<div class="day-empty">Nothing scheduled — tap + to add.</div>'
        }
      </div>`;
  }

  return `
    <div class="week-nav">
      <button class="icon-btn" data-action="week-prev" aria-label="Previous week">&#8249;</button>
      <span class="range">${range}</span>
      <button class="pill-btn" data-action="week-today">Today</button>
      <button class="icon-btn" data-action="week-next" aria-label="Next week">&#8250;</button>
    </div>
    ${chipsHtml()}
    <div class="progress-card">
      <div class="label"><span>This week</span><span>${done} of ${total} done</span></div>
      <div class="bar"><span style="width:${pct}%"></span></div>
    </div>
    ${days}`;
}

function renderReels() {
  const { reels } = Store.get();
  let sections = "";
  REEL_STATUSES.forEach(([key, label]) => {
    const group = reels.filter((r) => (r.status || "idea") === key);
    if (!group.length) return;
    sections += `<div class="section-title">${label} · ${group.length}</div>`;
    sections += group.map(reelCardHtml).join("");
  });
  if (!sections) {
    sections =
      '<div class="empty-state">No reels yet.<br/>Tap <b>New reel</b> to add your first idea.</div>';
  }
  return `
    <div class="reels-head">
      <h2>Reels</h2>
      <button class="primary-btn" data-action="add-reel">+ New reel</button>
    </div>
    ${sections}`;
}

function reelCardHtml(r) {
  const idx = Math.max(0, REEL_STATUSES.findIndex(([k]) => k === r.status));
  const pct = Math.round((idx / (REEL_STATUSES.length - 1)) * 100);
  const label = REEL_STATUSES[idx][1];
  const chipStyle = STATUS_COLORS[r.status] || STATUS_COLORS.idea;
  const next = REEL_STATUSES[idx + 1];
  return `
    <div class="reel-card" data-action="edit-reel" data-id="${r.id}">
      <div class="reel-top">
        <div class="reel-title">${esc(r.title)}</div>
        <span class="status-chip" style="background:${chipStyle}">${label}</span>
      </div>
      ${r.notes ? `<div class="reel-notes">${esc(r.notes)}</div>` : ""}
      <div class="reel-meta">
        ${r.assignee ? `<span>&#128100; ${esc(r.assignee)}</span>` : "<span>Unassigned</span>"}
        ${r.due_date ? `<span>&#128197; due ${esc(r.due_date)}</span>` : ""}
      </div>
      <div class="bar reel-bar"><span style="width:${pct}%"></span></div>
      ${
        next
          ? `<div class="reel-actions"><button class="advance-btn" data-action="advance-reel" data-id="${r.id}">Move to ${next[1]} &#8594;</button></div>`
          : ""
      }
    </div>`;
}

function renderTeams() {
  const today = ymd(new Date());
  let cards = "";
  Object.entries(BRANCHES).forEach(([key, b]) => {
    const { total, done } = weekStats(key);
    const pct = total ? Math.round((done / total) * 100) : 0;

    let rows = "";
    for (let i = 0; i < 7; i++) {
      const date = addDays(weekStart, i);
      const dateStr = ymd(date);
      const dow = i;
      Store.get()
        .items.filter((it) => it.branch === key && (it.recurring ? it.dow === dow : it.date === dateStr))
        .forEach((it) => {
          rows += taskRowHtml(it, dateStr);
        });
    }

    cards += `
      <div class="team-card">
        <div class="team-head" style="background:linear-gradient(135deg, ${b.color}, ${b.color}CC)">
          <h3>${b.name}</h3>
          <p>${b.desc}</p>
        </div>
        <div class="team-body">
          <div class="team-stats"><span>This week</span><span>${done} / ${total} done (${pct}%)</span></div>
          <div class="bar"><span style="width:${pct}%"></span></div>
          ${rows || '<div class="day-empty" style="padding:12px 0 0">No tasks this week.</div>'}
          <button class="team-add" data-action="add-item" data-branch="${key}" data-date="${today}">+ Add task for this team</button>
        </div>
      </div>`;
  });

  const range = `${fmtShort(weekStart)} – ${fmtShort(addDays(weekStart, 6))}`;
  return `
    <div class="week-nav">
      <button class="icon-btn" data-action="week-prev" aria-label="Previous week">&#8249;</button>
      <span class="range">${range}</span>
      <button class="pill-btn" data-action="week-today">Today</button>
      <button class="icon-btn" data-action="week-next" aria-label="Next week">&#8250;</button>
    </div>
    ${cards}`;
}

// ----- modals -----
function closeModal() {
  document.getElementById("modal-root").innerHTML = "";
}

function openItemModal(opts) {
  const editing = opts.id ? Store.get().items.find((i) => i.id === opts.id) : null;
  const it = editing || {
    title: "",
    notes: "",
    branch: opts.branch || (branchFilter !== "all" ? branchFilter : "social"),
    assignee: "",
    recurring: false,
    dow: 0,
    date: opts.date || ymd(new Date()),
  };
  const branchOpts = Object.entries(BRANCHES)
    .map(([k, b]) => `<option value="${k}" ${it.branch === k ? "selected" : ""}>${b.name}</option>`)
    .join("");
  const dayOpts = DAY_NAMES.map(
    (d, i) => `<option value="${i}" ${(it.dow ?? 0) === i ? "selected" : ""}>${d}</option>`
  ).join("");

  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" data-action="close-modal">
      <form class="modal" id="item-form">
        <h2>${editing ? "Edit item" : "Add item"}</h2>
        <div class="field">
          <label>What needs to happen?</label>
          <input type="text" name="title" required maxlength="200" value="${esc(it.title)}" placeholder="e.g. Post Sunday recap carousel" />
        </div>
        <div class="field">
          <label>Team</label>
          <select name="branch">${branchOpts}</select>
        </div>
        <div class="field">
          <label>Assigned to</label>
          <input type="text" name="assignee" maxlength="80" value="${esc(it.assignee)}" placeholder="Name (optional)" />
        </div>
        <div class="field">
          <label>Notes</label>
          <textarea name="notes" maxlength="2000" placeholder="Caption ideas, links, details… (optional)">${esc(it.notes)}</textarea>
        </div>
        <div class="field">
          <label>When</label>
          <div class="radio-row">
            <label><input type="radio" name="schedule" value="once" ${!it.recurring ? "checked" : ""}/> One date</label>
            <label><input type="radio" name="schedule" value="weekly" ${it.recurring ? "checked" : ""}/> Repeats weekly</label>
          </div>
          <input type="date" name="date" value="${esc(it.date || opts.date || ymd(new Date()))}" style="display:${it.recurring ? "none" : "block"}" />
          <select name="dow" style="display:${it.recurring ? "block" : "none"}">${dayOpts}</select>
        </div>
        <div class="modal-actions">
          ${editing ? '<button type="button" class="danger-btn" data-action="delete-item" data-id="' + editing.id + '">Delete</button>' : ""}
          <button type="button" class="ghost-btn" data-action="close-modal">Cancel</button>
          <button type="submit" class="primary-btn">${editing ? "Save" : "Add"}</button>
        </div>
      </form>
    </div>`;

  const form = document.getElementById("item-form");
  form.querySelectorAll('input[name="schedule"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const weekly = form.schedule.value === "weekly";
      form.date.style.display = weekly ? "none" : "block";
      form.dow.style.display = weekly ? "block" : "none";
    });
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const weekly = form.schedule.value === "weekly";
    const fields = {
      title: form.title.value.trim(),
      branch: form.branch.value,
      assignee: form.assignee.value.trim(),
      notes: form.notes.value.trim(),
      recurring: weekly,
      dow: weekly ? Number(form.dow.value) : null,
      date: weekly ? null : form.date.value || ymd(new Date()),
    };
    if (!fields.title) return;
    if (editing) Store.updateItem(editing.id, fields);
    else Store.addItem(fields);
    closeModal();
  });
  form.title.focus();
}

function openReelModal(id) {
  const editing = id ? Store.get().reels.find((r) => r.id === id) : null;
  const r = editing || { title: "", notes: "", assignee: "", status: "idea", due_date: "" };
  const statusOpts = REEL_STATUSES.map(
    ([k, label]) => `<option value="${k}" ${r.status === k ? "selected" : ""}>${label}</option>`
  ).join("");

  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" data-action="close-modal">
      <form class="modal" id="reel-form">
        <h2>${editing ? "Edit reel" : "New reel"}</h2>
        <div class="field">
          <label>Reel title</label>
          <input type="text" name="title" required maxlength="200" value="${esc(r.title)}" placeholder="e.g. Youth night recap" />
        </div>
        <div class="field">
          <label>Idea / notes</label>
          <textarea name="notes" maxlength="2000" placeholder="Concept, shots, audio, caption…">${esc(r.notes)}</textarea>
        </div>
        <div class="field">
          <label>Assigned to</label>
          <input type="text" name="assignee" maxlength="80" value="${esc(r.assignee)}" placeholder="Name (optional)" />
        </div>
        <div class="field">
          <label>Status</label>
          <select name="status">${statusOpts}</select>
        </div>
        <div class="field">
          <label>Target date</label>
          <input type="date" name="due_date" value="${esc(r.due_date || "")}" />
        </div>
        <div class="modal-actions">
          ${editing ? '<button type="button" class="danger-btn" data-action="delete-reel" data-id="' + editing.id + '">Delete</button>' : ""}
          <button type="button" class="ghost-btn" data-action="close-modal">Cancel</button>
          <button type="submit" class="primary-btn">${editing ? "Save" : "Add reel"}</button>
        </div>
      </form>
    </div>`;

  const form = document.getElementById("reel-form");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const fields = {
      title: form.title.value.trim(),
      notes: form.notes.value.trim(),
      assignee: form.assignee.value.trim(),
      status: form.status.value,
      due_date: form.due_date.value || null,
    };
    if (!fields.title) return;
    if (editing) Store.updateReel(editing.id, fields);
    else Store.addReel(fields);
    closeModal();
  });
  form.title.focus();
}

// ----- events -----
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]");
  if (!el) return;
  const action = el.dataset.action;

  // Clicking inside the modal shouldn't close it via the overlay handler.
  if (action === "close-modal" && el.classList.contains("modal-overlay") && e.target !== el) return;

  switch (action) {
    case "tab":
      tab = el.dataset.tab;
      history.replaceState(null, "", "#" + tab);
      render();
      break;
    case "filter":
      branchFilter = el.dataset.branch;
      render();
      break;
    case "week-prev":
      weekStart = addDays(weekStart, -7);
      render();
      break;
    case "week-next":
      weekStart = addDays(weekStart, 7);
      render();
      break;
    case "week-today":
      weekStart = startOfWeek(new Date());
      render();
      break;
    case "toggle-done": {
      e.stopPropagation();
      const { id, date } = el.dataset;
      Store.setDone(id, date, !Store.isDone(id, date));
      break;
    }
    case "add-item":
      openItemModal({ date: el.dataset.date, branch: el.dataset.branch });
      break;
    case "edit-item":
      if (e.target.closest('[data-action="toggle-done"]')) break;
      openItemModal({ id: el.dataset.id });
      break;
    case "add-reel":
      openReelModal();
      break;
    case "edit-reel":
      if (e.target.closest('[data-action="advance-reel"]')) break;
      openReelModal(el.dataset.id);
      break;
    case "advance-reel": {
      e.stopPropagation();
      const reel = Store.get().reels.find((r) => r.id === el.dataset.id);
      if (!reel) break;
      const idx = REEL_STATUSES.findIndex(([k]) => k === reel.status);
      const next = REEL_STATUSES[idx + 1];
      if (next) Store.updateReel(reel.id, { status: next[0] });
      break;
    }
    case "delete-item":
      if (confirm("Delete this item everywhere (including past weeks)?")) {
        Store.deleteItem(el.dataset.id);
        closeModal();
      }
      break;
    case "delete-reel":
      if (confirm("Delete this reel?")) {
        Store.deleteReel(el.dataset.id);
        closeModal();
      }
      break;
    case "close-modal":
      closeModal();
      break;
  }
});

// ----- boot -----
Store.onChange(render);
Store.init();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((e) => console.error("SW failed:", e));
  });
}
