const position = period => {
  const match = /^(\d{4})(?:Q([1-4]))?$/.exec(String(period));
  if (!match) return null;
  return match[2]
    ? {frequency: 'quarter', ordinal: Number(match[1]) * 4 + Number(match[2]) - 1}
    : {frequency: 'year', ordinal: Number(match[1])};
};

// Missing observations and absent calendar periods both break a financial line.
export function continuousPoints(values, periods) {
  const segments = [];
  let previous = null;
  periods.forEach((period, index) => {
    const value = values[period], current = position(period);
    if (!Number.isFinite(value)) {
      previous = null;
      return;
    }
    if (!previous || !current || previous.frequency !== current.frequency || current.ordinal !== previous.ordinal + 1) {
      segments.push([]);
    }
    segments.at(-1).push({period, index, value});
    previous = current;
  });
  return segments;
}
