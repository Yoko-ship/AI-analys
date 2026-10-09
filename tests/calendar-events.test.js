import test from "node:test";
import assert from "node:assert/strict";
import {
  addDays, addMonths, companyOptions, daysBetween, eventTitle, eventsToCsv, filterEvents, monthGrid,
  tashkentToday, upcomingEvents, viewWindow, weekRange, weekdayIndex,
} from "../frontend/src/features/news/calendarEvents.js";
import { NEWSCAL_TX } from "../frontend/src/features/news/calendarCopy.js";

const tx = NEWSCAL_TX.ru;

test("day arithmetic crosses months and years", () => {
  assert.equal(addDays("2026-12-30", 3), "2027-01-02");
  assert.equal(addDays("2026-03-01", -1), "2026-02-28");
  assert.equal(addMonths("2026-01-31", 1), "2026-02-01");
  assert.equal(daysBetween("2026-10-09", "2026-10-12"), 3);
  assert.equal(daysBetween("2026-10-09", "2026-10-02"), -7);
  assert.equal(weekdayIndex("2026-10-05"), 0); // a Monday
  assert.equal(weekdayIndex("2026-10-11"), 6);
});

test("the month grid is whole Monday-first weeks", () => {
  const g = monthGrid("2026-10-09");
  assert.equal(g.start, "2026-09-28");
  assert.equal(g.end, "2026-11-01");
  assert.equal(g.days.length % 7, 0);
  assert.equal(g.first, "2026-10-01");
  assert.equal(g.last, "2026-10-31");
});

test("each view fetches its own window", () => {
  assert.deepEqual(weekRange("2026-10-09").days.at(0), "2026-10-05");
  assert.deepEqual(viewWindow("week", "2026-10-09", {}), { start: "2026-10-05", end: "2026-10-11" });
  assert.deepEqual(viewWindow("list", "2026-10-09", { from: "2026-10-01", to: "2026-12-01" }),
    { start: "2026-10-01", end: "2026-12-01" });
});

test("today is the exchange's day, not the reader's", () => {
  // 21:30 UTC on 9 Oct is 02:30 on 10 Oct in Tashkent.
  assert.equal(tashkentToday(new Date("2026-10-09T21:30:00Z")), "2026-10-10");
});

const events = [
  { id: "a", type: "meeting", date: "2026-10-02", organization: "АО Alpha", ticker: "ALFA", title: "Внеочередное общее собрание акционеров" },
  { id: "b", type: "dividend", kind: "payment_start", date: "2026-10-12", organization: "Buxoroneftgazparmalash", ticker: "BNGP",
    tickers: ["BNGP", "BNGPP"], classes: ["preferred"],
    details: { classes: [{ class: "ordinary", amount: 242.47, start: "2026-10-01" }, { class: "preferred", amount: 300, start: "2026-10-12", end: "2026-11-24" }] } },
  { id: "c", type: "fact", date: "2026-10-15", organization: "Uzmetkombinat", ticker: "UZMK", title: "Сделка с аффилированным лицом" },
];

test("filters combine type and company, and match any ticker of the filing", () => {
  assert.deepEqual(filterEvents(events, { types: new Set(["dividend", "fact"]), company: "" }).map((e) => e.id), ["b", "c"]);
  assert.deepEqual(filterEvents(events, { types: null, company: "bngpp" }).map((e) => e.id), ["b"]);
  assert.deepEqual(filterEvents(events, { types: null, company: "alpha" }).map((e) => e.id), ["a"]);
});

test("coming up starts today", () => {
  assert.deepEqual(upcomingEvents(events, "2026-10-12").map((e) => e.id), ["b", "c"]);
});

test("a dividend step is titled by the class that pays on that day", () => {
  assert.equal(eventTitle(events[1], "ru", tx, "ru-RU"), "Начало выплаты · 300 сум");
  assert.equal(eventTitle(events[0], "ru", tx, "ru-RU"), "Внеочередное общее собрание акционеров");
  assert.equal(eventTitle({ type: "report", details: { report_form: "IFRS", year: 2026, quarter: 2 } }, "ru", tx, "ru-RU", { IFRS: "МСФО" }),
    "Отчёт МСФО за 2 кв. 2026");
});

test("company suggestions are unique and sorted", () => {
  const opts = companyOptions([...events, events[0]]);
  assert.deepEqual(opts.map((o) => o.ticker), ["ALFA", "BNGP", "UZMK"]);
});

test("the CSV has a BOM and one line per event", () => {
  const csv = eventsToCsv(events, "ru", tx, "ru-RU", {});
  assert.ok(csv.startsWith("﻿"));
  assert.equal(csv.split("\r\n").length, events.length + 1);
  assert.match(csv, /"BNGP, BNGPP"/);
});

test("a bond line of the dividend feed is named as bond income", () => {
  const ev = { type: "dividend", kind: "payment_end", classes: ["bond"],
    details: { classes: [{ class: "bond", amount: 23013.69 }] } };
  assert.equal(eventTitle(ev, "ru", tx, "ru-RU"), "Окончание выплаты дохода · 23\u00a0013,69 сум");
});
