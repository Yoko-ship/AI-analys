

function BrandIcon({ className = "brand-icon", decorative = false }) {
  return (
    <img
      className={className}
      src="/favicon.svg?v=candles-1"
      width="100"
      height="100"
      alt={decorative ? "" : "UZStock"}
      aria-hidden={decorative ? "true" : undefined}
    />
  );
}

export { BrandIcon };
