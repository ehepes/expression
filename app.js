/* EXPRESSION — media team hub. UI layer. */

const ACCOUNTS = {
  main: "Main Church",
  ya: "YA",
  yth: "YTH",
  her: "HER",
};

const BRANCHES = {
  social: { name: "Social Media Team", short: "Social", color: "#3B82F6", desc: "Instagram posts, stories & captions" },
  media: { name: "Photo & Media Team", short: "Media", color: "#8B5CF6", desc: "Photography, filming & visuals" },
  editing: { name: "Editing Team", short: "Editing", color: "#10B981", desc: "YouTube & Spotify content" },
};

const PROJECT_STATUSES = [
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
const NTH_NAMES = ["1st", "2nd", "3rd", "4th"];

// ----- per-device preferences -----
function getPrefs() {
  try {
    return JSON.parse(localStorage.getItem("expression-prefs") || "{}");
  } catch (e) {
    return {};
  }
}

function setPrefs(patch) {
  localStorage.setItem("expression-prefs", JSON.stringify(Object.assign(getPrefs(), patch)));
}

// ----- app state -----
let tab = ["week", "projects", "teams"].includes(location.hash.slice(1))
  ? location.hash.slice(1)
  : "week";
let branchFilter = "all";
let weekStart = startOfWeek(new Date());
let account = ACCOUNTS[getPrefs().account] ? getPrefs().account : "main";

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
// Whether a (possibly recurring) item appears on a given date.
function showsOn(it, date, dateStr) {
  if (!it.recurring) return it.date === dateStr;
  if (it.start_date && dateStr < it.start_date) return false;
  if (it.end_date && dateStr > it.end_date) return false;
  if (it.dow !== (date.getDay() + 6) % 7) return false;
  if ((it.recur || "weekly") === "monthly") {
    return Math.floor((date.getDate() - 1) / 7) + 1 === (it.nth || 1);
  }
  return true;
}

function accountItems() {
  return Store.get().items.filter((it) => (it.account || "main") === account);
}

function accountProjects() {
  return Store.get().projects.filter((r) => (r.account || "main") === account);
}

function itemsForDate(date) {
  const dateStr = ymd(date);
  return accountItems().filter((it) => {
    if (branchFilter !== "all" && it.branch !== branchFilter) return false;
    return showsOn(it, date, dateStr);
  });
}

function weekStats(filterBranch) {
  let total = 0;
  let done = 0;
  for (let i = 0; i < 7; i++) {
    const date = addDays(weekStart, i);
    const dateStr = ymd(date);
    accountItems().forEach((it) => {
      if (filterBranch && it.branch !== filterBranch) return;
      if (branchFilter !== "all" && !filterBranch && it.branch !== branchFilter) return;
      if (!showsOn(it, date, dateStr)) return;
      total++;
      if (Store.isDone(it.id, dateStr)) done++;
    });
  }
  return { total, done };
}

function repeatLabel(it) {
  if (!it.recurring) return "";
  if ((it.recur || "weekly") === "monthly") {
    return `${NTH_NAMES[(it.nth || 1) - 1]} ${DAY_NAMES[it.dow].slice(0, 3)} monthly`;
  }
  return "weekly";
}

// ----- rendering -----
function render() {
  renderSyncBadge();
  renderBanner();
  const sel = document.getElementById("account-select");
  if (sel && sel.value !== account) sel.value = account;
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  const view = document.getElementById("view");
  if (tab === "week") view.innerHTML = renderWeek();
  else if (tab === "projects") view.innerHTML = renderProjects();
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
  } else if (Store.needsUpgrade()) {
    el.innerHTML =
      "<b>Database upgrade needed:</b> to save team names and week assignments, run <b>supabase/upgrade-team.sql</b> in the Supabase SQL Editor (it’s in the project files), then reload.";
  } else {
    el.innerHTML = "";
  }
}

