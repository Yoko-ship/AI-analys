// One conversion rule for quote preparation and display. Missing is not zero.
export function safeNumber(value) {
  if (value == null || (typeof value === "string" && !value.trim())) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
