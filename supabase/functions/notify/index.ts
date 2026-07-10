// EXPRESSION — push sender (Supabase Edge Function).
//
// Two jobs, one function:
//   • default   — the app calls this when someone is assigned a project or a
//                 posting week: { name, title, body } → push that one person.
//   • morning   — a daily scheduler (pg_cron) calls this: { mode: "morning" }
//                 with header x-cron-secret → push everyone on posting duty
//                 this week a "post today" reminder.
//
// Deploy in the Supabase dashboard (Edge Functions → new function "notify"),
// turn OFF "Verify JWT", and set the VAPID + CRON secrets. See PUSH-SETUP.md.

import webpush from "npm:web-push@3.6.7";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

webpush.setVapidDetails(
  Deno.env.get("VAPID_SUBJECT") ?? "mailto:hello@example.com",
  Deno.env.get("VAPID_PUBLIC_KEY")!,
  Deno.env.get("VAPID_PRIVATE_KEY")!,
);

const ACCOUNTS: Record<string, string> = {
  main: "Main Church",
  ya: "YA",
  yth: "YTH",
  her: "HER",
};

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-cron-secret",
};

const json = (obj: unknown, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { ...cors, "Content-Type": "application/json" } });

// Push a payload to every device registered under a (lowercased) name.
async function sendToName(name: string, payloadObj: Record<string, unknown>): Promise<number> {
  const { data: subs, error } = await supabase
    .from("push_subscriptions")
    .select("*")
    .eq("name", name);
  if (error) throw error;
  const payload = JSON.stringify(payloadObj);
  let sent = 0;
  await Promise.all(
    (subs ?? []).map(async (s) => {
      try {
        await webpush.sendNotification(
          { endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth } },
          payload,
        );
        sent++;
      } catch (e) {
        const code = (e as { statusCode?: number }).statusCode;
        if (code === 404 || code === 410) {
          await supabase.from("push_subscriptions").delete().eq("endpoint", s.endpoint);
        } else {
          console.error("push send error:", e);
        }
      }
    }),
  );
  return sent;
}

// Monday (UTC) of the current week, as yyyy-mm-dd.
function currentMonday(): string {
  const now = new Date();
  const day = (now.getUTCDay() + 6) % 7; // 0 = Monday
  const monday = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - day));
  return monday.toISOString().slice(0, 10);
}

// Remind everyone on posting duty this week to post today.
async function sendMorningReminders(): Promise<number> {
  const wkStr = currentMonday();
  const { data: assigns, error } = await supabase
    .from("week_assignments")
    .select("*")
    .eq("week_start", wkStr);
  if (error) throw error;

  const byName = new Map<string, string[]>();
  for (const a of assigns ?? []) {
    const name = String(a.assignee ?? "").trim().toLowerCase();
    if (!name) continue;
    const label = ACCOUNTS[a.account ?? "main"] ?? a.account ?? "Main Church";
    const arr = byName.get(name) ?? [];
    if (!arr.includes(label)) arr.push(label);
    byName.set(name, arr);
  }

  let sent = 0;
  for (const [name, accounts] of byName) {
    sent += await sendToName(name, {
      title: "You're on posting duty today",
      body: `Open Expression to post today for ${accounts.join(", ")}.`,
      url: "./",
    });
  }
  return sent;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const payload = await req.json().catch(() => ({}));

    // Scheduled daily reminder — protected by the shared cron secret.
    if (payload.mode === "morning") {
      if (req.headers.get("x-cron-secret") !== Deno.env.get("CRON_SECRET")) {
        return json({ error: "unauthorized" }, 401);
      }
      const sent = await sendMorningReminders();
      return json({ ok: true, mode: "morning", sent });
    }

    // Default — notify a single assigned person.
    const { name, title, body, url } = payload;
    if (!name || !title) return json({ error: "name and title are required" }, 400);
    const sent = await sendToName(String(name).trim().toLowerCase(), {
      title,
      body: body ?? "",
      url: url ?? "./",
    });
    return json({ ok: true, sent });
  } catch (e) {
    return json({ error: String(e) }, 500);
  }
});
