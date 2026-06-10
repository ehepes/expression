/*
 * Data layer. Two modes:
 *  - "remote": Supabase configured in config.js -> shared team data with
 *    realtime updates.
 *  - "local": no config (or Supabase unreachable) -> data lives in
 *    localStorage on this device only.
 *
 * Data model:
 *  items:        scheduled posts/tasks. Either recurring weekly (dow 0=Mon..6=Sun)
 *                or one-off (date "YYYY-MM-DD").
 *  completions:  one row per (item_id, date) that has been marked done.
 *  reels:        reel ideas with an assignee and a pipeline status.
 */
window.Store = (() => {
  const LS_KEY = "expression-data-v1";

  let mode = "local"; // "local" | "remote" | "local-error"
  let sb = null;
  let state = { items: [], completions: [], reels: [] };
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
        state = JSON.parse(raw);
        return;
      }
    } catch (e) {
      console.error("Could not read saved data:", e);
    }
    state = seedData();
    saveLocal();
  }

  // Placeholder weekly calendar until the real Instagram sheet is loaded in.
  // Everything here can be edited or deleted inside the app.
  function seedData() {
    const item = (title, branch, dow, extra) =>
      Object.assign(
        { id: uid(), title, notes: "", branch, assignee: "", recurring: true, dow, date: null },
        extra || {}
      );
    const reel = (title, notes, status, assignee) => ({
      id: uid(), title, notes, assignee: assignee || "", status, due_date: null,
    });
    return {
      items: [
        item("Motivation Monday — encouragement quote post", "social", 0),
        item("Upload Sunday sermon to YouTube", "editing", 0),
        item("Testimony Tuesday — share a testimony", "social", 1),
        item("Cut sermon highlights for Spotify podcast", "editing", 1),
        item("Midweek check-in — Bible study reminder story", "social", 2),
        item("Throwback Thursday — photos from last service", "media", 3),
        item("Reel drop — weekly reel goes live", "social", 4),
        item("Sunday invite story + countdown", "social", 5),
        item("Service day — live stories + photo coverage", "media", 6),
        item("Post-service recap post", "social", 6),
      ],
      completions: [],
      reels: [
        reel("Welcome to Expression — intro reel", "Quick cuts of the team + what each branch does.", "idea"),
        reel("Sunday in 30 seconds — recap reel", "Best moments from last service, fast cuts to music.", "filming"),
        reel("Worship night highlights", "Footage is in the shared drive, needs colour + captions.", "editing"),
      ],
    };
  }

  // ----- remote (Supabase) -----
  async function fetchAll() {
    const [items, completions, reels] = await Promise.all([
      sb.from("items").select("*").order("created_at"),
      sb.from("completions").select("*"),
      sb.from("reels").select("*").order("created_at"),
    ]);
    const err = items.error || completions.error || reels.error;
    if (err) throw err;
    state = { items: items.data, completions: completions.data, reels: reels.data };
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
    return {
      id: it.id,
      title: it.title,
      notes: it.notes || "",
      branch: it.branch,
      assignee: it.assignee || "",
      recurring: !!it.recurring,
      dow: it.recurring ? it.dow : null,
      date: it.recurring ? null : it.date,
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

  // ----- reels -----
  function reelRow(r) {
    return {
      id: r.id,
      title: r.title,
      notes: r.notes || "",
      assignee: r.assignee || "",
      status: r.status || "idea",
      due_date: r.due_date || null,
    };
  }

  async function addReel(fields) {
    const r = reelRow(Object.assign({ id: uid() }, fields));
    if (sb) {
      const { error } = await sb.from("reels").insert(r);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.reels.push(r);
    saveLocal();
    emit();
  }

  async function updateReel(id, fields) {
    const current = state.reels.find((r) => r.id === id);
    if (!current) return;
    const next = reelRow(Object.assign({}, current, fields, { id }));
    if (sb) {
      const { error } = await sb.from("reels").update(next).eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    Object.assign(current, next);
    saveLocal();
    emit();
  }

  async function deleteReel(id) {
    if (sb) {
      const { error } = await sb.from("reels").delete().eq("id", id);
      if (error) return remoteFail(error);
      return afterRemoteWrite();
    }
    state.reels = state.reels.filter((r) => r.id !== id);
    saveLocal();
    emit();
  }

  return {
    init,
    onChange,
    get: () => state,
    getMode: () => mode,
    isDone,
    addItem,
    updateItem,
    deleteItem,
    setDone,
    addReel,
    updateReel,
    deleteReel,
  };
})();
