/**
 * icons.jsx — the admin panel's icon set.
 *
 * Lucide paths, inlined. One <symbol> sprite is mounted once and every icon is
 * a <use>, so an icon costs a reference rather than a repeated path — the
 * findings table alone would otherwise ship the same eight paths per row.
 *
 * Stroke width, cap and join live on the <svg>, not on the paths, so a single
 * class controls the whole set's weight. Do NOT swap these for unicode glyphs:
 * they arrive in whatever font the OS picks, at whatever baseline it likes.
 */
import React from "react";

const PATHS = {
  dashboard: <><rect width="7" height="9" x="3" y="3" rx="1" /><rect width="7" height="5" x="14" y="3" rx="1" /><rect width="7" height="9" x="14" y="12" rx="1" /><rect width="7" height="5" x="3" y="16" rx="1" /></>,
  refresh: <><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 16H3v5" /></>,
  alert: <><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4" /><path d="M12 17h.01" /></>,
  list: <><path d="M3 12h.01" /><path d="M3 18h.01" /><path d="M3 6h.01" /><path d="M8 12h13" /><path d="M8 18h13" /><path d="M8 6h13" /></>,
  file: <><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /><path d="M16 13H8" /><path d="M16 17H8" /></>,
  chart: <><path d="M3 3v16a2 2 0 0 0 2 2h16" /><path d="M18 17V9" /><path d="M13 17V5" /><path d="M8 17v-3" /></>,
  percent: <><line x1="19" x2="5" y1="5" y2="19" /><circle cx="6.5" cy="6.5" r="2.5" /><circle cx="17.5" cy="17.5" r="2.5" /></>,
  news: <><path d="M15 18h-5" /><path d="M18 14h-8" /><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-4 0v-9a2 2 0 0 1 2-2h2" /></>,
  image: <><rect width="18" height="18" x="3" y="3" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21" /></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>,
  sliders: <><line x1="21" x2="14" y1="4" y2="4" /><line x1="10" x2="3" y1="4" y2="4" /><line x1="21" x2="12" y1="12" y2="12" /><line x1="8" x2="3" y1="12" y2="12" /><line x1="21" x2="16" y1="20" y2="20" /><line x1="12" x2="3" y1="20" y2="20" /><line x1="14" x2="14" y1="2" y2="6" /><line x1="8" x2="8" y1="10" y2="14" /><line x1="16" x2="16" y1="18" y2="22" /></>,
  search: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></>,
  updown: <><path d="m7 15 5 5 5-5" /><path d="m7 9 5-5 5 5" /></>,
  dots: <><circle cx="12" cy="12" r="1" /><circle cx="12" cy="5" r="1" /><circle cx="12" cy="19" r="1" /></>,
  up: <><path d="M16 7h6v6" /><path d="m22 7-8.5 8.5-5-5L2 17" /></>,
  down: <><path d="M16 17h6v-6" /><path d="m22 17-8.5-8.5-5 5L2 7" /></>,
  panel: <><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M9 3v18" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="m4.9 4.9 1.4 1.4" /><path d="m17.7 17.7 1.4 1.4" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="m6.3 17.7-1.4 1.4" /><path d="m19.1 4.9-1.4 1.4" /></>,
  moon: <><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" /></>,
  play: <><polygon points="6 3 20 12 6 21 6 3" /></>,
  check: <><path d="M20 6 9 17l-5-5" /></>,
  external: <><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></>,
  clock: <><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>,
  arrowLeft: <><path d="m12 19-7-7 7-7" /><path d="M19 12H5" /></>,
  lock: <><rect width="18" height="11" x="3" y="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>,
};

export const ICON_NAMES = Object.keys(PATHS);

/** Mount once, near the root of the panel. */
export function IconSprite() {
  return (
    <svg aria-hidden="true" style={{ display: "none" }}>
      {ICON_NAMES.map((name) => (
        <symbol key={name} id={`adm-${name}`} viewBox="0 0 24 24">{PATHS[name]}</symbol>
      ))}
    </svg>
  );
}

export function Icon({ name, className = "", size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg className={`adm-i ${className}`.trim()} style={style} aria-hidden="true">
      <use href={`#adm-${name}`} />
    </svg>
  );
}

export default Icon;
