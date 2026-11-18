import qrcode from "qrcode-generator";

export function campaignQr(link) {
  const code = qrcode(0, "M");
  code.addData(link, "Byte");
  code.make();
  return code;
}

// Preview and export use the same layout and pixels. Canvas gives the PNG local fonts
// and crisp text without relying on an external rendering service.
function linesFor(ctx, value, width) {
  const lines = [];
  let line = "";
  for (const word of value.trim().split(/\s+/u)) {
    if (line && ctx.measureText(line + " " + word).width > width) {
      lines.push(line);
      line = "";
    }
    for (const ch of (line ? " " : "") + word) {
      if (ctx.measureText(line + ch).width > width) {
        lines.push(line);
        line = "";
      }
      line += ch;
    }
  }
  if (line) lines.push(line);
  return lines;
}

export function drawCampaignCard(canvas, headline, feature, edition, link, qr) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width, height = canvas.height;
  const ground = ctx.createLinearGradient(0, 0, width, height);
  ground.addColorStop(0, "#0d2234");
  ground.addColorStop(0.7, "#14263b");
  ground.addColorStop(1, "#294265");
  ctx.fillStyle = ground;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#35485c";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(64, 133); ctx.lineTo(1136, 133);
  ctx.moveTo(64, 506); ctx.lineTo(1136, 506);
  ctx.stroke();
  ctx.fillStyle = "#a5f3da";
  ctx.fillRect(64, 56, 8, 47);
  ctx.font = "bold 43px Arial, sans-serif";
  ctx.fillStyle = "#ffffff";
  ctx.fillText("UZStock", 92, 96);
  ctx.textAlign = "right";
  ctx.font = "25px Arial, sans-serif";
  ctx.fillStyle = "#cff9ed";
  ctx.fillText(feature, 1136, 92);
  ctx.textAlign = "left";
  let size = 78, lines;
  while (size >= 34) {
    ctx.font = "bold " + size + "px Arial, sans-serif";
    lines = linesFor(ctx, headline, 720);
    if (lines.length * size * 1.15 <= 310) break;
    size -= 2;
  }
  const spacing = size * 1.15;
  const top = 324 - (lines.length - 1) * spacing / 2 + size * 0.33;
  ctx.fillStyle = "#ffffff";
  lines.forEach((line, index) => ctx.fillText(line, 64, top + index * spacing));
  const modules = qr.getModuleCount();
  const unit = Math.floor(260 / (modules + 8));
  const side = unit * (modules + 8);
  const left = 1010 - Math.floor(side / 2);
  const y = 298 - Math.floor(side / 2);
  ctx.fillRect(left, y, side, side);
  ctx.fillStyle = "#0d2234";
  for (let row = 0; row < modules; row++) {
    for (let col = 0; col < modules; col++) {
      if (qr.isDark(row, col)) ctx.fillRect(left+(4+col)*unit, y+(4+row)*unit, unit, unit);
    }
  }
  ctx.textAlign = "center";
  ctx.font = "24px Arial, sans-serif";
  ctx.fillStyle = "#cff9ed";
  ctx.fillText({ru:"Открыть на UZStock", uz:"UZStock’da ochish", en:"Open on UZStock"}[edition],1010,466);
  ctx.textAlign = "left";
  ctx.font = "bold 32px Arial, sans-serif";
  ctx.fillStyle = "#a5f3da";
  const landing = new URL(link);
  ctx.fillText(landing.host + landing.pathname, 64, 573);
  ctx.textAlign = "right";
  ctx.font = "25px Arial, sans-serif";
  ctx.fillStyle = "#d1dbe5";
  ctx.fillText({ru:"Фондовый рынок Узбекистана", uz:"O‘zbekiston fond bozori", en:"Uzbekistan stock market"}[edition], 1136, 572);
  ctx.textAlign = "left";
}
