-- EXPRESSION — upgrade an existing Supabase project to the latest app.
-- Safe to run anytime, as many times as you like (everything is "if not
-- exists" / guarded). Run once in the SQL Editor: New query -> paste -> Run.
--
-- Adds: team member names, weekly posting duty, single-week edits,
-- shared quick links, and the requests inbox.

-- Team member names (assignment dropdowns).
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

-- A recurring item overridden/skipped on one date (single-week edits).
create table if not exists item_exceptions (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references items(id) on delete cascade,
  date date not null,
  created_at timestamptz not null default now(),
  unique (item_id, date)
);

-- Shared quick links (Google Drive, Canva, folders…).
create table if not exists links (
  id uuid primary key default gen_random_uuid(),
  label text not null,
  url text not null,
  sort int not null default 0,
  created_at timestamptz not null default now()
);

-- Content/project requests from other teams.
create table if not exists requests (
  id uuid primary key default gen_random_uuid(),
  account text not null default 'main',
  title text not null,
  details text not null default '',
  requested_by text not null default '',
  due_date date,
  status text not null default 'pending',
  created_at timestamptz not null default now()
);
-- If the requests table already existed without it, add the date column.
alter table requests add column if not exists due_date date;
-- Asset/Drive link per calendar item.
alter table items add column if not exists asset_url text not null default '';

alter table members enable row level security;
alter table week_assignments enable row level security;
alter table item_exceptions enable row level security;
alter table links enable row level security;
alter table requests enable row level security;

drop policy if exists "team access" on members;
drop policy if exists "team access" on week_assignments;
drop policy if exists "team access" on item_exceptions;
drop policy if exists "team access" on links;
drop policy if exists "team access" on requests;
create policy "team access" on members for all using (true) with check (true);
create policy "team access" on week_assignments for all using (true) with check (true);
create policy "team access" on item_exceptions for all using (true) with check (true);
create policy "team access" on links for all using (true) with check (true);
create policy "team access" on requests for all using (true) with check (true);

-- Realtime (each guarded so re-running doesn't error).
do $$ begin alter publication supabase_realtime add table members; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table week_assignments; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table item_exceptions; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table links; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table requests; exception when duplicate_object then null; end $$;