function weekNavHtml() {
  const range = `${fmtShort(weekStart)} – ${fmtShort(addDays(weekStart, 6))}`;
  return `
    <div class="week-nav">
      <button class="icon-btn" data-action="week-prev" aria-label="Previous week">&#8249;</button>
      <label class="range jump" title="Jump to any week or month">
        ${range} <span class="jump-hint">&#9662;</span>
        <input type="date" id="jump-date" value="${ymd(weekStart)}" aria-label="Jump to date" />
      </label>
      <button class="pill-btn" data-action="week-today">Today</button>
      <button class="icon-btn" data-action="week-next" aria-label="Next week">&#8250;</button>
    </div>`;
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

function taskRowHtml(it, dateStr) {
  const done = Store.isDone(it.id, dateStr);
  const b = BRANCHES[it.branch] || BRANCHES.social;
  const rep = repeatLabel(it);
  const meta = [
    `<span class="bdot" style="background:${b.color}"></span><span>${esc(b.short)}</span>`,
    it.assignee ? `<span>&#128100; ${esc(it.assignee)}</span>` : "",
    rep ? `<span class="repeat-tag">&#8635; ${rep}</span>` : "",
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
    ${weekNavHtml()}
    ${chipsHtml()}
    <div class="progress-card">
      <div class="label"><span>This week · ${esc(ACCOUNTS[account])}</span><span>${done} of ${total} done</span></div>
      <div class="bar"><span style="width:${pct}%"></span></div>
    </div>
    ${weekAssignHtml()}
    ${days}`;
}

function weekAssignee() {
  const ws = ymd(weekStart);
  const wa = Store.get().week_assignments.find(
    (w) => (w.account || "main") === account && w.week_start === ws
  );
  return wa ? wa.assignee : "";
}

function weekAssignHtml() {
  const who = weekAssignee();
  return `
    <button type="button" class="week-assign ${who ? "" : "unset"}" data-action="assign-week">
      <span>&#128100; Posting this week:</span>
      <b>${who ? esc(who) : "no one yet"}</b>
      <span class="assign-link">${who ? "Change" : "Assign"}</span>
    </button>`;
}

function openWeekAssignModal() {
  const range = `${fmtShort(weekStart)} – ${fmtShort(addDays(weekStart, 6))}`;
  const current = weekAssignee();
  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" data-action="close-modal">
      <form class="modal" id="week-assign-form">
        <h2>Assign this week's posting</h2>
        <p class="hint" style="margin-top:-8px">Week of ${range} · ${esc(ACCOUNTS[account])}. One person covers every day of this week.</p>
        <div class="field">
          <label>Assigned to</label>
          ${assigneeFieldHtml(current)}
          <p class="hint">They'll be notified when assigned, plus a reminder each morning of the week when they open the app.</p>
        </div>
        <div class="modal-actions">
          ${current ? '<button type="button" class="danger-btn" data-action="unassign-week">Remove</button>' : ""}
          <button type="button" class="ghost-btn" data-action="close-modal">Cancel</button>
          <button type="submit" class="primary-btn">Save</button>
        </div>
      </form>
    </div>`;
  const form = document.getElementById("week-assign-form");
  wireAssigneeField(form);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    Store.setWeekAssignment(account, ymd(weekStart), readAssignee(form));
    closeModal();
  });
}

function renderProjects() {
  const projects = accountProjects();
  let sections = "";
  PROJECT_STATUSES.forEach(([key, label]) => {
    const group = projects.filter((r) => (r.status || "idea") === key);
    if (!group.length) return;
    sections += `<div class="section-title">${label} · ${group.length}</div>`;
    sections += group.map(projectCardHtml).join("");
  });
  if (!sections) {
    sections =
      '<div class="empty-state">No projects yet for ' + esc(ACCOUNTS[account]) + '.<br/>Tap <b>New project</b> to add your first idea.</div>';
  }
  return `
    <div class="projects-head">
      <h2>Projects</h2>
      <button class="primary-btn" data-action="add-project">+ New project</button>
    </div>
    ${sections}`;
}

