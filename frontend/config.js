/* Public runtime configuration - LOCAL DEVELOPMENT DEFAULTS.
 *
 * The container never uses this file's contents: entrypoint.sh overwrites
 * /srv/config.js from environment variables at start. So what is committed here
 * is only what a developer gets when serving frontend/ directly.
 *
 * Only PUBLIC values belong here. The publishable key is public by design - it
 * is sent to every browser that loads the app - and RLS is what protects data.
 * A secret key must never appear in this file.
 */
window.APP_CONFIG = {
  APP_ENV: "dev",
  API_BASE_URL: "http://localhost:8000",
  SUPABASE_URL: "https://wnttlpxiycghqiibdpjr.supabase.co",
  SUPABASE_PUBLISHABLE_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndudHRscHhpeWNnaHFpaWJkcGpyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk2MDU3NjgsImV4cCI6MjEwNTE4MTc2OH0.P6Kpbccguyzpxi-ioooSVL3pRPKr10jFGclWTOYYBzo"
};
