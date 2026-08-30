export const SERVICE = "33333333-3333-4333-8333-333333333333";
export const DEPLOYMENT = "44444444-4444-4444-8444-444444444444";
export const OLDER = "55555555-5555-4555-8555-555555555555";
export const deployment = { id: DEPLOYMENT, status: "CRASHED", changed_at: "2026-08-30T07:02:00Z", created_at: "2026-08-30T07:00:00Z" };
export const snapshot = { configured: true, environment: "production", project_id: "demo", checked_at: "2026-08-30T07:03:00Z", services: [
  { id: SERVICE, name: "reports-watch", cron_schedule: "0 3 * * *", next_run_at: "2026-08-31T03:00:00Z", deployment, recovery_action: "restart", railway_url: "https://railway.com" },
  { id: "66666666-6666-4666-8666-666666666666", name: "quotes-2130", deployment: { ...deployment, status: "FAILED" }, recovery_action: "redeploy", railway_url: "https://railway.com" },
  { id: "77777777-7777-4777-8777-777777777777", name: "bank-fx", cron_schedule: "0 3 * * *", next_run_at: "2026-08-31T03:00:00Z", deployment: { ...deployment, status: "SUCCESS" }, recovery_action: null, railway_url: "https://railway.com" },
  { id: "88888888-8888-4888-8888-888888888888", name: "AI-analys", deployment: { ...deployment, status: "SUCCESS" }, recovery_action: null, railway_url: "https://railway.com" },
] };
export const history = { deployments: [deployment, { ...deployment, id: OLDER, status: "FAILED", changed_at: "2026-08-29T07:02:00Z" }] };
export const runtimeLogs = { kind: "runtime", error_excerpt: "ModuleNotFoundError: No module named 'main'", lines: [
  { timestamp: "2026-08-30T07:02:00Z", severity: "error", message: "Traceback (most recent call last):\n  File '/app/bot.py', line 42, in <module>\nModuleNotFoundError: No module named 'main'" },
] };
