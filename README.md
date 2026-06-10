# EXPRESSION — Media Team Hub

A free, installable web app for the Expression stream at Expectation Church.
It covers the three branches of the team:

| Branch | What it does in the app |
|---|---|
| **Social Media Team** | Weekly Instagram posting calendar with daily check-offs |
| **Photo & Media Team** | Photography / filming tasks on the same calendar |
| **Editing Team** | YouTube & Spotify tasks (uploads, podcast cuts) |

**Features**

- **Week view** — see everything that needs to happen each day of the week,
  tick items off as they're done, and jump between weeks. Posts can repeat
  weekly (like a posting schedule) or be one-off.
- **Reels pipeline** — capture reel ideas, assign them to people, and track
  progress through Idea → Approved → Filming → Editing → Ready → Posted.
- **Teams view** — each branch's weekly progress and task list at a glance.
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
- **Reels** tab: **+ New reel** to capture an idea. Assign someone, set a
  target date, and use **Move to …** to advance it through the pipeline.
- **Teams** tab: each branch's weekly progress, plus quick add per team.

The app ships with a **placeholder weekly calendar** — replace those items
with the real Instagram schedule (edit or delete them right in the app, or
update the inserts at the bottom of `supabase/schema.sql` before running it).

## Project layout

```
index.html            app shell
styles.css            styling (Expectation Church brand)
app.js                UI logic
store.js              data layer (Supabase or localStorage)
config.js             Supabase keys go here (optional)
sw.js                 offline support (service worker)
manifest.webmanifest  install-as-app metadata
supabase/schema.sql   one-time database setup + starter data
assets/logo.jpg       original Expectation Church logo
tools/make-icons.mjs  regenerates icons/header mark from the logo
```

No build step and no dependencies to install — it's plain HTML/CSS/JS, so
GitHub Pages serves it as-is.
