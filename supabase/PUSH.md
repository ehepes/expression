# Real push notifications — setup (free, ~15 minutes, one time)

This makes notifications arrive **even when the app is fully closed** —
when someone is assigned a project or a week of posting, and every morning
for whoever is on posting duty that week.

It runs on your existing Supabase project (free tier), so there's nothing
new to pay for. You do this once; teammates then just tap "Allow
notifications" in the app.

> **iPhone note:** Apple only allows web push for apps **added to the Home
> Screen** (iOS 16.4 or newer). Open the link in Safari → Share → *Add to
> Home Screen*, open it from the new icon, then allow notifications.
> Android/Chrome and laptops work either way.

The app already ships with the **public** push key (in `config.js`). You
only need the **private** key below, which stays secret inside Supabase.

---

## Step 1 — Create the database table

Supabase → **SQL Editor** → **New query** → paste all of
[`push-setup.sql`](push-setup.sql) → **Run**.

## Step 2 — Create the Edge Function

1. Supabase → **Edge Functions** (left sidebar) → **Create a function**.
2. Name it exactly **`push`**.
3. Delete the sample code and paste the entire contents of
   [`functions/push/index.ts`](functions/push/index.ts).
4. **Important:** turn **Verify JWT** *off* for this function (there's a
   toggle in the function settings / a checkbox when deploying). The app
   uses a publishable key, which isn't a JWT.
5. **Deploy**.

## Step 3 — Add the secret keys

Supabase → **Edge Functions** → **Secrets** (or **Project Settings →
Edge Functions → Secrets**) → add these three:

| Name | Value |
|---|---|
| `VAPID_PUBLIC_KEY` | `BJOIlFaAfkCtLlvGRetC3QVW9oj4-beXZjrc0A3sos_xDftMdLgBJILIPt6rVgfktWo-FyGbDr9MGGh6HN_DdLQ` |
| `VAPID_PRIVATE_KEY` | *(paste the private key — sent to you separately, keep it secret)* |
| `VAPID_SUBJECT` | `mailto:you@yourchurch.com` (any contact email) |

(You don't need to add `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` —
Supabase provides those to the function automatically.)

## Step 4 — Schedule the morning reminder

1. Open [`push-cron.sql`](push-cron.sql).
2. Replace `<SERVICE_ROLE_KEY>` with your **service_role** key
   (Project Settings → API keys → *service_role* — the secret one, **not**
   the publishable key).
3. Paste the edited SQL into **SQL Editor** → **Run**.

That schedules a 07:00 UTC daily reminder. Change the `0 7 * * *` if you
want a different time, and re-run to update it.

## Step 5 — Each teammate turns it on

In the app: **⚙ Settings** → type your name → **Allow notifications**.
That registers your device. From then on you'll get a push when you're
assigned something or when it's your posting week — even with the app shut.

---

## Quick test

- On a phone with notifications allowed, set your name to e.g. *Test*.
- On another device, assign a project to *Test*.
- The first device should get a notification within a few seconds, even if
  its screen is off.

To test the morning reminder without waiting for 7am, run this in the SQL
Editor (replace the key as in step 4):

```sql
select net.http_post(
  url := 'https://lboueyjikfjtycymigtw.supabase.co/functions/v1/push',
  headers := jsonb_build_object('Content-Type','application/json',
                                'Authorization','Bearer <SERVICE_ROLE_KEY>'),
  body := jsonb_build_object('type','morning')
);
```

## If something doesn't fire

- **No notification at all:** check the person tapped *Allow notifications*
  in Settings on that device, and (iPhone) is opening from the Home Screen
  icon, not a Safari tab.
- **Edge Function logs:** Supabase → Edge Functions → `push` → **Logs**
  shows each call and any error.
- The in-app reminders (while the app is open) keep working regardless, so
  the app is still useful even before push is set up.
