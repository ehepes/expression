-- EXPRESSION — enable closed-app push notifications.
-- Run once in the Supabase SQL Editor (New query -> paste -> Run). Safe to
-- re-run. Part 1 of push setup; see supabase/PUSH-SETUP.md for parts 2 & 3.

-- One row per device that has opted in, tied to the person's name (lowercased),
-- so an assignment to that name can reach every device they've enabled.
create table if not exists push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now()
);
create index if not exists push_subscriptions_name_idx on push_subscriptions (name);

alter table push_subscriptions enable row level security;
drop policy if exists "team access" on push_subscriptions;
create policy "team access" on push_subscriptions for all using (true) with check (true);
