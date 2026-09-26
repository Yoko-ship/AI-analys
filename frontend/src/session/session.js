export const TOKEN_KEY = "uz_stock_analyzer_token";
export const REMEMBER_KEY = "uz_stock_analyzer_remember";

/** Own one browser session. Storage and HTTP are replaceable adapters. */
export function createSession({ persistentStorage, temporaryStorage, fetcher }) {
  let generation = 0;
  let validationVersion = 0;
  let profileVersion = 0;
  let mutationVersion = 0;
  const listeners = new Set();
  const requestWith = (token) => async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetcher(path, { ...options, headers });
  };
  const token = persistentStorage.getItem(TOKEN_KEY) || temporaryStorage.getItem(TOKEN_KEY) || "";
  let snapshot = { token, user: null, profile: null, apiFetch: requestWith(token) };

  function publish(changes) {
    snapshot = { ...snapshot, ...changes };
    for (const listener of listeners) listener();
  }

  function clear() {
    generation += 1;
    profileVersion += 1;
    persistentStorage.removeItem(TOKEN_KEY);
    temporaryStorage.removeItem(TOKEN_KEY);
    publish({ token: "", user: null, profile: null, apiFetch: requestWith("") });
  }

  function acceptSession(data, { remember = true } = {}) {
    if (!data.token) return;
    generation += 1;
    profileVersion += 1;
    persistentStorage.setItem(REMEMBER_KEY, remember ? "1" : "0");
    const selected = remember ? persistentStorage : temporaryStorage;
    const other = remember ? temporaryStorage : persistentStorage;
    selected.setItem(TOKEN_KEY, data.token);
    other.removeItem(TOKEN_KEY);
    publish({ token: data.token, user: data.user || null, profile: null, apiFetch: requestWith(data.token) });
  }

  async function refreshSession() {
    if (!snapshot.token) return null;
    const current = generation;
    const version = ++validationVersion;
    let rejected = false;
    try {
      const response = await snapshot.apiFetch("/api/auth/me");
      rejected = response.status === 401;
      const data = await response.json();
      if (current !== generation || version !== validationVersion) return null;
      if (!response.ok) throw new Error(data.detail || "Session is invalid");
      publish({ user: data.user });
      return data.user;
    } catch (error) {
      if (current !== generation || version !== validationVersion) return null;
      // Transport and server failures do not revoke a valid credential.
      if (rejected) clear();
      throw error;
    }
  }

  async function refreshProfile() {
    if (!snapshot.token) return null;
    const current = generation;
    const version = ++profileVersion;
    try {
      const response = await snapshot.apiFetch("/api/profile");
      const data = await response.json();
      if (current !== generation || version !== profileVersion) return null;
      if (!response.ok) throw new Error(data.detail || "Could not load profile");
      publish({ profile: data });
      return data;
    } catch (error) {
      if (current !== generation || version !== profileVersion) return null;
      throw error;
    }
  }

  async function saveProfile(payload) {
    if (!snapshot.token) throw new Error("Session is invalid");
    const current = generation;
    // Older profile reads must not overwrite a successful edit.
    const version = ++mutationVersion;
    profileVersion += 1;
    const response = await snapshot.apiFetch("/api/profile", {
      method: "PATCH", body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (current !== generation || version !== mutationVersion) return null;
    if (!response.ok) throw new Error(data.detail || "Could not save profile");
    profileVersion += 1;
    validationVersion += 1;
    publish({ user: data.user,
      profile: snapshot.profile ? { ...snapshot.profile, user: data.user } : null });
    return data;
  }

  async function logout() {
    const revoke = snapshot.apiFetch;
    const hadToken = Boolean(snapshot.token);
    clear();
    if (hadToken) {
      try { await revoke("/api/auth/logout", { method: "POST" }); } catch { /* local logout still succeeds */ }
    }
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    acceptSession, refreshSession, refreshProfile, saveProfile, logout,
  };
}
