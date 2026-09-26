import { useEffect, useState, useSyncExternalStore } from "react";
import { createSession } from "./session.js";

/** React adapter; session ordering, persistence and races belong to session.js. */
export function useSession(language) {
  const [session] = useState(() => createSession({
    persistentStorage: localStorage,
    temporaryStorage: sessionStorage,
    fetcher: (...args) => fetch(...args),
  }));
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot);

  useEffect(() => {
    if (snapshot.token) session.refreshSession().catch(() => {});
  }, [session, snapshot.token]);

  useEffect(() => {
    if (snapshot.user) session.refreshProfile().catch(() => {});
  }, [session, snapshot.user, language]);

  return { ...snapshot,
    acceptSession: session.acceptSession,
    refreshProfile: session.refreshProfile,
    saveProfile: session.saveProfile,
    logout: session.logout,
  };
}
