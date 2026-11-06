import { defineConfig } from '@playwright/test';
import base from './playwright.config.js';

// Startup needs Python's SEO HTML, which Vite preview does not produce.
export default defineConfig({
  ...base,
  metadata: { landingServer: true },
  testMatch: /landing-(startup|appearance|restoration)\.spec\.js/,
  use: { ...base.use, baseURL: 'http://127.0.0.1:4175' },
  webServer: {
    command: '.venv/bin/python -m uvicorn e2e.landing_shell_app:app --host 127.0.0.1 --port 4175 --lifespan off',
    port: 4175,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      PYTHON_DOTENV_DISABLED: '1', DATABASE_URL: '', DATABASE_PUBLIC_URL: '', DATABASE_BACKEND: 'sqlite',
      APP_DATA_DIR: '/tmp/uzstock-landing-e2e', GEOIP_REFRESH: '0',
    },
  },
});
