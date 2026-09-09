// ---------------------------------------------------------------
// Team sync configuration (optional but recommended).
//
// Without this, the app still works — but each person's data stays
// on their own device. To make the whole team see the same calendar,
// reels and progress:
//
//   1. Create a free account at https://supabase.com (no card needed)
//   2. Create a new project (any name, e.g. "expression")
//   3. In the project: SQL Editor -> paste the contents of
//      supabase/schema.sql -> Run
//   4. In the project: Settings -> API -> copy "Project URL" and
//      the "anon public" key into the two fields below
//   5. Commit/redeploy. Done — everyone now shares the same data.
// ---------------------------------------------------------------
window.EXPRESSION_CONFIG = {
  SUPABASE_URL: "https://lboueyjikfjtycymigtw.supabase.co",
  // Legacy "anon public" JWT key. Used (instead of the newer sb_publishable_
  // key) because Edge Functions accept it by default — so push works without
  // having to disable "Verify JWT" on the function. Safe to expose (public key).
  SUPABASE_ANON_KEY:
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxib3VleWppa2ZqdHljeW1pZ3R3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEyMDAxMjQsImV4cCI6MjA5Njc3NjEyNH0.da5mcPwQH-4uPBjWth7DZdvGJhavhDHpTVRhoy42f38",
  // Public half of the Web Push (VAPID) key. Safe to expose — the private half
  // lives only as a secret in Supabase. See supabase/PUSH-SETUP.md.
  VAPID_PUBLIC_KEY: "BG66k15619dm35UKc9r6vPAbft76i8Iv8RL1t6TvnuTv5kQgGmgkKBlBV4MrxcKREsQ8Xw8JFGFB4Ht3OsHn34A",
};
