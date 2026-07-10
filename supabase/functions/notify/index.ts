// EXPRESSION — push sender (Supabase Edge Function).
//
// Called by the app when someone is assigned a project or a posting week. It
// looks up every device registered under that person's name and sends a Web
// Push to each. Deploy this in the Supabase dashboard (Edge Functions -> new
// function "notify"), turn OFF "Verify JWT", and set the three VAPID secrets.
// See supabase/PUSH-SETUP.md.

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

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const { name, title, body, url } = await req.json();
    if (!name || !title) {
      return new Response(JSON.stringify({ error: "name and title are required" }), {
        status: 400,
        headers: { ...cors, "Content-Type": "application/json" },
      });
    }

    const { data: subs, error } = await supabase
      .from("push_subscriptions")
      .select("*")
      .eq("name", String(name).trim().toLowerCase());
    if (error) throw error;

    const payload = JSON.stringify({ title, body: body ?? "", url: url ?? "./" });
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
          // 404/410 mean the subscription is dead — drop it so we stop trying.
          const code = (e as { statusCode?: number }).statusCode;
          if (code === 404 || code === 410) {
            await supabase.from("push_subscriptions").delete().eq("endpoint", s.endpoint);
          } else {
            console.error("push send error:", e);
          }
        }
      }),
    );

    return new Response(JSON.stringify({ sent }), {
      headers: { ...cors, "Content-Type": "application/json" },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }
});
