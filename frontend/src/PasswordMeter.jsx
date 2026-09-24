import React from "react";
import { passwordHint, passwordLevelLabel, passwordStrength } from "./lib/passwordStrength.js";

// Four-segment strength bar with a one-line reason, shown while a new
// password is typed. The server applies the same policy and has the final say.
export function PasswordMeter({ password, email = "", fullName = "", language = "ru" }) {
  const strength = passwordStrength(password, { email, fullName });
  if (strength.level === "empty") return null;
  return (
    <div className={`password-meter is-${strength.level}`} role="status" aria-live="polite">
      <div className="password-meter-bar" aria-hidden="true">
        {[1, 2, 3, 4].map((step) => <span key={step} className={step <= strength.score ? "is-on" : ""} />)}
      </div>
      <p><strong>{passwordLevelLabel(strength, language)}</strong> · {passwordHint(strength, language)}</p>
    </div>
  );
}

export default PasswordMeter;
