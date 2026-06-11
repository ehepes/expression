-- Morning reminder schedule — run this AFTER the "push" Edge Function is
-- deployed (see supabase/PUSH.md). It calls the function once every morning;
-- the function works out who is on posting duty that week and pushes them a
-- reminder, even if their app is closed.
--
-- Before running: replace <SERVICE_ROLE_KEY> below with your project's
-- service_role key (Project Settings -> API keys -> service_role — it's the
-- secret one, NOT the publishable key). Keep this key private.

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- 07:00 UTC daily. UK summer time = 08:00, UK winter = 07:00. Change the
-- "0 7 * * *" (minute hour * * *) if you want a different time.
select cron.schedule(
  'expression-morning-reminders',
  '0 7 * * *',
  $$
  select net.http_post(
    url := 'https://lboueyjikfjtycymigtw.supabase.co/functions/v1/push',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer <SERVICE_ROLE_KEY>'
    ),
    body := jsonb_build_object('type', 'morning')
  );
  $$
);

-- To change the time later, just run this file again (it replaces the job).
-- To stop morning reminders entirely:
--   select cron.unschedule('expression-morning-reminders');
