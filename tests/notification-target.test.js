import test from "node:test";
import assert from "node:assert/strict";

import { notificationPath } from "../frontend/src/lib/notificationTarget.js";

// Shapes as /api/notifications builds them (server/accounts/notifications.py).
test("every company alert opens its company, whatever its kind", () => {
  const report = { ticker: "SQBN", report_form: "IFRS", year: 2026, quarter: 2, title: "Q2", detected_at: "2026-10-12" };
  const price = { ticker: "hmkb", report_form: "PRICE", kind: "price_threshold", price: 41.19, threshold: 40 };
  const pattern = { ticker: "KVTS", kind: "pattern", pattern: "double_bottom", direction: "bullish" };
  assert.equal(notificationPath(report), "/company/SQBN");
  assert.equal(notificationPath(price), "/company/HMKB");
  assert.equal(notificationPath(pattern), "/company/KVTS");
});

test("an alert the server routes itself goes where the server says", () => {
  assert.equal(notificationPath({ ticker: "ADMIN", kind: "feedback", href: "/admin/feedback" }), "/admin/feedback");
  assert.equal(notificationPath({ ticker: "ADMIN", kind: "data_pipeline", href: "/admin" }), "/admin");
});

test("an alert with nowhere to go is not sent to a fake company", () => {
  assert.equal(notificationPath({ ticker: "ADMIN", kind: "something_new" }), null);
  assert.equal(notificationPath({}), null);
  assert.equal(notificationPath(null), null);
  assert.equal(notificationPath({ ticker: "SQBN", href: "javascript:alert(1)" }), "/company/SQBN");
});
