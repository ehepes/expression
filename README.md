# EXPRESSION — Media Team Hub

A free, installable web app for the Expression stream at Expectation Church.
It covers the three branches of the team:

| Branch | What it does in the app |
|---|---|
| **Social Media Team** | Weekly Instagram posting calendar with daily check-offs |
| **Photo & Media Team** | Photography / filming tasks on the same calendar |
| **Editing Team** | YouTube & Spotify tasks (uploads, podcast cuts) |

**Features**

- **Week view** — pick a team from the chips; each shows the format that fits:
  - **Social** — a daily Mon–Sun calendar. Tick posts off, flip between weeks,
    or tap the date range to jump to any week. Posts can be one-off, weekly, or
    monthly (e.g. "3rd Wednesday"); when editing a recurring post you choose the
    scope (**just this week**, **future weeks**, or **every week**).
  - **Media** & **Editing** — a weekly standing checklist (not daily). Set the
    list once; it appears every week and is ticked off once per week. Editing
    starts with Edit/Post Spotify and Edit/Post YouTube; Media starts blank for
    your Sunday shoot list. Add or remove tasks any time.
  - **Graphics** — no schedule; their work is tracked in the Projects tab.
- **Projects pipeline** — capture ideas, assign them to people, set a
  "required by" date, and track progress through Idea → Approved → Filming
  → Editing → Ready → Posted. Assignment notifications fire on devices
  where the person has set their name (Settings ⚙) while the app is open or
  backgrounded — needs team sync on.
- **Team names & week duty** — names set in Settings ⚙ are saved to the
  shared database, so assigning is a dropdown of real team members. One
  person can be assigned a whole week of posting from the Week tab
  ("Posting this week"). When someone is assigned, and each morning of an
  assigned week, a notification fires on their device — while the app is
  open or running in the background (set name + allow notifications in
  Settings ⚙, team sync on).
- **Requests inbox** — other teams tap **New request** to ask for content;
  pending requests show a count on the tab. Approve one to drop it straight
  into the Projects pipeline (then assign it), or decline it.
- **Quick links** — a 🔗 button by the header opens shared links (Google
  Drive, Canva, folders…) that the whole team can add and edit.
- **Today** — the home screen the app opens to: today's posts with quick
  check-off, who's on posting duty this week, projects due soon (or overdue),
  and a nudge when requests are awaiting approval.
- **Accounts** — separate content plans for Main Church, YA, YTH and HER,
  switchable from the dropdown under the header.
- Works on any phone or laptop from a link; installable like a real app
  (no app store, no fees); works offline.

Everything is free: free hosting (GitHub Pages), free database (Supabase
free tier), no domain purchase needed.

---

## 1. Put it online (free, ~2 minutes)

1. In this GitHub repository go to **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to *Deploy from a branch*,
   pick branch **main** and folder **/ (root)**, then save.
3. After a minute the app is live at
   `https://<your-username>.github.io/expression/`.
4. Share that link with the team.

## 2. Turn on team sync (free, ~5 minutes, recommended)

Out of the box the app runs in **local mode**: it works fully, but each
person's data stays on their own device. To give the whole team one shared
calendar with live updates:

1. Create a free account at [supabase.com](https://supabase.com)
   (no card required).
2. Create a **New project** (name it anything, e.g. `expression`).
3. Open **SQL Editor → New query**, paste the whole contents of
   [`supabase/schema.sql`](supabase/schema.sql), and click **Run**.
4. Go to **Settings → API** and copy two values into
   [`config.js`](config.js):
   - *Project URL* → `SUPABASE_URL`
   - *anon public* key → `SUPABASE_ANON_KEY`
5. Commit the change. When the page reloads you'll see **“Team sync”** in
   the header — now everyone shares the same data, live.

> The anon key is safe to put in the app, but the app link then acts like a
> shared team notebook — share it with the team only, don't post it publicly.

**Already had sync running before a newer feature was added?** Run
[`supabase/upgrade.sql`](supabase/upgrade.sql) once in the SQL Editor the
same way — it safely adds anything missing (team names, week duty,
single-week edits, links, requests). The app shows a banner until it's done.

> **Notifications** appear while the app is open or running in the
> background (each person sets their name and taps *Allow notifications* in
> Settings ⚙). They don't wake a fully-closed phone — that needs a small
> server add-on which isn't set up here.

## 3. Install it like an app on your phone

- **iPhone (Safari):** open the link → tap the **Share** button → **Add to
  Home Screen**.
- **Android (Chrome):** open the link → tap the **⋮** menu → **Add to Home
  screen** / **Install app**.

It gets its own icon, opens full-screen, and works offline.

## Using the app

- **Week** tab: tap **+** on any day to add a post or task. Choose *One
  date* for a single post or *Repeats weekly* for the standing schedule
  (e.g. "Reel drop every Friday"). Tap the checkbox to mark it done for that
  day; tap the row to edit or delete it.
- **Projects** tab: **+ New project** to capture an idea. Assign someone,
  set a "required by" date, and use **Move to …** to advance it.
- **Today** tab: the home screen — today's posts, this week's posting duty,
  projects due soon, and pending requests, all at a glance.

The app ships with the **Main Church standard weekly Instagram schedule**
(from the team's posting calendar) plus the Special Reels Tracker projects.
The YA, YTH and HER accounts start blank, ready to populate in-app.

## Project layout

```
index.html               app shell
styles.css               styling (Expectation Church brand)
app.js                   UI logic
store.js                 data layer (Supabase or localStorage)
config.js                Supabase keys
sw.js                    offline support (service worker)
manifest.webmanifest     install-as-app metadata
supabase/schema.sql      full database setup + starter data (fresh projects)
supabase/upgrade.sql     add newer features to an already-running project
assets/logo.jpg          original Expectation Church logo
tools/make-icons.mjs     regenerates icons/header mark from the logo
```

No build step and no dependencies to install — it's plain HTML/CSS/JS, so
GitHub Pages serves it as-is.
