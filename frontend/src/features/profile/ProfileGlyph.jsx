

function ProfileGlyph({ name }) {
  const common = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", focusable: "false" };
  if (name === "check") return <svg {...common}><polyline points="4 12 10 18 20 6" /></svg>;
  if (name === "bell") return <svg {...common}><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0" /></svg>;
  return null;
}

export { ProfileGlyph };
