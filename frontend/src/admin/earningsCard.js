import {box, label} from "./marketPoster.js";

const ink = "#201222", paper = "#fff3df", pink = "#ffc2d9";
const bold = size => `800 ${size}px "Poster Manrope"`;

export function drawEarningsCard(canvas, report, background) {
  const ctx = canvas.getContext("2d");
  ctx.drawImage(background, 0, 0, 1080, 1350);
  const shade = ctx.createLinearGradient(0, 0, 0, 1350);
  shade.addColorStop(0,"rgba(29,12,32,.18)");
  shade.addColorStop(.30,"rgba(29,12,32,.10)");
  shade.addColorStop(1,"#271126");
  ctx.fillStyle = shade;
  ctx.fillRect(0,0,1080,1350);
  label(ctx, "UZStock", 54, 86, '54px "Poster Anton"', paper);
  label(ctx, report.ticker, 1024, 82, bold(34), paper, "right");
  ctx.fillStyle = paper;
  ctx.fillRect(56,114,968,2);
  label(ctx, "ФИНАНСОВЫЕ РЕЗУЛЬТАТЫ", 56, 214, bold(25), paper);
  ctx.font = bold(96);
  const title = report.name;
  const size = Math.min(96, Math.max(50, Math.floor(96 * 960 / Math.max(ctx.measureText(title).width,1))));
  label(ctx, title, 50, 329, bold(size), paper, "left", 974);
  ctx.save();
  ctx.translate(56, 416);
  ctx.rotate(-.035);
  label(ctx, `${report.months} ${report.months === 3 ? "месяца" : "месяцев"} · ${report.year}`, 0, 0, '700 78px "Poster Caveat"', pink);
  ctx.restore();

  const rowCount = Math.ceil(report.cards.length / 2);
  const height = Math.min(276, 702 / rowCount);
  const start = 1204 - rowCount * height;
  box(ctx, 40, start, 1000, rowCount * height, 23, "rgba(31,16,34,.93)");
  report.cards.forEach((card,index) => {
    const x = 68 + (index % 2) * 497, y = start + Math.floor(index / 2) * height;
    if (index >= 2) {
      ctx.fillStyle = "#5f4259";
      ctx.fillRect(x, y, 441, 2);
    }
    label(ctx, card.label, x, y + 54, bold(25), "#f4cfdf", "left", 454);
    label(ctx, card.value, x, y + 137, bold(59), paper, "left", 455);
    if (card.change) {
      const color = card.direction > 0 ? "#a5e7c8" : card.direction < 0 ? "#ffacb2" : paper;
      label(ctx, card.change, x, y + 189, bold(30), color);
    }
  });
  if (report.mismatch) label(ctx, "Чистый результат — по строке 270*", 56, 1257, bold(25), paper);
  label(ctx, report.mismatch ? "*Есть расхождение с расчётом по строкам формы." : "Источник · отчётность эмитента на Openinfo", 56, 1305, bold(22), "#edc9dc");
  label(ctx, "UZS", 1024, 1305, bold(25), pink, "right");
}
