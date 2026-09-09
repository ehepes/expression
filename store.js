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
 *  item_exceptions: dates a recurring item is overridden/skipped, so an
 *                edit can apply to just one week.
 *  links:        shared quick links (Google Drive, Canva, …).
 *  requests:     content/project requests from other teams, to review and
 *                turn into projects.
 */
window.Store = (() => {
  const LS_KEY = "expression-data-v2";

  const EMPTY = {
    items: [],
    completions: [],
    projects: [],
    members: [],
    week_assignments: [],
    item_exceptions: [],
    links: [],
    requests: [],
    focus_weeks: [],
    focus_ideas: [],
  };

  let mode = "local"; // "local" | "remote" | "local-error"
  let sb = null;
  let upgradeNeeded = false; // remote DB missing the members/week_assignments tables
  let state = Object.assign({}, EMPTY);
  const listeners = [];

  // ----- auth (only meaningful in remote mode) -----
  let user = null; // Supabase auth user, or null when signed out
  let profile = null; // row from `profiles` (carries the person's role)
  let authReady = false; // we've finished checking for an existing session
  let realtimeSub = false; // realtime channel subscribed once
  const authListeners = [];
  const onAuth = (fn) => authListeners.push(fn);
  const emitAuth = () => authListeners.forEach((fn) => fn());
  // Staff = full app. Requester = request-only. No profile yet in remote mode
  // means the DB is still open (pre-lockdown) so treat as staff.
  const isStaff = () => !profile || profile.role === "admin" || profile.role === "editor";

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
      date: null, start_date: null, end_date: null, asset_url: "",
    });
    const m = (nth, dow, title, notes) => Object.assign(w(dow, title, notes), { recur: "monthly", nth });
    // Weekly standing checklist task (Media / Editing): recurs every week with
    // no fixed day (dow null), ticked off once per week.
    const c = (branch, title, notes) => Object.assign(w(null, title, notes, branch), { dow: null });
    const p = (title, notes, assignee, status, due) => ({
      id: uid(), account: "main", title, notes: notes || "", assignee: assignee || "",
      status: status || "idea", due_date: due || null,
    });
    return {
      members: [],
      week_assignments: [],
      item_exceptions: [],
      links: [],
      requests: [],
      items: [
        // Monday
        w(0, "Story Recap", "Worship moment + key quote + Scripture + CTA + poll · 08:00–10:00"),
        w(0, "Invite to Prayer Story", "Use video from drive · 08:00–10:00"),
        w(0, "Sunday Reel", "Include engagement sticker (poll/question) · 08:00–10:00"),
        // Tuesday
        w(1, "Prayer Story", "Scripture + prayer prompt + question sticker · 08:00–10:00"),
        w(1, "Podcast/YT Promo Story", "20-sec audiogram + subtitles + CTA: Listen on Spotify · 08:00–10:00"),
        w(1, "Expect Group Story", "Real face + 10-sec testimony + poll: Want info? · 08:00–10:00"),
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
        // Editing team — weekly standing tasks (no fixed day)
        c("editing", "Edit Spotify"),
        c("editing", "Post Spotify"),
        c("editing", "Edit YouTube"),
        c("editing", "Post YouTube"),
        // Media team starts with a blank weekly shoot list — added in-app.
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
    const [
      items,
      completions,
      projects,
      members,
      weekAssignments,
      exceptions,
      links,
      requests,
      focusWeeks,
      focusIdeas,
    ] = await Promise.all([
      sb.from("items").select("*").order("created_at"),
      sb.from("completions").select("*"),
      sb.from("projects").select("*").order("created_at"),
      sb.from("members").select("*").order("name"),
      sb.from("week_assignments").select("*"),
      sb.from("item_exceptions").select("*"),
      sb.from("links").select("*").order("sort").order("created_at"),
      sb.from("requests").select("*").order("created_at"),
      sb.from("focus_weeks").select("*"),
      sb.from("focus_ideas").select("*").order("created_at"),
    ]);
    // Never throw: a per-table error can mean "not allowed" (a requester
    // has no access to staff tables) or a transient network blip. In both
    // cases we keep the last known rows for that table instead of wiping
    // the screen. Staff-table errors only flag an upgrade for staff users.
    upgradeNeeded =
      isStaff() &&
      !!(
        members.error ||
        weekAssignments.error ||
        exceptions.error ||
        links.error ||
        focusWeeks.error ||
        focusIdeas.error
      );
    const keep = (res, prev) => (res.error ? prev : res.data || []);
    state = {
      items: keep(items, state.items),
      completions: keep(completions, state.completions),
      projects: keep(projects, state.projects),
      members: keep(members, state.members),
      week_assignments: keep(weekAssignments, state.week_assignments),
      item_exceptions: keep(exceptions, state.item_exceptions),
      links: keep(links, state.links),
      requests: keep(requests, state.requests),
      focus_weeks: keep(focusWeeks, state.focus_weeks),
      focus_ideas: keep(focusIdeas, state.focus_ideas),
    };
  }

  function subscribeRealtime() {
    if (realtimeSub) return;
    realtimeSub = true;
    sb.channel("db-changes")
      .on("postgres_changes", { event: "*", schema: "public" }, async () => {
        try {
          await refreshProfile(); // pick up a role change made by an admin
          await fetchAll();
          emit();
        } catch (e) {
          console.error("Realtime refresh failed:", e);
        }
      })
      .subscribe();
  }

  // Reload the signed-in person's profile; if their role changed (e.g. an admin
  // promoted them), tell the app so it can swap them into the right view live.
  async function refreshProfile() {
    if (!user) return;
    const before = profile ? profile.role : null;
    await loadProfile();
    const after = profile ? profile.role : null;
    if (before !== after) emitAuth();
  }

  // Load the signed-in person's profile (which carries their role). If the
  // signup trigger hasn't created a row yet, create a requester row.
  async function loadProfile() {
    if (!user) {
      profile = null;
      return;
    }
    const { data, error } = await sb.from("profiles").select("*").eq("id", user.id).maybeSingle();
    if (error) {
      console.error("Could not load profile:", error);
      profile = null;
      return;
    }
    profile = data;
    if (!profile) {
      const row = {
        id: user.id,
        email: user.email,
        name: (user.user_metadata && user.user_metadata.name) || "",
        role: "requester",
      };
      const ins = await sb.from("profiles").insert(row).select("*").maybeSingle();
      if (!ins.error) profile = ins.data;
    }
  }

  // React to a session appearing/disappearing (sign in, sign out, restore).
  async function handleAuth(session) {
    user = session ? session.user : null;
    if (user) {
      await loadProfile();
      subscribeRealtime();
      try {
        await fetchAll();
      } catch (e) {
        console.error("Load after sign-in failed:", e);
      }
    } else {
      profile = null;
      state = Object.assign({}, EMPTY);
    }
    authReady = true;
    emitAuth();
    emit();
  }

  async function init() {
    const cfg = window.EXPRESSION_CONFIG || {};
    if (cfg.SUPABASE_URL && cfg.SUPABASE_ANON_KEY && window.supabase) {
      mode = "remote";
      sb = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
        auth: { persistSession: true, autoRefreshToken: true, storageKey: "expression-auth" },
      });
      // Keep the app in sync with sign-in/out on this and other tabs. A silent
      // hourly token refresh keeps the same session, so it needs no reload.
      sb.auth.onAuthStateChange((event, session) => {
        if (event === "TOKEN_REFRESHED") return;
        handleAuth(session).catch((e) => console.error(e));
      });
      try {
        const { data } = await sb.auth.getSession();
        await handleAuth(data.session);
      } catch (e) {
        console.error("Auth check failed:", e);
        authReady = true;
      }
    } else {
      loadLocal();
      authReady = true;
    }
    emit();
    emitAuth();
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
    let asset_url = (it.asset_url || "").trim();
    if (asset_url && !/^https?:\/\//i.test(asset_url)) asset_url = "https://" + asset_url;
    return {
      id: it.id,
      account: it.account || "main",
      title: it.title,
      notes: it.notes || "",
      branch: it.branch,
      assignee: it.assignee || "",
      asset_url,
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
      if (r.assignee) notifyAssignee(r.assignee, "New project assigned to you", r.title);
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
    const assigneeChanged =
      next.assignee && next.assignee.toLowerCase() !== (current.assignee || "").toLowerCase();
    if (sb) {
      const { error } = await sb.from("projects").update(next).eq("id", id);
      if (error) return remoteFail(error);
      if (assigneeChanged) notifyAssignee(next.assignee, "Project assigned to you", next.title);
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

  // Toggle whether a team member is pushed a notification on new requests.
  async function setMemberNotify(id, on) {
    if (sb) {
      const { error } = await sb.from("members").update({ notify_requests: !!on }).eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    const m = state.members.find((x) => x.id === id);
    if (m) {
      m.notify_requests = !!on;
      saveLocal();
      emit();
    }
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
      if (assignee) notifyAssignee(assignee, "You're on posting duty this week", "Week of " + weekStartStr);
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

  // ----- item exceptions (override/skip a recurring item on one date) -----
  function isException(itemId, date) {
    return state.item_exceptions.some((x) => x.item_id === itemId && x.date === date);
  }

  async function addException(itemId, date) {
    if (isException(itemId, date)) return;
    if (sb) {
      const { error } = await sb
        .from("item_exceptions")
        .upsert({ id: uid(), item_id: itemId, date }, { onConflict: "item_id,date", ignoreDuplicates: true });
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.item_exceptions.push({ id: uid(), item_id: itemId, date });
    saveLocal();
    emit();
  }

  // ----- links (shared quick links) -----
  function linkRow(r) {
    let url = (r.url || "").trim();
    if (url && !/^https?:\/\//i.test(url)) url = "https://" + url;
    return {
      id: r.id,
      label: (r.label || "").trim(),
      url,
      sort: Number.isFinite(r.sort) ? r.sort : 0,
    };
  }

  async function addLink(fields) {
    const r = linkRow(Object.assign({ id: uid(), sort: state.links.length }, fields));
    if (sb) {
      const { error } = await sb.from("links").insert(r);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.links.push(r);
    saveLocal();
    emit();
  }

  async function updateLink(id, fields) {
    const current = state.links.find((r) => r.id === id);
    if (!current) return;
    const next = linkRow(Object.assign({}, current, fields, { id }));
    if (sb) {
      const { error } = await sb.from("links").update(next).eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    Object.assign(current, next);
    saveLocal();
    emit();
  }

  async function deleteLink(id) {
    if (sb) {
      const { error } = await sb.from("links").delete().eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.links = state.links.filter((r) => r.id !== id);
    saveLocal();
    emit();
  }

  // ----- requests (content/project requests to review) -----
  function requestRow(r) {
    return {
      id: r.id,
      account: r.account || "main",
      title: r.title,
      details: r.details || "",
      requested_by: r.requested_by || "",
      due_date: r.due_date || null, // "required by"
      status: r.status || "pending", // pending | approved | declined
    };
  }

  // Ask the Edge Function to push everyone flagged to receive new requests.
  // Recipients are resolved server-side, so even a requester (who can't read
  // the team list) can trigger the alert. Fire-and-forget.
  function notifyNewRequest(r) {
    if (!sb) return;
    sb.functions
      .invoke("NOTIFY", {
        body: {
          mode: "request",
          title: r.title,
          account: r.account || "main",
          requested_by: r.requested_by || "",
        },
      })
      .catch((e) => console.error("request notify failed:", e));
  }

  async function addRequest(fields) {
    const r = requestRow(Object.assign({ id: uid() }, fields));
    if (sb) {
      const { error } = await sb.from("requests").insert(r);
      if (error) return remoteFail(error);
      notifyNewRequest(r);
      return afterRemoteWrite();
    }
    state.requests.push(r);
    saveLocal();
    emit();
  }

  async function updateRequest(id, fields) {
    const current = state.requests.find((r) => r.id === id);
    if (!current) return;
    const next = requestRow(Object.assign({}, current, fields, { id }));
    if (sb) {
      const { error } = await sb.from("requests").update(next).eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    Object.assign(current, next);
    saveLocal();
    emit();
  }

  async function deleteRequest(id) {
    if (sb) {
      const { error } = await sb.from("requests").delete().eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.requests = state.requests.filter((r) => r.id !== id);
    saveLocal();
    emit();
  }

  // ----- focus (weekly theme + content ideas to shoot ahead) -----
  async function setFocusTitle(acct, weekStartStr, title) {
    title = (title || "").trim();
    if (sb) {
      const { error } = await sb
        .from("focus_weeks")
        .upsert({ account: acct, week_start: weekStartStr, title }, { onConflict: "account,week_start" });
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    const row = state.focus_weeks.find(
      (w) => (w.account || "main") === acct && w.week_start === weekStartStr
    );
    if (row) row.title = title;
    else state.focus_weeks.push({ id: uid(), account: acct, week_start: weekStartStr, title });
    saveLocal();
    emit();
  }

  function focusIdeaRow(r) {
    let concept_url = (r.concept_url || "").trim();
    if (concept_url && !/^https?:\/\//i.test(concept_url)) concept_url = "https://" + concept_url;
    return {
      id: r.id,
      account: r.account || "main",
      week_start: r.week_start,
      type: ["reel", "post", "carousel"].includes(r.type) ? r.type : "reel",
      description: (r.description || "").trim(),
      concept_url,
      shot: !!r.shot,
    };
  }

  async function addFocusIdea(fields) {
    const r = focusIdeaRow(Object.assign({ id: uid() }, fields));
    if (sb) {
      const { error } = await sb.from("focus_ideas").insert(r);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.focus_ideas.push(r);
    saveLocal();
    emit();
  }

  async function updateFocusIdea(id, fields) {
    const current = state.focus_ideas.find((r) => r.id === id);
    if (!current) return;
    const next = focusIdeaRow(Object.assign({}, current, fields, { id }));
    if (sb) {
      const { error } = await sb.from("focus_ideas").update(next).eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    Object.assign(current, next);
    saveLocal();
    emit();
  }

  async function deleteFocusIdea(id) {
    if (sb) {
      const { error } = await sb.from("focus_ideas").delete().eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.focus_ideas = state.focus_ideas.filter((r) => r.id !== id);
    saveLocal();
    emit();
  }

  // ----- web push (closed-app notifications) -----
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  // Subscribe THIS device to push and store it against the person's name, so a
  // later assignment to that name reaches every device they've enabled.
  async function enablePush(name) {
    const cfg = window.EXPRESSION_CONFIG || {};
    if (!sb) return { ok: false, reason: "Team sync must be on." };
    if (!cfg.VAPID_PUBLIC_KEY) return { ok: false, reason: "Push isn't configured yet." };
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      return { ok: false, reason: "This browser doesn't support push notifications." };
    }
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(cfg.VAPID_PUBLIC_KEY),
      });
      const j = sub.toJSON();
      const row = {
        name: (name || "").trim().toLowerCase(),
        endpoint: j.endpoint,
        p256dh: j.keys.p256dh,
        auth: j.keys.auth,
      };
      const { error } = await sb.from("push_subscriptions").upsert(row, { onConflict: "endpoint" });
      if (error) return { ok: false, reason: error.message };
      return { ok: true };
    } catch (e) {
      return { ok: false, reason: (e && e.message) || String(e) };
    }
  }

  // Ask the Supabase Edge Function to push to everyone registered under `name`.
  // Fire-and-forget: if push isn't set up yet, this fails quietly.
  function notifyAssignee(name, title, body) {
    if (!sb || !name) return;
    sb.functions
      .invoke("NOTIFY", {
        body: { name: String(name).trim().toLowerCase(), title, body: body || "", url: "./" },
      })
      .catch((e) => console.error("push notify failed:", e));
  }

  // ----- auth actions -----
  async function signUp(email, password, name) {
    if (!sb) return { error: { message: "Sign-in needs team sync (Supabase) configured." } };
    return sb.auth.signUp({
      email: (email || "").trim(),
      password,
      options: { data: { name: (name || "").trim() } },
    });
  }

  async function signIn(email, password) {
    if (!sb) return { error: { message: "Sign-in needs team sync (Supabase) configured." } };
    return sb.auth.signInWithPassword({ email: (email || "").trim(), password });
  }

  async function signOut() {
    if (sb) await sb.auth.signOut();
  }

  // Admin-only in practice (RLS blocks others): list everyone and set roles.
  async function listProfiles() {
    if (!sb) return [];
    const { data, error } = await sb.from("profiles").select("*").order("email");
    if (error) {
      console.error("Could not list people:", error);
      return [];
    }
    return data || [];
  }

  async function setRole(id, role) {
    if (!sb) return { error: { message: "Unavailable." } };
    const { error } = await sb.from("profiles").update({ role }).eq("id", id);
    return { error };
  }

  return {
    init,
    onChange,
    onAuth,
    signUp,
    signIn,
    signOut,
    listProfiles,
    setRole,
    getUser: () => user,
    getProfile: () => profile,
    getRole: () => (profile ? profile.role : null),
    refresh: async () => {
      if (!sb || !user) return;
      try {
        await refreshProfile();
        await fetchAll();
        emit();
      } catch (e) {
        console.error("Refresh failed:", e);
      }
    },
    isAuthReady: () => authReady,
    isAuthMode: () => mode === "remote",
    isStaff,
    get: () => state,
    getMode: () => mode,
    needsUpgrade: () => upgradeNeeded,
    isDone,
    addItem,
    updateItem,
    deleteItem,
    setDone,
    addProject,
    updateProject,
    deleteProject,
    addMember,
    setMemberNotify,
    setWeekAssignment,
    isException,
    addException,
    addLink,
    updateLink,
    deleteLink,
    addRequest,
    updateRequest,
    deleteRequest,
    setFocusTitle,
    addFocusIdea,
    updateFocusIdea,
    deleteFocusIdea,
    enablePush,
  };
})();
