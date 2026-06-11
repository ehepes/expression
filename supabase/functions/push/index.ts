// Expression — Web Push sender (Supabase Edge Function).
//
// Two jobs, chosen by the JSON body it receives:
//   { "type": "assign", "name": "...", "title": "...", "body": "..." }
//     -> push to every device registered under that person's name.
//   { "type": "morning" }   (called by the daily cron)
//     -> work out who is on posting duty this week, count what's still due
//        today for their account(s), and push them a reminder.
//
// Deploy + secrets: see supabase/PUSH.md.

import webpush from "npm:web-push@3.6.7";
import { createClient } from "npm:@supabase/supabase-js@2";

const VAPID_PUBLIC = Deno.env.get("VAPID_PUBLIC_KEY") ?? "";
const VAPID_PRIVATE = Deno.env.get("VAPID_PRIVATE_KEY") ?? "";
const VAPID_SUBJECT = Deno.env.get("VAPID_SUBJECT") ?? "mailto:team@expectation.church";

// These three are injected into every Edge Function automatically.
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

webpush.setVapidDetails(VAPID_SUBJECT, VAPID_PUBLIC, VAPID_PRIVATE);
const db = createClient(SUPABASE_URL, SERVICE_ROLE);

const ACCOUNTS: Record<string, string> = {
  main: "Main Church",
  ya: "YA",
  yth: "YTH",
  her: "HER",
};

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

function ymd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

// Mirror of the app's recurrence rule, in UTC.
function showsOn(it: any, date: Date, dateStr: string): boolean {
  if (!it.recurring) return it.date === dateStr;
  if (it.start_date && dateStr < it.start_date) return false;
  if (it.end_date && dateStr > it.end_date) return false;
  const dow = (date.getUTCDay() + 6) % 7;
  if (it.dow !== dow) return false;
  if ((it.recur || "weekly") === "monthly") {
    return Math.floor((date.getUTCDate() - 1) / 7) + 1 === (it.nth || 1);
  }
  return true;
}

// Send one notification to every device a person has, pruning dead ones.
async function pushToName(name: string, payload: Record<string, unknown>) {
  const { data: subs } = await db
    .from("push_subscriptions")
    .select("*")
    .ilike("name", name);
  if (!subs || !subs.length) return 0;
  let sent = 0;
  for (const row of subs) {
    try {
      await webpush.sendNotification(row.subscription, JSON.stringify(payload));
      sent++;
    } catch (err: any) {
      const code = err?.statusCode;
      if (code === 404 || code === 410) {
        await db.from("push_subscriptions").delete().eq("endpoint", row.endpoint);
      } else {
        console.error("push error for", name, code, err?.body || err?.message);
      }
    }
  }
  return sent;
}

async function handleMorning(): Promise<number> {
  const now = new Date();
  const todayStr = ymd(now);
  const day = (now.getUTCDay() + 6) % 7;
  const monday = new Date(now);
  monday.setUTCDate(now.getUTCDate() - day);
  const ws = ymd(monday);

  const [{ data: weeks }, { data: items }, { data: comps }] = await Promise.all([
    db.from("week_assignments").select("*").eq("week_start", ws),
    db.from("items").select("*"),
    db.from("completions").select("*").eq("date", todayStr),
  ]);
  if (!weeks || !weeks.length) return 0;

  const doneToday = new Set((comps || []).map((c: any) => c.item_id));

  // Aggregate per person (someone could cover more than one account).
  const perName: Record<string, { count: number; accounts: Set<string> }> = {};
  for (const w of weeks) {
    const acct = w.account || "main";
    let due = 0;
    for (const it of items || []) {
      if ((it.account || "main") !== acct) continue;
      if (showsOn(it, now, todayStr) && !doneToday.has(it.id)) due++;
    }
    const key = (w.assignee || "").trim();
    if (!key) continue;
    if (!perName[key]) perName[key] = { count: 0, accounts: new Set() };
    perName[key].count += due;
    perName[key].accounts.add(ACCOUNTS[acct] || acct);
  }

  let sent = 0;
  for (const [name, info] of Object.entries(perName)) {
    const where = [...info.accounts].join(", ");
    const body = info.count
      ? `${info.count} item${info.count === 1 ? "" : "s"} to post today (${where})`
      : `Nothing left to post today (${where}).`;
    sent += await pushToName(name, { title: "You're on posting today", body, url: "./" });
  }
  return sent;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const payload = await req.json().catch(() => ({}));
    let sent = 0;
    if (payload.type === "morning") {
      sent = await handleMorning();
    } else if (payload.type === "assign" && payload.name) {
      sent = await pushToName(String(payload.name), {
        title: payload.title || "New assignment",
        body: payload.body || "",
        url: payload.url || "./",
      });
    } else {
      return new Response(JSON.stringify({ error: "unknown request" }), {
        status: 400,
        headers: { ...cors, "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ ok: true, sent }), {
      headers: { ...cors, "Content-Type": "application/json" },
    });
  } catch (e) {
    console.error(e);
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }
});
