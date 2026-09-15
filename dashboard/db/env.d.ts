declare namespace Cloudflare {
  interface Env {
    DB: D1Database;
    VESSEL_AUTH_SECRET: string;
    VESSEL_AUTH_URL: string;
  }
}
