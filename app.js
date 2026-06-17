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
let tab = ["week", "projects", "requests", "teams"].includes(location.hash.slice(1))
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
  // A one-week override/skip hides the recurring item on that single date.
  if (Store.isException(it.id, dateStr)) return false;
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
  renderRequestsBadge();
  const view = document.getElementById("view");
  if (tab === "week") view.innerHTML = renderWeek();
  else if (tab === "projects") view.innerHTML = renderProjects();
  else if (tab === "requests") view.innerHTML = renderRequests();
  else view.innerHTML = renderTeams();
}

// Little count bubble on the Requests tab when there are pending requests.
function renderRequestsBadge() {
  const tabBtn = document.querySelector('.tab[data-tab="requests"]');
  if (!tabBtn) return;
  const pending = Store.get().requests.filter((r) => (r.status || "pending") === "pending").length;
  let dot = tabBtn.querySelector(".tab-badge");
  if (pending) {
    if (!dot) {
      dot = document.createElement("span");
      dot.className = "tab-badge";
      tabBtn.appendChild(dot);
    }
    dot.textContent = pending > 9 ? "9+" : String(pending);
  } else if (dot) {
    dot.remove();
  }
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
      "<b>Database upgrade needed:</b> to enable team names, week duty, single-week edits, links and requests, run <b>supabase/upgrade.sql</b> in the Supabase SQL Editor (it’s in the project files), then reload.";
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
            ? `<div class="field scope-field">
                 <label>Apply this change to</label>
                 <div class="radio-col">
                   <label><input type="radio" name="scope" value="one" checked /> <span><b>Just this week</b> — other weeks stay the same</span></label>
                   <label><input type="radio" name="scope" value="future" /> <span><b>This week and all future weeks</b> — past weeks unchanged</span></label>
                   <label><input type="radio" name="scope" value="all" /> <span><b>Every week</b> — change the standing schedule</span></label>
                 </div>
               </div>`
            : ""
        }
        <div class="modal-actions">
          ${
            editing
              ? `<button type="button" class="danger-btn" data-action="delete-item" data-id="${editing.id}" data-date="${esc(opts.date || "")}">Delete</button>` +
                (editing.recurring
                  ? `<button type="button" class="ghost-btn" data-action="stop-item" data-id="${editing.id}" title="Keeps past weeks, removes it from this week onward">Stop future weeks</button>`
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
      // Scope only applies when an existing recurring item stays recurring.
      const scope = form.scope && editing.recurring && fields.recurring ? form.scope.value : "all";
      if (scope === "one") {
        // Override just this occurrence: hide the original on that date and
        // drop a one-off copy carrying the edited details.
        const target = occurrenceDate(editing, opts.date);
        Store.addException(editing.id, target);
        Store.addItem(
          Object.assign({}, fields, {
            recurring: false,
            date: target,
            start_date: null,
            end_date: null,
          })
        );
      } else if (scope === "future") {
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

// The specific date a recurring item is being edited on — the tapped date if
// we have it, otherwise that item's day within the currently shown week.
function occurrenceDate(it, dateStr) {
  if (dateStr) return dateStr;
  return ymd(addDays(weekStart, it.dow ?? 0));
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

// ----- quick links -----
function openLinksModal() {
  const links = Store.get().links;
  const rows = links.length
    ? links
        .map(
          (l) => `
        <div class="link-row">
          <a class="link-main" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">
            <span class="link-label">${esc(l.label || l.url)}</span>
            <span class="link-url">${esc(l.url)}</span>
          </a>
          <button class="icon-btn" data-action="edit-link" data-id="${l.id}" aria-label="Edit link">&#9998;</button>
          <button class="icon-btn" data-action="delete-link" data-id="${l.id}" aria-label="Delete link">&#128465;</button>
        </div>`
        )
        .join("")
    : '<div class="day-empty">No links yet — add Drive folders, Canva, schedules…</div>';
  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" data-action="close-modal">
      <div class="modal" id="links-modal">
        <h2>Quick links</h2>
        <p class="hint" style="margin-top:-8px">Shared with the whole team — Google Drive, Canva, folders and more.</p>
        <div class="link-list">${rows}</div>
        <div class="modal-actions">
          <button type="button" class="ghost-btn" data-action="close-modal">Close</button>
          <button type="button" class="primary-btn" data-action="add-link">+ Add link</button>
        </div>
      </div>
    </div>`;
}

function openLinkModal(id) {
  const editing = id ? Store.get().links.find((l) => l.id === id) : null;
  const l = editing || { label: "", url: "" };
  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" data-action="close-modal">
      <form class="modal" id="link-form">
        <h2>${editing ? "Edit link" : "Add link"}</h2>
        <div class="field">
          <label>Name</label>
          <input type="text" name="label" required maxlength="80" value="${esc(l.label)}" placeholder="e.g. Reels Drive folder" />
        </div>
        <div class="field">
          <label>Link (URL)</label>
          <input type="text" name="url" required maxlength="500" value="${esc(l.url)}" placeholder="paste the link here" />
        </div>
        <div class="modal-actions">
          ${editing ? `<button type="button" class="danger-btn" data-action="delete-link" data-id="${editing.id}">Delete</button>` : ""}
          <button type="button" class="ghost-btn" data-action="open-links">Cancel</button>
          <button type="submit" class="primary-btn">${editing ? "Save" : "Add"}</button>
        </div>
      </form>
    </div>`;
  const form = document.getElementById("link-form");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const fields = { label: form.label.value.trim(), url: form.url.value.trim() };
    if (!fields.label || !fields.url) return;
    if (editing) Store.updateLink(editing.id, fields);
    else Store.addLink(fields);
    openLinksModal();
  });
  form.label.focus();
}

// ----- requests -----
const REQUEST_STATUS = { pending: "Pending", approved: "Approved", declined: "Declined" };

function renderRequests() {
  const all = Store.get().requests;
  const pending = all.filter((r) => (r.status || "pending") === "pending");
  const handled = all.filter((r) => (r.status || "pending") !== "pending");

  const card = (r) => {
    const acct = ACCOUNTS[r.account || "main"] || "Main Church";
    const isPending = (r.status || "pending") === "pending";
    return `
      <div class="request-card ${isPending ? "" : "muted"}">
        <div class="request-top">
          <div class="request-title">${esc(r.title)}</div>
          <span class="status-chip" style="background:${
            r.status === "approved" ? STATUS_COLORS.ready : r.status === "declined" ? "#FFE9EF;color:#D03A6B" : "#EAF1FF;color:#1E5BD6"
          }">${REQUEST_STATUS[r.status] || "Pending"}</span>
        </div>
        ${r.details ? `<div class="request-notes">${esc(r.details)}</div>` : ""}
        <div class="request-meta">
          <span>&#127991; ${esc(acct)}</span>
          ${r.requested_by ? `<span>&#128100; ${esc(r.requested_by)}</span>` : ""}
        </div>
        ${
          isPending
            ? `<div class="request-actions">
                 <button class="advance-btn" data-action="approve-request" data-id="${r.id}">Approve &amp; add to projects &#8594;</button>
                 <button class="ghost-btn small" data-action="decline-request" data-id="${r.id}">Decline</button>
               </div>`
            : `<div class="request-actions"><button class="ghost-btn small" data-action="delete-request" data-id="${r.id}">Remove</button></div>`
        }
      </div>`;
  };

  let body = "";
  body += pending.length
    ? `<div class="section-title">To review · ${pending.length}</div>` + pending.map(card).join("")
    : '<div class="empty-state">No requests waiting.<br/>Other teams can tap <b>New request</b> to ask for content.</div>';
  if (handled.length) {
    body += `<div class="section-title">Handled · ${handled.length}</div>` + handled.map(card).join("");
  }

  return `
    <div class="projects-head">
      <h2>Requests</h2>
      <button class="primary-btn" data-action="add-request">+ New request</button>
    </div>
    <p class="hint" style="margin:-6px 0 14px">Anyone can request content or a project here. Approve to send it to the Projects pipeline, then assign it.</p>
    ${body}`;
}

function openRequestModal(id) {
  const editing = id ? Store.get().requests.find((r) => r.id === id) : null;
  const r = editing || { title: "", details: "", requested_by: getPrefs().myName || "", account };
  const acctOpts = Object.entries(ACCOUNTS)
    .map(([k, name]) => `<option value="${k}" ${ (r.account || "main") === k ? "selected" : ""}>${name}</option>`)
    .join("");
  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" data-action="close-modal">
      <form class="modal" id="request-form">
        <h2>${editing ? "Edit request" : "New request"}</h2>
        <div class="field">
          <label>What do you need?</label>
          <input type="text" name="title" required maxlength="200" value="${esc(r.title)}" placeholder="e.g. Reel to promote youth weekend" />
        </div>
        <div class="field">
          <label>Details</label>
          <textarea name="details" maxlength="2000" placeholder="Dates, key info, who/what, any references…">${esc(r.details)}</textarea>
        </div>
        <div class="field">
          <label>Your name</label>
          <input type="text" name="requested_by" maxlength="80" value="${esc(r.requested_by)}" placeholder="So we know who asked" />
        </div>
        <div class="field">
          <label>For which account</label>
          <select name="account">${acctOpts}</select>
        </div>
        <div class="modal-actions">
          <button type="button" class="ghost-btn" data-action="close-modal">Cancel</button>
          <button type="submit" class="primary-btn">${editing ? "Save" : "Send request"}</button>
        </div>
      </form>
    </div>`;
  const form = document.getElementById("request-form");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const fields = {
      title: form.title.value.trim(),
      details: form.details.value.trim(),
      requested_by: form.requested_by.value.trim(),
      account: form.account.value,
    };
    if (!fields.title) return;
    if (editing) Store.updateRequest(editing.id, fields);
    else Store.addRequest(fields);
    closeModal();
  });
  form.title.focus();
}

// Turn a request into a project (unassigned), then mark it approved.
function approveRequest(id) {
  const r = Store.get().requests.find((x) => x.id === id);
  if (!r) return;
  const notes = [r.details, r.requested_by ? `Requested by ${r.requested_by}` : ""]
    .filter(Boolean)
    .join("\n\n");
  Store.addProject({ account: r.account || "main", title: r.title, notes, status: "idea" });
  Store.updateRequest(id, { status: "approved" });
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
    case "links":
    case "open-links":
      openLinksModal();
      break;
    case "add-link":
      openLinkModal();
      break;
    case "edit-link":
      openLinkModal(el.dataset.id);
      break;
    case "delete-link":
      if (confirm("Delete this link?")) {
        Store.deleteLink(el.dataset.id);
        openLinksModal();
      }
      break;
    case "add-request":
      openRequestModal();
      break;
    case "approve-request":
      approveRequest(el.dataset.id);
      break;
    case "decline-request":
      if (confirm("Decline this request?")) Store.updateRequest(el.dataset.id, { status: "declined" });
      break;
    case "delete-request":
      if (confirm("Remove this request?")) Store.deleteRequest(el.dataset.id);
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
