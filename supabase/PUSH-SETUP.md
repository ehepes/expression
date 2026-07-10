# Push notifications — one-time setup

All the app code is already in place. To turn on **closed-app** push (a buzz on
your phone even when the app isn't open), do these three things once in your
Supabase project. ~10 minutes.

The public key is already in `config.js`. You only need the **private key** —
Claude gave it to you in chat. Keep it secret; don't commit it or share it.

---

## Part 1 — Create the table (2 min)

1. Supabase → **SQL Editor** → **New query**.
2. Paste the contents of **`supabase/push.sql`** and click **Run**.
   You should see "Success. No rows returned".

## Part 2 — Deploy the sender function (5 min)

1. Supabase → **Edge Functions** (left sidebar) → **Deploy a new function**
   (or "Create function").
2. Name it exactly **`notify`**.
3. Delete the sample code and paste the entire contents of
   **`supabase/functions/notify/index.ts`**.
4. **Turn OFF "Verify JWT"** for this function (the app has no login, so it
   calls the function with the public anon key). It's a toggle on the deploy
   screen, or under the function's **Settings** after deploying.
5. Click **Deploy**.

## Part 3 — Add the secrets (3 min)

1. Supabase → **Edge Functions** → **Secrets** (also under
   **Project Settings → Edge Functions**).
2. Add these three:

   | Name | Value |
   |---|---|
   | `VAPID_PUBLIC_KEY` | `BG66k15619dm35UKc9r6vPAbft76i8Iv8RL1t6TvnuTv5kQgGmgkKBlBV4MrxcKREsQ8Xw8JFGFB4Ht3OsHn34A` |
   | `VAPID_PRIVATE_KEY` | *(the private key Claude gave you in chat)* |
   | `VAPID_SUBJECT` | `mailto:ehepes@yahoo.com` |

3. Save. (`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are already provided to
   the function automatically — you don't add those.)

---

## Then, on each phone (once)

1. Open the app and **add it to the home screen** (required for push on iOS
   16.4+; Android works either way).
2. Open it from the home screen, go to **Settings ⚙**, type your **name**, and
   tap **Allow notifications on this device**.

That's it. Now, when someone is assigned a project or a posting week, everyone
registered under that name gets a push — even with the app closed.

### Notes
- **iOS** only delivers push to an **installed** PWA on **iOS 16.4+**. In a
  plain Safari tab it won't work.
- Each device enables itself once. The same person can enable several devices.
- If push isn't set up yet, nothing breaks — the app just falls back to the
  in-app notifications it already had.
