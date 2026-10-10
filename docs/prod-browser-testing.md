# Browser tests against production

Any automated browser run against the live site (uzstock.uz) must mark its
browser as internal, so that it does not show up in the admin audience numbers.

## Why

On 2026-10-10 a phone-layout check opened about 100 fresh Playwright browsers
and loaded about 700 pages on prod. Each fresh browser gets its own visitor id,
and the bot filter in `web_analytics.py` only drops user agents containing
"headless". Playwright's device presets (iPhone 13, Desktop Chrome) send a real
Safari/Chrome user agent, so every one of those browsers was counted as a real
visitor. The admin «Посетителей сегодня» card showed 107 (+53% against 70 the
day before), and most of that jump was the test.

## The rule

Set the internal flag before the page loads. It is the same flag as the site's
own «Не считать этот браузер» option (`uz_track_internal` in `localStorage`,
read by `frontend/src/lib/track.js`). The beacon then sends `internal = true`,
and the admin views (the `ev` temp view in `web_analytics.py`) leave that
visitor out.

```js
await context.addInitScript(() => {
  try { localStorage.setItem('uz_track_internal', '1'); } catch (e) { /* ignore */ }
});
```

Alternatively, mock `/api/track` so the beacon never reaches the server.

## What is not affected

The repository's own e2e suite (`npm run test:e2e`) runs against
`vite preview` and mocks every `/api/**` call, so it never reaches the
production analytics.

Two opt-in specs are the exception: `e2e/production-market.spec.js`
(`E2E_PRODUCTION_SMOKE`) and `e2e/production-calendar.spec.js`
(`E2E_BASE_URL`) talk to the real API on purpose and do not set the internal
flag yet, so each run against prod counts as one visitor.

## Events that were already recorded

Removing test events that were already counted means deleting rows from the
production `web_events` table. That is a permanent change to live data: agree
on it with the site owner before doing it.
