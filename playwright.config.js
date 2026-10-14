import { defineConfig, devices } from "@playwright/test";

const remoteBaseURL = process.env.E2E_BASE_URL;

// E2E_ORIGIN=host:port sends the remote site's own hostname to that address
// instead of its public DNS — the post-deploy check reaches the server's nginx
// through an SSH tunnel, past the hosting provider's front proxy, so a deploy
// is judged by the site and not by the route to it. The URL, Host header and
// TLS name stay the site's own; only the certificate is not checked, because
// the origin's is not the one the public proxy presents.
const origin = remoteBaseURL && process.env.E2E_ORIGIN;
const originUse = origin ? {
  ignoreHTTPSErrors: true,
  launchOptions: { args: [`--host-resolver-rules=MAP ${new URL(remoteBaseURL).hostname}:443 ${origin}`] },
} : {};

/**
 * Smoke e2e for the chat-first frontend.
 * Runs against the built app served by `vite preview`. All /api/** calls are
 * mocked per-test (see e2e/smoke.spec.js), so no backend or LLM key is needed.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: remoteBaseURL || "http://localhost:4173",
    colorScheme: "light",
    trace: "retain-on-failure",
    ...originUse,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: remoteBaseURL ? undefined : {
    command: "npm run preview -- --port 4173 --strictPort",
    port: 4173,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
