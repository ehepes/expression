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
  SUPABASE_URL: "",
  SUPABASE_ANON_KEY: "",
};
