/*
 * Data layer. Two modes:
 *  - "remote": Supabase configured in config.js -> shared team data with
 *    realtime updates.
 *  - "local": no config (or Supabase unreachable) -> data lives in
 *    localStorage on this device only.
 *
 * Data model:
 *  items:        scheduled posts/tasks, each belonging to an account.
 *                One-off (date) or recurring: weekly (dow 0=Mon..6=Sun) or
 *                monthly (nth weekday of the month, e.g. 3rd Wednesday).
 *                Optional start_date/end_date bound a recurring item so
 *                changes can apply "from this week onward" without
 *                rewriting history.
 *  completions:  one row per (item_id, date) marked done.
 *  projects:     reels/projects with assignee, pipeline status and a
 *                "required by" date, per account.
 *  members:      team member names (populate assignment dropdowns).
 *  week_assignments: who is on posting duty for a week, per account.
 */
window.Store = (() => {
  const LS_KEY = "expression-data-v2";

  const EMPTY = { items: [], completions: [], projects: [], members: [], week_assignments: [] };

  let mode = "local"; // "local" | "remote" | "local-error"
  let sb = null;
  let upgradeNeeded = false; // remote DB missing the members/week_assignments tables
  let state = Object.assign({}, EMPTY);
  const listeners = [];

  const uid = () =>
    crypto.randomUUID
      ? crypto.randomUUID()
      : "id-" + Date.now() + "-" + Math.random().toString(36).slice(2);

  function emit() {
    listeners.forEach((fn) => fn());
  }

  function onChange(fn) {
    listeners.push(fn);
  }

  // ----- local persistence -----
  function saveLocal() {
    localStorage.setItem(LS_KEY, JSON.stringify(state));
  }

  function loadLocal() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) {
        // Older saves predate some collections; fill in what's missing.
        state = Object.assign({}, EMPTY, JSON.parse(raw));
        return;
      }
    } catch (e) {
      console.error("Could not read saved data:", e);
    }
    state = seedData();
    saveLocal();
  }

  // The Main Church standard weekly Instagram schedule, from the team's
  // posting calendar. Everything is editable in the app.
  function seedData() {
    const w = (dow, title, notes, branch) => ({
      id: uid(), account: "main", title, notes: notes || "", branch: branch || "social",
      assignee: "", recurring: true, recur: "weekly", dow, nth: null,
      date: null, start_date: null, end_date: null,
    });
    const m = (nth, dow, title, notes) => Object.assign(w(dow, title, notes), { recur: "monthly", nth });
    const p = (title, notes, assignee, status, due) => ({
      id: uid(), account: "main", title, notes: notes || "", assignee: assignee || "",
      status: status || "idea", due_date: due || null,
    });
    return {
      members: [],
      week_assignments: [],
      items: [
        // Monday
        w(0, "Story Recap", "Worship moment + key quote + Scripture + CTA + poll · 08:00–10:00"),
        w(0, "Invite to Prayer Story", "Use video from drive · 08:00–10:00"),
        w(0, "Sunday Reel", "Include engagement sticker (poll/question) · 08:00–10:00"),
        w(0, "Upload Sunday sermon to YouTube", "", "editing"),
        // Tuesday
        w(1, "Prayer Story", "Scripture + prayer prompt + question sticker · 08:00–10:00"),
        w(1, "Podcast/YT Promo Story", "20-sec audiogram + subtitles + CTA: Listen on Spotify · 08:00–10:00"),
        w(1, "Expect Group Story", "Real face + 10-sec testimony + poll: Want info? · 08:00–10:00"),
        w(1, "Cut sermon highlights for Spotify podcast", "", "editing"),
        // Wednesday
        w(2, "Expect Socials Story", "Real face + 10-sec testimony + poll: Want info? · 08:00–10:00"),
        w(2, "Join a Team Story", "Real face + 10-sec testimony + poll: Want info? · 08:00–10:00"),
        m(1, 2, "Expect Group Reel", "1st Wednesday of the month"),
        m(3, 2, "Expect Socials Reel", "3rd Wednesday of the month"),
        // Thursday
        w(3, "Established Post/Story", "Graphic from drive · 08:00–10:00"),
        w(3, "Anthems Story", "Worship clip overlay + text: This has been on repeat · 08:00–10:00"),
        w(3, "Worship rehearsal/worship story", ""),
        m(3, 3, "Testimony Thursday Reel", "3rd Thursday of the month — special projects"),
        // Friday
        w(4, "Sunday Teaser Story", "Pastor 15-sec invite + sermon reveal (if clip on drive) · 08:00–10:00"),
        w(4, "Youth Repost Story", "Add text overlay + tag someone sticker · evening"),
        w(4, "Sermon Clip Reel", "Clip sent from media team · 08:00–10:00"),
        // Saturday
        w(5, "Encouragement Carousel", "Hook + Scripture + why Sunday matters + service time · 10:00"),
        w(5, "Countdown Story", "Who are you bringing? + location + parking · 10:00"),
        // Sunday
        w(6, "Service day — live stories + photo coverage", "", "media"),
      ],
      completions: [],
      projects: [
        p("Summer social reel", "One person sitting at table alone, 2 others come sit down — 1st person says 'don't have a boring summer, come to summer social next week' + details, get off Planning Centre.", "Nesser", "posted"),
        p("SOCIALS reel — 3rd Wednesday", "Love heart & phone: https://www.instagram.com/reel/C7Q5Rl9Czpx/", "Nesser", "filming"),
        p("ALPHA Course", "Testimony, shopping centre, one person in crowd speaking looking at camera.", "Nesser", "filming", "2026-06-15"),
        p("VISION Sunday", "Face to camera, photos with text of the people. Voice-over video of church at end — the vision is the people.", "Nesser", "idea", "2026-06-22"),
        p("Wave at stool", "To be edited — Daniel to send raw footage.", "Andreea", "editing"),
        p("Pastoral care team", "Reel to promote pastoral care and explain what it is.", "Nesser", "idea"),
        p("Baptism", "Promote baptism — EQUIP, explain what baptism is.", "Nesser", "idea", "2026-06-22"),
      ],
    };
  }

  // ----- remote (Supabase) -----
  async function fetchAll() {
    const [items, completions, projects, members, weekAssignments] = await Promise.all([
      sb.from("items").select("*").order("created_at"),
      sb.from("completions").select("*"),
      sb.from("projects").select("*").order("created_at"),
      sb.from("members").select("*").order("name"),
      sb.from("week_assignments").select("*"),
    ]);
    const err = items.error || completions.error || projects.error;
    if (err) throw err;
    // members/week_assignments arrived in a later upgrade; if those tables
    // don't exist yet the rest of the app must keep working.
    upgradeNeeded = !!(members.error || weekAssignments.error);
    state = {
      items: items.data,
      completions: completions.data,
      projects: projects.data,
      members: members.error ? [] : members.data,
      week_assignments: weekAssignments.error ? [] : weekAssignments.data,
    };
  }

  async function init() {
    const cfg = window.EXPRESSION_CONFIG || {};
    if (cfg.SUPABASE_URL && cfg.SUPABASE_ANON_KEY && window.supabase) {
      try {
        sb = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
        await fetchAll();
        mode = "remote";
        sb.channel("db-changes")
          .on("postgres_changes", { event: "*", schema: "public" }, async () => {
            try {
              await fetchAll();
              emit();
            } catch (e) {
              console.error("Realtime refresh failed:", e);
            }
          })
          .subscribe();
      } catch (e) {
        console.error("Supabase unavailable, falling back to this device only:", e);
        mode = "local-error";
        sb = null;
        loadLocal();
      }
    } else {
      loadLocal();
    }
    emit();
  }

  function remoteFail(error) {
    console.error(error);
    alert("Could not save to the team database. Check your connection and try again.");
  }

  async function afterRemoteWrite() {
    try {
      await fetchAll();
    } catch (e) {
      console.error(e);
    }
    emit();
  }

  // ----- items -----
  function itemRow(it) {
    const recurring = !!it.recurring;
    return {
      id: it.id,
      account: it.account || "main",
      title: it.title,
      notes: it.notes || "",
      branch: it.branch,
      assignee: it.assignee || "",
      recurring,
      recur: recurring ? it.recur || "weekly" : null,
      dow: recurring ? it.dow : null,
      nth: recurring && it.recur === "monthly" ? it.nth || 1 : null,
      date: recurring ? null : it.date,
      start_date: recurring ? it.start_date || null : null,
      end_date: recurring ? it.end_date || null : null,
    };
  }

  async function addItem(fields) {
    const it = itemRow(Object.assign({ id: uid() }, fields));
    if (sb) {
      const { error } = await sb.from("items").insert(it);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.items.push(it);
    saveLocal();
    emit();
  }

  async function updateItem(id, fields) {
    const current = state.items.find((i) => i.id === id);
    if (!current) return;
    const next = itemRow(Object.assign({}, current, fields, { id }));
    if (sb) {
      const { error } = await sb.from("items").update(next).eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    Object.assign(current, next);
    saveLocal();
    emit();
  }

  async function deleteItem(id) {
    if (sb) {
      const { error } = await sb.from("items").delete().eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.items = state.items.filter((i) => i.id !== id);
    state.completions = state.completions.filter((c) => c.item_id !== id);
    saveLocal();
    emit();
  }

  // ----- completions -----
  function isDone(itemId, date) {
    return state.completions.some((c) => c.item_id === itemId && c.date === date);
  }

  async function setDone(itemId, date, done) {
    if (sb) {
      const { error } = done
        ? await sb
            .from("completions")
            .upsert({ id: uid(), item_id: itemId, date }, { onConflict: "item_id,date", ignoreDuplicates: true })
        : await sb.from("completions").delete().eq("item_id", itemId).eq("date", date);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    if (done) {
      if (!isDone(itemId, date)) state.completions.push({ id: uid(), item_id: itemId, date });
    } else {
      state.completions = state.completions.filter((c) => !(c.item_id === itemId && c.date === date));
    }
    saveLocal();
    emit();
  }

  // ----- projects -----
  function projectRow(r) {
    return {
      id: r.id,
      account: r.account || "main",
      title: r.title,
      notes: r.notes || "",
      assignee: r.assignee || "",
      status: r.status || "idea",
      due_date: r.due_date || null,
    };
  }

  async function addProject(fields) {
    const r = projectRow(Object.assign({ id: uid() }, fields));
    if (sb) {
      const { error } = await sb.from("projects").insert(r);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.projects.push(r);
    saveLocal();
    emit();
  }

  async function updateProject(id, fields) {
    const current = state.projects.find((r) => r.id === id);
    if (!current) return;
    const next = projectRow(Object.assign({}, current, fields, { id }));
    if (sb) {
      const { error } = await sb.from("projects").update(next).eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    Object.assign(current, next);
    saveLocal();
    emit();
  }

  async function deleteProject(id) {
    if (sb) {
      const { error } = await sb.from("projects").delete().eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.projects = state.projects.filter((r) => r.id !== id);
    saveLocal();
    emit();
  }

  // ----- members -----
  async function addMember(name) {
    name = (name || "").trim();
    if (!name) return;
    if (state.members.some((m) => m.name.toLowerCase() === name.toLowerCase())) return;
    if (sb) {
      // Not worth an error popup — the assignment itself still saves.
      const { error } = await sb
        .from("members")
        .upsert({ name }, { onConflict: "name", ignoreDuplicates: true });
      if (error) return console.error("Could not save member name:", error);
      return afterRemoteWrite();
    }
    state.members.push({ id: uid(), name });
    saveLocal();
    emit();
  }

  // ----- week assignments (posting duty for a whole week) -----
  async function setWeekAssignment(acct, weekStartStr, assignee) {
    assignee = (assignee || "").trim();
    if (sb) {
      const { error } = assignee
        ? await sb
            .from("week_assignments")
            .upsert({ account: acct, week_start: weekStartStr, assignee }, { onConflict: "account,week_start" })
        : await sb.from("week_assignments").delete().eq("account", acct).eq("week_start", weekStartStr);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.week_assignments = state.week_assignments.filter(
      (w) => !(w.account === acct && w.week_start === weekStartStr)
    );
    if (assignee) {
      state.week_assignments.push({ id: uid(), account: acct, week_start: weekStartStr, assignee });
    }
    saveLocal();
    emit();
  }

  // ----- push notifications (only meaningful with team sync on) -----
  async function savePushSubscription(name, subscription) {
    if (!sb) return;
    const endpoint = subscription.endpoint;
    const { error } = await sb
      .from("push_subscriptions")
      .upsert({ name, endpoint, subscription }, { onConflict: "endpoint" });
    if (error) console.error("Could not save push subscription:", error);
  }

  async function removePushSubscription(endpoint) {
    if (!sb || !endpoint) return;
    await sb.from("push_subscriptions").delete().eq("endpoint", endpoint);
  }

  // Ask the Edge Function to deliver a push to a named teammate's devices.
  // Best-effort: a missing function or offline assigner must never block
  // the assignment itself, so failures are only logged.
  async function sendPush(payload) {
    if (!sb || !sb.functions) return;
    try {
      const { error } = await sb.functions.invoke("push", { body: payload });
      if (error) console.error("Push send failed:", error);
    } catch (e) {
      console.error("Push send failed:", e);
    }
  }

  return {
    init,
    onChange,
    get: () => state,
    getMode: () => mode,
    needsUpgrade: () => upgradeNeeded,
    savePushSubscription,
    removePushSubscription,
    sendPush,
    isDone,
    addItem,
    updateItem,
    deleteItem,
    setDone,
    addProject,
    updateProject,
    deleteProject,
    addMember,
    setWeekAssignment,
  };
})();
