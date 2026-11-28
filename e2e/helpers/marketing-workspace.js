import { execFileSync } from 'node:child_process';

export async function workspace(page, info) {
  const database = info.outputPath('marketing.sqlite3');
  const callApi = request => {
    const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
    return JSON.parse(execFileSync(python, ['-X', 'utf8', 'e2e/helpers/marketing-api.py', database, JSON.stringify(request)],
      { encoding: 'utf8', env: { ...process.env, PYTHONPATH: process.cwd() } }));
  };
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_token', 'marketing-test-owner');
    localStorage.setItem('uz_stock_analyzer_language', 'ru');
  });
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/admin/ai-marketing/')) {
      const response = callApi({ method: request.method(), path: path + new URL(request.url()).search, body: request.postDataJSON(), cookie: request.headers().cookie });
      if (response.base64) return route.fulfill({ status: response.status, body: Buffer.from(response.base64, 'base64'), headers: response.headers });
      return route.fulfill({ status: response.status, json: response.body, headers: response.headers });
    }
    if (path === '/api/auth/me') return route.fulfill({ json: { user: { id: 1, email: 'owner@example.test', full_name: 'Owner', is_admin: true } } });
    return route.fulfill({ json: { ok: true, items: [], rows: [], streams: [] } });
  });
  await page.goto('/admin/ai-marketing');
  return callApi;
}
