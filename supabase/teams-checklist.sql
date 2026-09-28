-- EXPRESSION — switch Media & Editing to the weekly-checklist model.
-- Run this ONCE in the Supabase SQL Editor (New query -> paste -> Run).
-- It is written to be safe to re-run: deletes are by exact title, and the
-- new Editing tasks are only inserted if they don't already exist.
--
-- What it does:
--   * Removes the old day-pinned Editing/Media seed tasks.
--   * Adds the Editing team's 4 weekly standing tasks (no fixed day).
--   * Leaves the Media team blank — build its Sunday shoot list in the app.

-- 1) Remove the old day-pinned seed tasks (only the original seeds; anything
--    you created yourself is left untouched).
delete from items
where branch in ('editing', 'media')
  and title in (
    'Upload Sunday sermon to YouTube',
    'Cut sermon highlights for Spotify podcast',
    'Service day — live stories + photo coverage'
  );

-- 2) Add the Editing team's weekly standing tasks (dow null = whole week).
--    Guarded so re-running doesn't create duplicates.
insert into items (account, title, branch, recurring, recur, dow, nth)
select v.account, v.title, 'editing', true, 'weekly', null, null
from (values
  ('main', 'Edit Spotify'),
  ('main', 'Post Spotify'),
  ('main', 'Edit YouTube'),
  ('main', 'Post YouTube')
) as v(account, title)
where not exists (
  select 1 from items i
  where i.account = v.account and i.title = v.title and i.branch = 'editing'
);
