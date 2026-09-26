import assert from "node:assert/strict";
import { test } from "node:test";
import { createSession, TOKEN_KEY, REMEMBER_KEY } from "../frontend/src/session/session.js";

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return { getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) };
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const json = (data, status = 200) => new Response(JSON.stringify(data), { status });
function setup(fetcher = async () => json({}), initial = {}) {
  const persistentStorage = storage(initial);
  const temporaryStorage = storage();
  return { persistentStorage, temporaryStorage,
    session: createSession({ persistentStorage, temporaryStorage, fetcher }) };
}

test("remembered sessions survive restoration; temporary sessions do not become persistent", () => {
  const { session, persistentStorage, temporaryStorage } = setup();
  session.acceptSession({ token: "remembered", user: { id: 1 } });
  assert.equal(persistentStorage.getItem(TOKEN_KEY), "remembered");
  session.acceptSession({ token: "temporary", user: { id: 2 } }, { remember: false });
  assert.equal(persistentStorage.getItem(TOKEN_KEY), null);
  assert.equal(temporaryStorage.getItem(TOKEN_KEY), "temporary");
  assert.equal(persistentStorage.getItem(REMEMBER_KEY), "0");
  assert.equal(createSession({ persistentStorage, temporaryStorage, fetcher: fetch }).getSnapshot().token, "temporary");
  session.acceptSession({ token: "remembered-again" });
  assert.equal(temporaryStorage.getItem(TOKEN_KEY), null);
});

test("requests use a newly accepted token immediately and preserve custom headers and form uploads", async () => {
  const calls = [];
  const { session } = setup(async (...args) => { calls.push(args); return json({}); });
  session.acceptSession({ token: "new" });
  await session.getSnapshot().apiFetch("/api/profile", { body: JSON.stringify({ full_name: "Test" }), headers: { "X-Test": "yes" } });
  assert.equal(calls[0][1].headers.get("Authorization"), "Bearer new");
  assert.equal(calls[0][1].headers.get("X-Test"), "yes");
  assert.equal(calls[0][1].headers.get("Content-Type"), "application/json");
  await session.getSnapshot().apiFetch("/api/profile/avatar", { body: new FormData() });
  assert.equal(calls[1][1].headers.has("Content-Type"), false);
});

test("profile and identity refreshes keep the request function stable", async () => {
  const { session } = setup(async () => json({ user: { id: 1 } }), { [TOKEN_KEY]: "saved" });
  const request = session.getSnapshot().apiFetch;
  await session.refreshSession();
  await session.refreshProfile();
  assert.equal(session.getSnapshot().apiFetch, request);
  assert.equal(session.getSnapshot().profile.user.id, 1);
});

test("logout clears both stores immediately even if server revocation fails", async () => {
  const pending = deferred();
  const { session, persistentStorage, temporaryStorage } = setup(() => pending.promise, { [TOKEN_KEY]: "saved" });
  const completed = session.logout();
  assert.equal(session.getSnapshot().token, "");
  assert.equal(persistentStorage.getItem(TOKEN_KEY), null);
  assert.equal(temporaryStorage.getItem(TOKEN_KEY), null);
  pending.reject(new Error("offline"));
  await completed;
});

test("a late profile response cannot restore data after logout", async () => {
  const pending = deferred();
  const { session } = setup(path => path === "/api/profile" ? pending.promise : Promise.resolve(json({})), { [TOKEN_KEY]: "old" });
  const read = session.refreshProfile();
  await session.logout();
  pending.resolve(json({ user: { id: 1 } }));
  assert.equal(await read, null);
  assert.equal(session.getSnapshot().profile, null);
});

test("a failed validation of the previous user cannot clear a newer login", async () => {
  const pending = deferred();
  const { session } = setup(() => pending.promise, { [TOKEN_KEY]: "old" });
  const validation = session.refreshSession();
  session.acceptSession({ token: "new", user: { id: 2 } });
  pending.resolve(json({ detail: "expired" }, 401));
  assert.equal(await validation, null);
  assert.equal(session.getSnapshot().token, "new");
  assert.equal(session.getSnapshot().user.id, 2);
});

test("an invalid current session clears its private data and credentials", async () => {
  const { session, persistentStorage } = setup(async () => json({ detail: "expired" }, 401));
  session.acceptSession({ token: "invalid", user: { id: 1 } });
  await assert.rejects(session.refreshSession(), /expired/);
  assert.equal(session.getSnapshot().user, null);
  assert.equal(session.getSnapshot().profile, null);
  assert.equal(persistentStorage.getItem(TOKEN_KEY), null);
});

test("the newest profile refresh wins if responses arrive out of order", async () => {
  const first = deferred(), second = deferred();
  let calls = 0;
  const { session } = setup(() => (++calls === 1 ? first : second).promise, { [TOKEN_KEY]: "saved" });
  const oldRead = session.refreshProfile(), newRead = session.refreshProfile();
  second.resolve(json({ notes: ["new"] }));
  await newRead;
  first.resolve(json({ notes: ["old"] }));
  assert.equal(await oldRead, null);
  assert.deepEqual(session.getSnapshot().profile.notes, ["new"]);
});

test("successful profile edits survive overlapping profile and identity reads", async () => {
  const write = deferred(), read = deferred(), identity = deferred();
  const { session } = setup((path, options) => options.method === "PATCH" ? write.promise : path.endsWith("/me") ? identity.promise : read.promise,
    { [TOKEN_KEY]: "saved" });
  const save = session.saveProfile({ full_name: "New name" });
  const refresh = session.refreshProfile(), validate = session.refreshSession();
  write.resolve(json({ user: { id: 1, full_name: "New name" } }));
  assert.equal((await save).user.full_name, "New name");
  read.resolve(json({ user: { id: 1, full_name: "Old name" } }));
  identity.resolve(json({ user: { id: 1, full_name: "Old name" } }));
  assert.equal(await refresh, null);
  assert.equal(await validate, null);
  assert.equal(session.getSnapshot().user.full_name, "New name");
});

test("late edits from a previous account cannot overwrite the new account", async () => {
  const write = deferred();
  const { session } = setup(() => write.promise, { [TOKEN_KEY]: "old" });
  const save = session.saveProfile({ full_name: "Old user edit" });
  session.acceptSession({ token: "new", user: { id: 2 } });
  write.resolve(json({ user: { id: 1, full_name: "Old user edit" } }));
  assert.equal(await save, null);
  assert.equal(session.getSnapshot().user.id, 2);
});

test("subscribers observe changes and can unsubscribe", () => {
  const { session } = setup();
  const observed = [];
  const unsubscribe = session.subscribe(() => observed.push(session.getSnapshot().token));
  session.acceptSession({ token: "one" });
  unsubscribe();
  session.acceptSession({ token: "two" });
  assert.deepEqual(observed, ["one"]);
});
