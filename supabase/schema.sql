-- EXPRESSION media team hub — database setup.
-- Run this once in your Supabase project: SQL Editor -> New query -> paste -> Run.

-- Scheduled posts / tasks. Either repeats weekly (dow: 0=Monday .. 6=Sunday)
-- or happens on one specific date.
create table if not exists items (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  notes text not null default '',
  branch text not null default 'social', -- social | media | editing
  assignee text not null default '',
  recurring boolean not null default false,
  dow int check (dow between 0 and 6),
  date date,
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

-- Reels pipeline.
create table if not exists reels (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  notes text not null default '',
  assignee text not null default '',
  status text not null default 'idea', -- idea | approved | filming | editing | ready | posted
  due_date date,
  created_at timestamptz not null default now()
);

-- The app is shared via a private link with a small trusted team, so the
-- anon key gets full read/write. Don't post the app link publicly.
alter table items enable row level security;
alter table completions enable row level security;
alter table reels enable row level security;

create policy "team access" on items for all using (true) with check (true);
create policy "team access" on completions for all using (true) with check (true);
create policy "team access" on reels for all using (true) with check (true);

-- Live updates: when one person changes something, everyone else sees it.
alter publication supabase_realtime add table items;
alter publication supabase_realtime add table completions;
alter publication supabase_realtime add table reels;

-- Starter weekly calendar (placeholder until the real Instagram sheet is
-- loaded). Safe to edit or delete from inside the app.
insert into items (title, branch, recurring, dow) values
  ('Motivation Monday — encouragement quote post', 'social',  true, 0),
  ('Upload Sunday sermon to YouTube',              'editing', true, 0),
  ('Testimony Tuesday — share a testimony',        'social',  true, 1),
  ('Cut sermon highlights for Spotify podcast',    'editing', true, 1),
  ('Midweek check-in — Bible study reminder story','social',  true, 2),
  ('Throwback Thursday — photos from last service','media',   true, 3),
  ('Reel drop — weekly reel goes live',            'social',  true, 4),
  ('Sunday invite story + countdown',              'social',  true, 5),
  ('Service day — live stories + photo coverage',  'media',   true, 6),
  ('Post-service recap post',                      'social',  true, 6);

insert into reels (title, notes, status) values
  ('Welcome to Expression — intro reel', 'Quick cuts of the team + what each branch does.', 'idea'),
  ('Sunday in 30 seconds — recap reel',  'Best moments from last service, fast cuts to music.', 'filming'),
  ('Worship night highlights',           'Footage is in the shared drive, needs colour + captions.', 'editing');
