-- Real push notifications — database part.
-- Run this once in the Supabase SQL Editor (New query -> paste -> Run).
-- Then follow supabase/PUSH.md to deploy the Edge Function and schedule the
-- morning reminder.

-- One row per device that opted in, stored against the person's name.
create table if not exists push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  endpoint text not null unique,
  subscription jsonb not null,
  created_at timestamptz not null default now()
);

alter table push_subscriptions enable row level security;
create policy "team access" on push_subscriptions for all using (true) with check (true);
