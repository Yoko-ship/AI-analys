import { useEffect, useState, useSyncExternalStore } from "react";
import { createSession } from "./session.js";
import { requestStepUpCode } from "./stepUp.js";

/** React adapter; session ordering, persistence and races belong to session.js. */
export function useSession(language) {
  const [session] = useState(() => createSession({
    persistentStorage: localStorage,
    temporaryStorage: sessionStorage,
    fetcher: (...args) => fetch(...args),
    requestStepUp: requestStepUpCode,
  }));
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot);

  useEffect(() => {
    session.startLocalSession(window.location.hostname);
  }, [session]);

  useEffect(() => {
    if (snapshot.token) session.refreshSession().catch(() => {
      session.startLocalSession(window.location.hostname);
    });
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
