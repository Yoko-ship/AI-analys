import { useEffect, useState } from "react";

function getProfileInitials(user) {
  const source = (user?.full_name || user?.email || "?").trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0] || "";
  const second = parts.length > 1 ? parts[1][0] : parts[0][1] || "";
  return (first + second).toUpperCase();
}

function hashToHue(source) {
  return String(source || "").split("").reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) % 360, 47);
}

function ProfileAvatar({ user, src = "", className = "" }) {
  const [imageFailed, setImageFailed] = useState(false);
  const label = user?.full_name || user?.email || "Profile";
  const hue = hashToHue(user?.email || label);
  const showImage = Boolean(src) && !imageFailed;

  useEffect(() => {
    setImageFailed(false);
  }, [src]);

  return (
    <span
      className={`profile-cmd-avatar ${className}`.trim()}
      role="img"
      aria-label={label}
      style={{ background: `linear-gradient(135deg, hsl(${hue} 70% 60%), hsl(${(hue + 45) % 360} 70% 50%))` }}
    >
      {showImage ? <img src={src} alt="" onError={() => setImageFailed(true)} /> : <span className="profile-cmd-avatar-initials">{getProfileInitials(user)}</span>}
    </span>
  );
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read image"));
    reader.readAsDataURL(file);
  });
}

export { ProfileAvatar, readFileAsDataUrl };
