/** Pixel/point quantization; financial values retain their original precision. */
export function snapPixel(value, step = 1) {
  // eslint-disable-next-line no-restricted-properties -- Pixel coordinates, not financial inputs.
  return Math.round(value / step) * step;
}

export function nearestPointIndex(fraction, count) {
  if (count <= 0) return null;
  // eslint-disable-next-line no-restricted-properties -- Selecting an array element requires an integer.
  return Math.max(0, Math.min(count - 1, Math.round(fraction * (count - 1))));
}

/** Thin date labels by their rendered footprint, preserving both end dates. */
export function fitAxisLabels(ticks, left, right, widthOf = label => Math.max(32, label.length * 6.8), gap = 8) {
  const visible = [];
  for (let i = 0; i < ticks.length; i++) {
    const tick = ticks[i];
    const width = widthOf(tick.label);
    const last = i === ticks.length - 1;
    const anchor = i === 0 ? "start" : last ? "end" : "middle";
    const offset = anchor === "start" ? 0 : anchor === "end" ? width : width / 2;
    const start = Math.max(left, Math.min(right - width, tick.x - offset));
    // Prefer the final date over a nearby interior label.
    if (last) {
      while (visible.length > 1 && start < visible.at(-1).end + gap) visible.pop();
    }
    if (visible.length && start < visible.at(-1).end + gap) continue;
    visible.push({ tick: { ...tick, x: start + offset, anchor }, end: start + width });
  }
  return visible.map(item => item.tick);
}
