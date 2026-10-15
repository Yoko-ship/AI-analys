/**
 * One pending request for the admin's authenticator code at a time. The session
 * asks (requestStepUpCode) when the server refuses an admin change with
 * MFA_REQUIRED; StepUpDialog answers with the code, or null when dismissed.
 */
let pending = null;
const listeners = new Set();

function publish() {
  for (const listener of listeners) listener();
}

export function requestStepUpCode({ message = "" } = {}) {
  return new Promise((resolve) => {
    if (pending) pending.resolve(null);
    pending = { message, resolve };
    publish();
  });
}

export function answerStepUp(code) {
  const current = pending;
  pending = null;
  publish();
  if (current) current.resolve(code || null);
}

export const getStepUp = () => pending;

export function subscribeStepUp(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
