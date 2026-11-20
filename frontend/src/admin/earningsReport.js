import { issuerDisplayName } from "../lib/issuerDisplayName.js";

const decimals = new Intl.NumberFormat("ru-RU", {minimumFractionDigits:1, maximumFractionDigits:1});
const integer = new Intl.NumberFormat("ru-RU", {maximumFractionDigits:2});
const quarterEnds = ["03-31", "06-30", "09-30", "12-31"];
const roman = ["I","II","III","IV"];
const scales = [[1e12, "трлн", "trln"], [1e9, "млрд", "mlrd"], [1e6, "млн", "mln"], [1e3, "тыс.", "ming"]];

function amount(value, uz = false) {
  const magnitude = Math.abs(value);
  const scale = scales.find(([factor]) => magnitude >= factor);
  const formatted = scale ? decimals.format(magnitude / scale[0]) + " " + scale[uz ? 2 : 1] : integer.format(magnitude);
  return (value < 0 ? "−" : "") + formatted;
}

function quarterIncome(period, previous) {
  const total = period?.values.net_income;
  if (total == null) return null;
  if (period.end.endsWith("-03-31")) return total;
  const previousTotal = previous?.values.net_income;
  return previousTotal == null ? null : total - previousTotal;
}

function result(value, uz, headline = false) {
  if (value === 0) return uz ? "sof natija nolga teng" : "нулевой результат";
  const sign = value < 0 ? (uz ? "zarar" : "убыток") : (uz ? "foyda" : "прибыль");
  const magnitude = amount(Math.abs(value), uz);
  const label = !headline ? sign : uz ? "sof " + sign : (value < 0 ? "чистый " : "чистая ") + sign;
  return uz ? magnitude + " so‘m " + label : label + " " + magnitude + " сумов";
}

function edition(report, uz) {
  const {name, year, months, q, current, prior, quarter, priorQuarter, mismatch} = report;
  const span = uz ? months + " oy" : months + (months === 3 ? " месяца" : " месяцев");
  const paragraphs = [];
  const profit = current.net_income;
  if (profit != null) {
    const now = result(profit, uz, true);
    paragraphs.push(uz ? `💰 ${name} — ${year}-yilning ${span}ida ${now}`
      : `💰 «${name}» за ${span} ${year} года — ${now}`);
    if (prior.net_income != null) {
      paragraphs.push(uz ? `Bir yil avval — ${result(prior.net_income,true)}.`
        : `Годом ранее — ${result(prior.net_income,false)}.`);
    }
  } else {
    paragraphs.push(uz ? `💰 ${name} — ${year}-yilning ${span}lik natijalari` : `💰 «${name}» — итоги за ${span} ${year} года`);
  }
  if (q > 1 && quarter != null) {
    let sentence = uz ? `${roman[q-1]} chorak natijasi — ${result(quarter, true)}` : `В ${roman[q-1]} квартале — ${result(quarter, false)}`;
    if (priorQuarter != null) sentence += uz ? `, bir yil avval esa ${result(priorQuarter,true)}` : `, годом ранее — ${result(priorQuarter,false)}`;
    paragraphs.push(sentence + ".");
  }
  const groups = [
    [["revenue", "Чистая выручка", "Sof tushum"], ["selling_expense", "Расходы по реализации", "Sotish xarajatlari"]],
    [["bank_borrowings_long", "Долгосрочные банковские кредиты", "Uzoq muddatli bank kreditlari"],
     ["other_borrowings_short", "Краткосрочные займы", "Qisqa muddatli qarzlar"]],
  ];
  groups.forEach((rows,index) => {
    const phrases = rows.filter(([key]) => current[key] != null).map(([key,ru,label]) => {
      const display = value => amount(key === "selling_expense" ? -value : value, uz);
      const earlier = prior[key] == null ? "" : ` (${display(prior[key])})`;
      return (uz ? label : ru) + " — " + display(current[key]) + earlier;
    });
    if (phrases.length) {
      const prefix = index ? (uz ? "💼 Chorak oxirida: " : "💼 На конец квартала: ") : "";
      const line = phrases.map((phrase, i) => index || i ? phrase[0].toLocaleLowerCase() + phrase.slice(1) : phrase).join(", ");
      paragraphs.push(prefix + line + ".");
    }
  });
  if (groups.some(rows => rows.some(([key]) => current[key] != null))) {
    paragraphs.push(uz ? "So‘mda. Qavsda — bir yil avval." : "В сумах. В скобках — годом ранее.");
  }
  if (mismatch) paragraphs.push(uz ? "270-satrdagi sof natija 240−250−260 hisobiga mos kelmaydi."
    : "Чистый результат по строке 270 расходится с расчётом 240−250−260.");
  return paragraphs.join("\n\n");
}

export function earningsReport(data, end) {
  const periods = new Map(data.periods.map(period => [period.end,period]));
  const year = Number(end.slice(0,4)), q = quarterEnds.indexOf(end.slice(5)) + 1;
  const current = periods.get(end), prior = periods.get((year-1) + end.slice(4));
  const previous = q > 1 && periods.get(year + "-" + quarterEnds[q-2]);
  const previousPrior = q > 1 && periods.get((year-1) + "-" + quarterEnds[q-2]);
  const quarter = quarterIncome(current,previous), priorQuarter = quarterIncome(prior,previousPrior);
  const used = [current, prior, quarter != null && previous, priorQuarter != null && quarter != null && previousPrior].filter(Boolean);
  const report = {
    ticker:data.ticker, name:issuerDisplayName({name:data.issuer},data.ticker), end, year, q, months:q*3,
    current:current.values, prior:prior?.values || {}, quarter, priorQuarter,
    sources:used.flatMap(period => period.sources.map(url => ({end:period.end,url}))),
    mismatch:used.some(period => period.profit_mismatch),
  };
  const values = report.current, last = report.prior;
  const rows = [
    ["Активы",values.total_assets,last.total_assets], ["Капитал",values.total_equity,last.total_equity],
    ["Нераспределённая прибыль",values.retained_earnings,last.retained_earnings], ["Чистая выручка",values.revenue,last.revenue],
    [`Результат за ${roman[q-1]} квартал`,q > 1 ? quarter : null,priorQuarter], ["Чистый результат с начала года",values.net_income,last.net_income],
  ];
  report.cards = rows.filter(([,value]) => value != null).map(([label,value,baseline]) => {
    const pct = baseline ? (value - baseline) / Math.abs(baseline) * 100 : null;
    return {label, value:amount(value), change:pct == null ? "" : (pct > 0 ? "+" : pct < 0 ? "−" : "") + decimals.format(Math.abs(pct)) + "% г/г", direction:Math.sign(pct)};
  });
  report.text = edition(report,false) + "\n\n—\n\n" + edition(report,true) + `\n\n🏦 #${report.ticker} #отчет`;
  return report;
}
