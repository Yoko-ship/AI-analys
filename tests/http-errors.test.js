// API failures shown to a reader (frontend/src/lib/httpErrors.js).
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";
import { apiErrorMessage, rateLimitMessage, readApiResponse } from "../frontend/src/lib/httpErrors.js";

const response = (status, body, headers = {}) => ({
  status,
  ok: status < 400,
  headers: { get: (name) => headers[name] ?? null },
  text: async () => body,
});

describe("rateLimitMessage", () => {
  it("states the wait in the interface language with Russian number agreement", () => {
    assert.equal(rateLimitMessage("42", "ru"), "Превышен лимит запросов. Попробуйте через 42 секунды.");
    assert.equal(rateLimitMessage("21", "ru"), "Превышен лимит запросов. Попробуйте через 21 секунду.");
    assert.equal(rateLimitMessage("15", "ru"), "Превышен лимит запросов. Попробуйте через 15 секунд.");
    assert.match(rateLimitMessage("30", "uz"), /30 soniyadan/);
    assert.equal(rateLimitMessage("30", "en"), "Request limit exceeded. Try again in 30 seconds.");
  });

  it("calls a day-long wait a daily limit and survives a missing header", () => {
    assert.match(rateLimitMessage("86000", "ru"), /Дневной лимит/);
    assert.match(rateLimitMessage(null, "ru"), /через 60 секунд/);
  });
});

describe("apiErrorMessage", () => {
  it("words a 429 from Retry-After, not from the server's English text", async () => {
    const res = response(429, JSON.stringify({ detail: "Too many analysis requests — try again in a minute" }), { "Retry-After": "12" });
    const { data } = await readApiResponse(res);
    assert.equal(apiErrorMessage(res, data, "ru"), "Превышен лимит запросов. Попробуйте через 12 секунд.");
  });

  it("does not throw on a proxy's HTML error page", async () => {
    const res = response(504, "<html><body>504 Gateway Time-out</body></html>");
    const parsed = await readApiResponse(res);
    assert.deepEqual(parsed, { data: null, json: false });
    assert.match(apiErrorMessage(res, parsed.data, "ru"), /Сервер временно не ответил \(504\)/);
  });

  it("keeps a localized server detail and names the id of an opaque 500", async () => {
    const notFound = response(404, JSON.stringify({ detail: "Анализ не выполняется: в отчёте за 2024 год нет баланса." }));
    assert.match(apiErrorMessage(notFound, (await readApiResponse(notFound)).data, "ru"), /нет баланса/);
    const opaque = response(500, JSON.stringify({ detail: "Internal server error", error_id: "c7915b49c1e5" }));
    assert.equal(apiErrorMessage(opaque, (await readApiResponse(opaque)).data, "ru"),
      "Внутренняя ошибка сервера. Код ошибки: c7915b49c1e5.");
  });
});