function projectCardHtml(r) {
  const idx = Math.max(0, PROJECT_STATUSES.findIndex(([k]) => k === r.status));
  const pct = Math.round((idx / (PROJECT_STATUSES.length - 1)) * 100);
  const label = PROJECT_STATUSES[idx][1];
  const chipStyle = STATUS_COLORS[r.status] || STATUS_COLORS.idea;
  const next = PROJECT_STATUSES[idx + 1];
  return `
    <div class="project-card" data-action="edit-project" data-id="${r.id}">
      <div class="project-top">
        <div class="project-title">${esc(r.title)}</div>
        <span class="status-chip" style="background:${chipStyle}">${label}</span>
      </div>
      ${r.notes ? `<div class="project-notes">${esc(r.notes)}</div>` : ""}
      <div class="project-meta">
        ${r.assignee ? `<span>&#128100; ${esc(r.assignee)}</span>` : "<span>Unassigned</span>"}
        ${r.due_date ? `<span>&#128197; required by ${esc(r.due_date)}</span>` : ""}
      </div>
      <div class="bar project-bar"><span style="width:${pct}%"></span></div>
      ${
        next
          ? `<div class="project-actions"><button class="advance-btn" data-action="advance-project" data-id="${r.id}">Move to ${next[1]} &#8594;</button></div>`
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
      accountItems()
        .filter((it) => it.branch === key && showsOn(it, date, dateStr))
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

  return `${weekNavHtml()}${cards}`;
}

// ----- modals -----
function closeModal() {
  document.getElementById("modal-root").innerHTML = "";
}

// Assignee picker: dropdown of saved team names + a "new name" escape hatch.
function assigneeFieldHtml(current) {
  current = (current || "").trim();
  const names = Store.get().members.map((m) => m.name);
  if (current && !names.some((n) => n.toLowerCase() === current.toLowerCase())) names.push(current);
  names.sort((a, b) => a.localeCompare(b));
  const opts = ['<option value="">Unassigned</option>']
    .concat(
      names.map(
        (n) => `<option value="${esc(n)}" ${n.toLowerCase() === current.toLowerCase() ? "selected" : ""}>${esc(n)}</option>`
      )
    )
    .concat(['<option value="__new__">&#65291; New name&hellip;</option>'])
    .join("");
  return `
    <select name="assignee_select">${opts}</select>
    <input type="text" name="assignee_new" maxlength="80" placeholder="Type the new name" class="assignee-new" style="display:none" />`;
}

function wireAssigneeField(form) {
  form.assignee_select.addEventListener("change", () => {
    const isNew = form.assignee_select.value === "__new__";
    form.assignee_new.style.display = isNew ? "block" : "none";
    if (isNew) form.assignee_new.focus();
  });
}

// Read the chosen name and remember it in the shared team list.
function readAssignee(form) {
  const v = form.assignee_select.value;
  const name = (v === "__new__" ? form.assignee_new.value : v).trim();
  if (name) Store.addMember(name);
  return name;
}

function openItemModal(opts) {
  const editing = opts.id ? Store.get().items.find((i) => i.id === opts.id) : null;
  const it = editing || {
    title: "",
    notes: "",
    branch: opts.branch || (branchFilter !== "all" ? branchFilter : "social"),
    assignee: "",
    recurring: false,
    recur: "weekly",
    dow: 0,
    nth: 1,
    date: opts.date || ymd(new Date()),
  };
  const schedule = !it.recurring ? "once" : (it.recur || "weekly") === "monthly" ? "monthly" : "weekly";
  const branchOpts = Object.entries(BRANCHES)
    .map(([k, b]) => `<option value="${k}" ${it.branch === k ? "selected" : ""}>${b.name}</option>`)
    .join("");
  const dayOpts = DAY_NAMES.map(
    (d, i) => `<option value="${i}" ${(it.dow ?? 0) === i ? "selected" : ""}>${d}</option>`
  ).join("");
  const nthOpts = NTH_NAMES.map(
    (n, i) => `<option value="${i + 1}" ${(it.nth || 1) === i + 1 ? "selected" : ""}>${n}</option>`
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
          ${assigneeFieldHtml(it.assignee)}
        </div>
        <div class="field">
          <label>Notes</label>
          <textarea name="notes" maxlength="2000" placeholder="Caption ideas, links, details… (optional)">${esc(it.notes)}</textarea>
        </div>
        <div class="field">
          <label>When</label>
          <div class="radio-row">
            <label><input type="radio" name="schedule" value="once" ${schedule === "once" ? "checked" : ""}/> One date</label>
            <label><input type="radio" name="schedule" value="weekly" ${schedule === "weekly" ? "checked" : ""}/> Weekly</label>
            <label><input type="radio" name="schedule" value="monthly" ${schedule === "monthly" ? "checked" : ""}/> Monthly</label>
          </div>
          <input type="date" name="date" value="${esc(it.date || opts.date || ymd(new Date()))}" />
          <div class="row-2">
            <select name="nth">${nthOpts}</select>
            <select name="dow">${dayOpts}</select>
          </div>
        </div>
        ${
          editing && editing.recurring
            ? `<div class="field future-only">
                 <label class="check-label"><input type="checkbox" name="futureOnly" />
                 Apply changes from this week onward only (past weeks stay as they were)</label>
               </div>`
            : ""
        }
        <div class="modal-actions">
          ${
            editing
              ? `<button type="button" class="danger-btn" data-action="delete-item" data-id="${editing.id}">Delete</button>` +
                (editing.recurring
                  ? `<button type="button" class="ghost-btn" data-action="stop-item" data-id="${editing.id}" title="Keeps past weeks, removes it from this week on">Stop from this week</button>`
                  : "")
              : ""
          }
          <button type="button" class="ghost-btn" data-action="close-modal">Cancel</button>
          <button type="submit" class="primary-btn">${editing ? "Save" : "Add"}</button>
        </div>
      </form>
    </div>`;

  const form = document.getElementById("item-form");
  wireAssigneeField(form);
  const syncScheduleFields = () => {
    const s = form.schedule.value;
    form.date.style.display = s === "once" ? "block" : "none";
    form.querySelector(".row-2").style.display = s === "once" ? "none" : "flex";
    form.nth.style.display = s === "monthly" ? "block" : "none";
  };
  form.querySelectorAll('input[name="schedule"]').forEach((radio) =>
    radio.addEventListener("change", syncScheduleFields)
  );
  syncScheduleFields();

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const s = form.schedule.value;
    const fields = {
      account,
      title: form.title.value.trim(),
      branch: form.branch.value,
      assignee: readAssignee(form),
      notes: form.notes.value.trim(),
      recurring: s !== "once",
      recur: s === "monthly" ? "monthly" : "weekly",
      dow: s === "once" ? null : Number(form.dow.value),
      nth: s === "monthly" ? Number(form.nth.value) : null,
      date: s === "once" ? form.date.value || ymd(new Date()) : null,
    };
    if (!fields.title) return;
    if (editing) {
      const futureOnly = form.futureOnly && form.futureOnly.checked && editing.recurring && fields.recurring;
      if (futureOnly) {
        // Split: the old item ends before this week, a new one starts here.
        const boundary = ymd(weekStart);
        Store.updateItem(editing.id, { end_date: ymd(addDays(weekStart, -1)) });
        Store.addItem(Object.assign({}, fields, { start_date: boundary, end_date: null }));
      } else {
        Store.updateItem(editing.id, fields);
      }
    } else {
      Store.addItem(fields);
    }
    closeModal();
  });
  form.title.focus();
}

function openProjectModal(id) {
  const editing = id ? Store.get().projects.find((r) => r.id === id) : null;
  const r = editing || { title: "", notes: "", assignee: "", status: "idea", due_date: "" };
  const statusOpts = PROJECT_STATUSES.map(
    ([k, label]) => `<option value="${k}" ${r.status === k ? "selected" : ""}>${label}</option>`
  ).join("");

  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" data-action="close-modal">
      <form class="modal" id="project-form">
        <h2>${editing ? "Edit project" : "New project"}</h2>
        <div class="field">
          <label>Project title</label>
          <input type="text" name="title" required maxlength="200" value="${esc(r.title)}" placeholder="e.g. Youth night recap reel" />
        </div>
        <div class="field">
          <label>Idea / notes</label>
          <textarea name="notes" maxlength="2000" placeholder="Concept, shots, audio, caption…">${esc(r.notes)}</textarea>
        </div>
        <div class="field">
          <label>Assigned to</label>
          ${assigneeFieldHtml(r.assignee)}
          <p class="hint">They get a notification when you save (if they've set their name in Settings).</p>
        </div>
        <div class="field">
          <label>Status</label>
          <select name="status">${statusOpts}</select>
        </div>
        <div class="field">
          <label>Required by</label>
          <input type="date" name="due_date" value="${esc(r.due_date || "")}" />
        </div>
        <div class="modal-actions">
          ${editing ? '<button type="button" class="danger-btn" data-action="delete-project" data-id="' + editing.id + '">Delete</button>' : ""}
          <button type="button" class="ghost-btn" data-action="close-modal">Cancel</button>
          <button type="submit" class="primary-btn">${editing ? "Save" : "Add project"}</button>
        </div>
      </form>
    </div>`;

  const form = document.getElementById("project-form");
  wireAssigneeField(form);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const fields = {
      account,
      title: form.title.value.trim(),
      notes: form.notes.value.trim(),
      assignee: readAssignee(form),
      status: form.status.value,
      due_date: form.due_date.value || null,
    };
    if (!fields.title) return;
    if (editing) Store.updateProject(editing.id, fields);
    else Store.addProject(fields);
    closeModal();
  });
  form.title.focus();
}

