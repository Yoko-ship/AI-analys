

function BrandIcon({ className = "brand-icon", decorative = false }) {
  return (
    <svg
      className={className}
      viewBox="0 0 100 100"
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : "UZStock"}
      aria-hidden={decorative ? "true" : undefined}
      focusable="false"
    >
      <rect x="5" y="5" width="90" height="90" rx="24" fill="#062D5F" />
      <path d="M28 28v24c0 13.2 8 21 19 21 8.5 0 14.5-4.5 17-12.2" fill="none" stroke="#F7FBFF" strokeLinecap="round" strokeWidth="9" />
      <path d="M54 61.5 76 32" fill="none" stroke="#65E6A2" strokeLinecap="round" strokeWidth="9" />
      <path d="m64.5 32 11.5 0 0 11.5" fill="none" stroke="#65E6A2" strokeLinecap="round" strokeLinejoin="round" strokeWidth="8" />
    </svg>
  );
}

export { BrandIcon };
