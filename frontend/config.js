/* Public runtime configuration.
   Overwritten at container start from environment variables (see entrypoint.sh).
   Only PUBLIC values belong here - never a secret key. */
window.APP_CONFIG = {
  APP_ENV: "dev",
  API_BASE_URL: "http://localhost:8000",
  SUPABASE_URL: "",
  SUPABASE_PUBLISHABLE_KEY: ""
};