function openSettingsModal() {
  const prefs = getPrefs();
  const granted = "Notification" in window && Notification.permission === "granted";
  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" data-action="close-modal">
      <form class="modal" id="settings-form">
        <h2>Settings</h2>
        <div class="field">
          <label>Your name</label>
          <input type="text" name="myName" maxlength="80" value="${esc(prefs.myName || "")}" placeholder="So assignments can find you" />
          <p class="hint">When a project is assigned to this name, this device gets a notification (needs team sync on and notifications allowed).</p>
        </div>
        <div class="field">
          <button type="button" class="ghost-btn" data-action="enable-notifications" ${granted ? "disabled" : ""}>
            ${granted ? "Notifications enabled ✓" : "Allow notifications on this device"}
          </button>
        </div>
        <div class="modal-actions">
          <button type="button" class="ghost-btn" data-action="close-modal">Cancel</button>
          <button type="submit" class="primary-btn">Save</button>
        </div>
      </form>
    </div>`;
  const form = document.getElementById("settings-form");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const myName = form.myName.value.trim();
    setPrefs({ myName });
    if (myName) Store.addMember(myName); // joins the shared assignment dropdown
    closeModal();
  });
}

// ----- assignment notifications (works while the app is open, team sync on) -----
let prevAssignees = null;
let prevWeekAssignees = null;

function canNotify() {
  const prefs = getPrefs();
  return (
    Store.getMode() === "remote" &&
    prefs.myName &&
    "Notification" in window &&
    Notification.permission === "granted"
  );
}

function notify(title, body) {
  try {
    new Notification(title, { body, icon: "icons/icon-192.png" });
  } catch (e) {
    console.error("Notification failed:", e);
  }
}

function checkAssignments() {
  const prefs = getPrefs();
  const me = (prefs.myName || "").trim().toLowerCase();
  const current = {};
  Store.get().projects.forEach((r) => {
    current[r.id] = r.assignee || "";
  });
  const currentWeeks = {};
  Store.get().week_assignments.forEach((w) => {
    currentWeeks[(w.account || "main") + "|" + w.week_start] = w.assignee || "";
  });

  if (prevAssignees && canNotify()) {
    Store.get().projects.forEach((r) => {
      const now = (r.assignee || "").trim().toLowerCase();
      const before = (prevAssignees[r.id] || "").trim().toLowerCase();
      if (now === me && before !== me) {
        notify("New project assigned to you", r.title);
      }
    });
    Object.entries(currentWeeks).forEach(([key, who]) => {
      const before = ((prevWeekAssignees || {})[key] || "").trim().toLowerCase();
      if (who.trim().toLowerCase() === me && before !== me) {
        const [acct, ws] = key.split("|");
        const [y, m, d] = ws.split("-").map(Number);
        notify(
          "You're on posting duty",
          `Week of ${fmtShort(new Date(y, m - 1, d))} · ${ACCOUNTS[acct] || acct}`
        );
      }
    });
  }
  prevAssignees = current;
  prevWeekAssignees = currentWeeks;
}

// Once per day, on the first open of the app: if I'm on posting duty this
// week, remind me what's due today.
function morningReminder() {
  if (!canNotify()) return;
  const prefs = getPrefs();
  const me = prefs.myName.trim().toLowerCase();
  const today = new Date();
  const todayStr = ymd(today);
  if (prefs.lastReminder === todayStr) return;
  const ws = ymd(startOfWeek(today));
  const mine = Store.get().week_assignments.filter(
    (w) => w.week_start === ws && (w.assignee || "").trim().toLowerCase() === me
  );
  if (!mine.length) return;
  let due = 0;
  mine.forEach((w) => {
    Store.get().items.forEach((it) => {
      if ((it.account || "main") !== (w.account || "main")) return;
      if (showsOn(it, today, todayStr) && !Store.isDone(it.id, todayStr)) due++;
    });
  });
  setPrefs({ lastReminder: todayStr });
  notify(
    "You're on posting today",
    due
      ? `${due} item${due === 1 ? "" : "s"} to post today (${mine.map((w) => ACCOUNTS[w.account || "main"]).join(", ")})`
      : "Nothing left to post today — all done or nothing scheduled."
  );
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") morningReminder();
});

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
      const { id, date } = el.dataset;
      Store.setDone(id, date, !Store.isDone(id, date));
      break;
    }
    case "add-item":
      openItemModal({ date: el.dataset.date, branch: el.dataset.branch });
      break;
    case "edit-item":
      if (e.target.closest('[data-action="toggle-done"]')) break;
      openItemModal({ id: el.dataset.id, date: el.dataset.date });
      break;
    case "add-project":
      openProjectModal();
      break;
    case "edit-project":
      if (e.target.closest('[data-action="advance-project"]')) break;
      openProjectModal(el.dataset.id);
      break;
    case "advance-project": {
      const project = Store.get().projects.find((r) => r.id === el.dataset.id);
      if (!project) break;
      const idx = PROJECT_STATUSES.findIndex(([k]) => k === project.status);
      const next = PROJECT_STATUSES[idx + 1];
      if (next) Store.updateProject(project.id, { status: next[0] });
      break;
    }
    case "stop-item":
      if (confirm("Remove this from this week onward? Past weeks keep it.")) {
        Store.updateItem(el.dataset.id, { end_date: ymd(addDays(weekStart, -1)) });
        closeModal();
      }
      break;
    case "delete-item":
      if (confirm("Delete this item everywhere (including past weeks)?")) {
        Store.deleteItem(el.dataset.id);
        closeModal();
      }
      break;
    case "delete-project":
      if (confirm("Delete this project?")) {
        Store.deleteProject(el.dataset.id);
        closeModal();
      }
      break;
    case "assign-week":
      openWeekAssignModal();
      break;
    case "unassign-week":
      Store.setWeekAssignment(account, ymd(weekStart), "");
      closeModal();
      break;
    case "settings":
      openSettingsModal();
      break;
    case "enable-notifications":
      if ("Notification" in window) {
        Notification.requestPermission().then(() => openSettingsModal());
      } else {
        alert("This browser does not support notifications.");
      }
      break;
    case "close-modal":
      closeModal();
      break;
  }
});

// Jump to any week via the native date picker on the week-range label.
document.addEventListener("change", (e) => {
  if (e.target.id === "jump-date" && e.target.value) {
    const [y, m, d] = e.target.value.split("-").map(Number);
    weekStart = startOfWeek(new Date(y, m - 1, d));
    render();
  } else if (e.target.id === "account-select") {
    account = e.target.value;
    setPrefs({ account });
    render();
  }
});

// ----- boot -----
function initAccountSelect() {
  const sel = document.getElementById("account-select");
  sel.innerHTML = Object.entries(ACCOUNTS)
    .map(([k, name]) => `<option value="${k}">${name}</option>`)
    .join("");
  sel.value = account;
}

initAccountSelect();
Store.onChange(() => {
  checkAssignments();
  morningReminder();
  render();
});
Store.init();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((e) => console.error("SW failed:", e));
  });
}
