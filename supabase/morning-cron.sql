-- EXPRESSION — daily "you're on posting duty today" morning reminder.
-- Part of push setup (see PUSH-SETUP.md). Run in the SQL Editor AFTER the
-- notify function is deployed and its secrets (incl. CRON_SECRET) are set.
--
-- Before running: replace REPLACE_WITH_CRON_SECRET below with the CRON_SECRET
-- value Claude gave you in chat (the same value you set on the function).

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Remove any previous copy of this job so re-running is safe.
select cron.unschedule(jobid) from cron.job where jobname = 'expression-morning-reminder';

-- Fire every day at 07:00 UTC. Change '0 7 * * *' to another time if you like
-- (it's in UTC — e.g. '0 6 * * *' is 07:00 UK during summer / 06:00 in winter).
select cron.schedule(
  'expression-morning-reminder',
  '0 7 * * *',
  $$
  select net.http_post(
    url := 'https://lboueyjikfjtycymigtw.supabase.co/functions/v1/NOTIFY',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      -- anon key (public) so the scheduled call clears the function's JWT gateway
      'Authorization', 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxib3VleWppa2ZqdHljeW1pZ3R3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEyMDAxMjQsImV4cCI6MjA5Njc3NjEyNH0.da5mcPwQH-4uPBjWth7DZdvGJhavhDHpTVRhoy42f38',
      'x-cron-secret', 'REPLACE_WITH_CRON_SECRET'
    ),
    body := jsonb_build_object('mode', 'morning')
  );
  $$
);

-- To check it's scheduled:   select jobname, schedule from cron.job;
-- To stop it later:          select cron.unschedule('expression-morning-reminder');
