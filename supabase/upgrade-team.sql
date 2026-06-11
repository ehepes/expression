-- Upgrade: team member names + weekly posting assignments.
-- For projects that already ran schema.sql. Run once in the Supabase
-- SQL Editor (New query -> paste -> Run). Safe to run more than once
-- apart from the final two lines, which error harmlessly if repeated.

-- Everyone who has set their name in the app, so assignment dropdowns
-- can offer existing names instead of free typing.
create table if not exists members (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  created_at timestamptz not null default now()
);

-- Who is on posting duty for a given week (Monday date), per account.
create table if not exists week_assignments (
  id uuid primary key default gen_random_uuid(),
  account text not null default 'main',
  week_start date not null,
  assignee text not null,
  created_at timestamptz not null default now(),
  unique (account, week_start)
);

alter table members enable row level security;
alter table week_assignments enable row level security;

create policy "team access" on members for all using (true) with check (true);
create policy "team access" on week_assignments for all using (true) with check (true);

alter publication supabase_realtime add table members;
alter publication supabase_realtime add table week_assignments;
