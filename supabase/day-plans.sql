-- Day plans: per-day editor + concept/post links on the Week calendar.
-- Run once in the Supabase SQL Editor (New query -> paste -> Run).
-- Safe to re-run. Staff-only, to match the locked-down setup.

create table if not exists day_plans (
  id uuid primary key default gen_random_uuid(),
  account text not null default 'main',
  date date not null,
  editor text not null default '',      -- who is editing that day's post
  concept_url text not null default '', -- link to the idea
  post_url text not null default '',    -- link to the edited post, once ready
  created_at timestamptz not null default now(),
  unique (account, date)
);

alter table day_plans enable row level security;

-- Staff (editor/admin) only. If you have NOT locked the app down yet (no
-- is_staff() function), use the open policy on the next line instead.
drop policy if exists "staff all" on day_plans;
drop policy if exists "team access" on day_plans;
create policy "staff all" on day_plans for all
  using (public.is_staff()) with check (public.is_staff());
-- create policy "team access" on day_plans for all using (true) with check (true);

do $$ begin
  alter publication supabase_realtime add table day_plans;
exception when duplicate_object then null; end $$;
