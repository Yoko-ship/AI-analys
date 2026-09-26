import React from "react";

const COMPACT_MARK_LOGO_TICKERS = new Set([
  "BNGP", "BNGPP", "CBSK", "MIQE", "PLST", "TKDM", "TKDMP", "TMYS",
  "UPOS", "UPOSP", "URTS", "UTYK", "UZAL", "UZINP", "UZML", "UZNF", "YRFS",
]);

function CompanyLogo({ logo, name, ticker }) {
  const [failed, setFailed] = React.useState(false);
  if (!logo || failed) {
    // No logo: render a designed monogram tile — the ticker initials over a
    // gradient whose hue is derived deterministically from the ticker, so each
    // issuer gets a distinct, stable, intentional-looking mark.
    const seed = ticker || name || "?";
    const mono = (seed.replace(/[^A-Za-z0-9]/g, "").slice(0, 2) || "?").toUpperCase();
    let h = 0;
    for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 360;
    return <span className="chip-logo-fallback" style={{ "--mono-h": h }}>{mono}</span>;
  }
  // Self-hosted icon-marks (/logos/*) are transparent and float directly on the
  // surface; remote and /logos/plate/* (wordmark/dark) logos keep a light plate.
  const isFloat = typeof logo === "string"
    && logo.startsWith("/logos/") && !logo.startsWith("/logos/plate/");
  const useCompactMark = COMPACT_MARK_LOGO_TICKERS.has(String(ticker || "").toUpperCase());
  return (
    <img
      className={`chip-logo${isFloat ? " chip-logo--float" : ""}${useCompactMark ? " chip-logo--compact-mark" : ""}`}
      src={logo}
      alt={name}
      onError={() => setFailed(true)}
      loading="lazy"
    />
  );
}

export { CompanyLogo };
