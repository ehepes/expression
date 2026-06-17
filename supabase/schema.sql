-- EXPRESSION media team hub — database setup.
-- Run this once in your Supabase project: SQL Editor -> New query -> paste -> Run.

-- Scheduled posts / tasks, per account ('main' | 'ya' | 'yth' | 'her').
-- One-off (date) or recurring: weekly (dow 0=Monday..6=Sunday) or monthly
-- (nth weekday, e.g. nth=3 dow=2 -> 3rd Wednesday). start_date/end_date
-- bound a recurring item so changes can apply "from this week onward".
create table if not exists items (
  id uuid primary key default gen_random_uuid(),
  account text not null default 'main',
  title text not null,
  notes text not null default '',
  branch text not null default 'social', -- social | media | editing
  assignee text not null default '',
  asset_url text not null default '',
  recurring boolean not null default false,
  recur text check (recur in ('weekly', 'monthly')),
  dow int check (dow between 0 and 6),
  nth int check (nth between 1 and 4),
  date date,
  start_date date,
  end_date date,
  created_at timestamptz not null default now()
);

-- One row per (item, date) that has been marked complete.
create table if not exists completions (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references items(id) on delete cascade,
  date date not null,
  created_at timestamptz not null default now(),
  unique (item_id, date)
);

-- Projects pipeline (reels, videos, campaigns), per account.
create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  account text not null default 'main',
  title text not null,
  notes text not null default '',
  assignee text not null default '',
  status text not null default 'idea', -- idea | approved | filming | editing | ready | posted
  due_date date, -- "required by"
  created_at timestamptz not null default now()
);

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

-- A recurring item overridden/skipped on a single date, so an edit can apply
-- to just one week without changing the standing schedule.
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

-- Content/project requests from other teams, to review and turn into projects.
create table if not exists requests (
  id uuid primary key default gen_random_uuid(),
  account text not null default 'main',
  title text not null,
  details text not null default '',
  requested_by text not null default '',
  due_date date, -- "required by"
  status text not null default 'pending', -- pending | approved | declined
  created_at timestamptz not null default now()
);

-- The app is shared via a private link with a small trusted team, so the
-- anon key gets full read/write. Don't post the app link publicly.
alter table items enable row level security;
alter table completions enable row level security;
alter table projects enable row level security;
alter table members enable row level security;
alter table week_assignments enable row level security;
alter table item_exceptions enable row level security;
alter table links enable row level security;
alter table requests enable row level security;

create policy "team access" on items for all using (true) with check (true);
create policy "team access" on completions for all using (true) with check (true);
create policy "team access" on projects for all using (true) with check (true);
create policy "team access" on members for all using (true) with check (true);
create policy "team access" on week_assignments for all using (true) with check (true);
create policy "team access" on item_exceptions for all using (true) with check (true);
create policy "team access" on links for all using (true) with check (true);
create policy "team access" on requests for all using (true) with check (true);

-- Live updates: when one person changes something, everyone else sees it.
alter publication supabase_realtime add table items;
alter publication supabase_realtime add table completions;
alter publication supabase_realtime add table projects;
alter publication supabase_realtime add table members;
alter publication supabase_realtime add table week_assignments;
alter publication supabase_realtime add table item_exceptions;
alter publication supabase_realtime add table links;
alter publication supabase_realtime add table requests;

