-- ---------------------------------------------------------------
-- LOCKDOWN / CUTOVER SCRIPT — run this ONCE, at the moment you want to
-- switch the app from "anyone with the link" to "signed-in people only".
--
-- BEFORE running this:
--   1. Make sure supabase/schema.sql (or the add_profiles_and_roles
--      migration) has already been applied — this script depends on the
--      profiles table and the is_staff()/is_admin() helpers.
--   2. In the Supabase dashboard: Authentication -> Providers -> Email,
--      turn OFF "Confirm email" (so password sign-up works without an
--      email service). Leave "Enable Email provider" ON.
--   3. Sign in once in the app as the owner (ehepes@yahoo.com) so the
--      admin profile is created. You can do this right after running this.
--
-- AFTER running this the rules are:
--   admin/editor  -> full read/write on everything
--   requester     -> can ONLY insert requests and read their own requests;
--                    no access to the calendar, projects, links, etc.
--   signed out    -> no access at all.
--
-- To UNDO (go back to open access), see the block at the very bottom.
-- ---------------------------------------------------------------

-- Staff-only tables: calendar, completions, projects, members, week duty,
-- exceptions and shared links. Replace the open "team access" policy with a
-- role-gated one.
do $$
declare t text;
begin
  foreach t in array array[
    'items','completions','projects','members',
    'week_assignments','item_exceptions','links'
  ] loop
    execute format('drop policy if exists "team access" on public.%I', t);
    execute format('drop policy if exists "staff all" on public.%I', t);
    execute format(
      'create policy "staff all" on public.%I for all
         using (public.is_staff()) with check (public.is_staff())', t);
  end loop;
end $$;

-- Requests: staff get everything; requesters can create a request and read
-- back only the ones they submitted.
drop policy if exists "team access" on public.requests;
drop policy if exists "staff all requests" on public.requests;
create policy "staff all requests" on public.requests for all
  using (public.is_staff()) with check (public.is_staff());

drop policy if exists "requester insert own" on public.requests;
create policy "requester insert own" on public.requests for insert
  with check (auth.uid() is not null and created_by = auth.uid());

drop policy if exists "requester read own" on public.requests;
create policy "requester read own" on public.requests for select
  using (created_by = auth.uid());

-- Push subscriptions: any signed-in user may register their own device.
drop policy if exists "team access" on public.push_subscriptions;
drop policy if exists "authed push" on public.push_subscriptions;
create policy "authed push" on public.push_subscriptions for all
  using (auth.uid() is not null) with check (auth.uid() is not null);

-- ---------------------------------------------------------------
-- UNDO (emergency rollback to fully open access). Uncomment and run:
--
-- do $$
-- declare t text;
-- begin
--   foreach t in array array[
--     'items','completions','projects','members','week_assignments',
--     'item_exceptions','links','requests','push_subscriptions'
--   ] loop
--     execute format('drop policy if exists "staff all" on public.%I', t);
--     execute format('drop policy if exists "staff all requests" on public.%I', t);
--     execute format('drop policy if exists "requester insert own" on public.%I', t);
--     execute format('drop policy if exists "requester read own" on public.%I', t);
--     execute format('drop policy if exists "authed push" on public.%I', t);
--     execute format('drop policy if exists "team access" on public.%I', t);
--     execute format('create policy "team access" on public.%I for all using (true) with check (true)', t);
--   end loop;
-- end $$;
-- ---------------------------------------------------------------
