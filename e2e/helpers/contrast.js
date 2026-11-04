// Composite translucent surfaces before measuring the rendered text contrast.
export async function textContrast(locator) {
  return locator.evaluate(el => {
    const rgba = value => value.match(/[\d.]+/g).map(Number);
    const blend = (front, back) => front.slice(0, 3).map((v, i) => v * (front[3] ?? 1) + back[i] * (1 - (front[3] ?? 1)));
    const stack = [];
    for (let node = el; node; node = node.parentElement) stack.push(rgba(getComputedStyle(node).backgroundColor));
    const background = stack.reverse().reduce((back, front) => blend(front, back), [255, 255, 255]);
    const foreground = blend(rgba(getComputedStyle(el).color), background);
    const luminance = color => color.map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
      .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
    const a = luminance(foreground), b = luminance(background);
    return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  });
}