-- ---------------------------------------------------------------
-- Main Church standard weekly Instagram schedule (from the team's
-- posting calendar). All editable in the app afterwards.
-- ---------------------------------------------------------------
insert into items (account, title, notes, branch, recurring, recur, dow, nth) values
  -- Monday
  ('main', 'Story Recap', 'Worship moment + key quote + Scripture + CTA + poll · 08:00–10:00', 'social', true, 'weekly', 0, null),
  ('main', 'Invite to Prayer Story', 'Use video from drive · 08:00–10:00', 'social', true, 'weekly', 0, null),
  ('main', 'Sunday Reel', 'Include engagement sticker (poll/question) · 08:00–10:00', 'social', true, 'weekly', 0, null),
  ('main', 'Upload Sunday sermon to YouTube', '', 'editing', true, 'weekly', 0, null),
  -- Tuesday
  ('main', 'Prayer Story', 'Scripture + prayer prompt + question sticker · 08:00–10:00', 'social', true, 'weekly', 1, null),
  ('main', 'Podcast/YT Promo Story', '20-sec audiogram + subtitles + CTA: Listen on Spotify · 08:00–10:00', 'social', true, 'weekly', 1, null),
  ('main', 'Expect Group Story', 'Real face + 10-sec testimony + poll: Want info? · 08:00–10:00', 'social', true, 'weekly', 1, null),
  ('main', 'Cut sermon highlights for Spotify podcast', '', 'editing', true, 'weekly', 1, null),
  -- Wednesday
  ('main', 'Expect Socials Story', 'Real face + 10-sec testimony + poll: Want info? · 08:00–10:00', 'social', true, 'weekly', 2, null),
  ('main', 'Join a Team Story', 'Real face + 10-sec testimony + poll: Want info? · 08:00–10:00', 'social', true, 'weekly', 2, null),
  ('main', 'Expect Group Reel', '1st Wednesday of the month', 'social', true, 'monthly', 2, 1),
  ('main', 'Expect Socials Reel', '3rd Wednesday of the month', 'social', true, 'monthly', 2, 3),
  -- Thursday
  ('main', 'Established Post/Story', 'Graphic from drive · 08:00–10:00', 'social', true, 'weekly', 3, null),
  ('main', 'Anthems Story', 'Worship clip overlay + text: This has been on repeat · 08:00–10:00', 'social', true, 'weekly', 3, null),
  ('main', 'Worship rehearsal/worship story', '', 'social', true, 'weekly', 3, null),
  ('main', 'Testimony Thursday Reel', '3rd Thursday of the month — special projects', 'social', true, 'monthly', 3, 3),
  -- Friday
  ('main', 'Sunday Teaser Story', 'Pastor 15-sec invite + sermon reveal (if clip on drive) · 08:00–10:00', 'social', true, 'weekly', 4, null),
  ('main', 'Youth Repost Story', 'Add text overlay + tag someone sticker · evening', 'social', true, 'weekly', 4, null),
  ('main', 'Sermon Clip Reel', 'Clip sent from media team · 08:00–10:00', 'social', true, 'weekly', 4, null),
  -- Saturday
  ('main', 'Encouragement Carousel', 'Hook + Scripture + why Sunday matters + service time · 10:00', 'social', true, 'weekly', 5, null),
  ('main', 'Countdown Story', 'Who are you bringing? + location + parking · 10:00', 'social', true, 'weekly', 5, null),
  -- Sunday
  ('main', 'Service day — live stories + photo coverage', '', 'media', true, 'weekly', 6, null);

-- Projects from the Special Reels Tracker.
insert into projects (account, title, notes, assignee, status, due_date) values
  ('main', 'Summer social reel', 'One person sitting at table alone, 2 others come sit down — 1st person says ''don''t have a boring summer, come to summer social next week'' + details, get off Planning Centre.', 'Nesser', 'posted', null),
  ('main', 'SOCIALS reel — 3rd Wednesday', 'Love heart & phone: https://www.instagram.com/reel/C7Q5Rl9Czpx/', 'Nesser', 'filming', null),
  ('main', 'ALPHA Course', 'Testimony, shopping centre, one person in crowd speaking looking at camera.', 'Nesser', 'filming', '2026-06-15'),
  ('main', 'VISION Sunday', 'Face to camera, photos with text of the people. Voice-over video of church at end — the vision is the people.', 'Nesser', 'idea', '2026-06-22'),
  ('main', 'Wave at stool', 'To be edited — Daniel to send raw footage.', 'Andreea', 'editing', null),
  ('main', 'Pastoral care team', 'Reel to promote pastoral care and explain what it is.', 'Nesser', 'idea', null),
  ('main', 'Baptism', 'Promote baptism — EQUIP, explain what baptism is.', 'Nesser', 'idea', '2026-06-22');
