import test from "node:test";
import assert from "node:assert/strict";

import {
  calendarMeetingKind,
  calendarTitleLanguage,
  localizedCalendarTitle,
} from "../frontend/src/lib/calendarTitle.js";

test("calendar titles detect Russian and both Uzbek scripts", () => {
  assert.equal(calendarTitleLanguage("О проведении годового общего собрания акционеров"), "ru");
  assert.equal(calendarTitleLanguage("Акциядорларнинг навбатдан ташқари умумий йиғилиши"), "uz");
  assert.equal(calendarTitleLanguage("Aksiyadorlarning umumiy yig'ilishi"), "uz");
});

test("calendar meeting kind preserves the important event qualifier", () => {
  assert.equal(calendarMeetingKind("Сообщение о повторном ОСА"), "repeated");
  assert.equal(calendarMeetingKind("Navbatdan tashqari umumiy yig'ilish"), "extraordinary");
  assert.equal(calendarMeetingKind("Годовое общее собрание"), "annual");
  assert.equal(calendarMeetingKind("Хабарнома"), "general");
});

test("calendar titles follow the selected interface language", () => {
  const uzExtraordinary = { title: "Акциядорларнинг навбатдан ташқари умумий йиғилишини ўтказиш тўғрисида" };
  assert.equal(localizedCalendarTitle(uzExtraordinary, "ru"), "Внеочередное общее собрание акционеров");
  assert.equal(localizedCalendarTitle(uzExtraordinary, "en"), "Extraordinary general meeting of shareholders");
  assert.equal(localizedCalendarTitle(uzExtraordinary, "uz"), uzExtraordinary.title);
});

test("stored exact translations outrank the standardized fallback", () => {
  const item = { title: "ЭЪЛОН", title_ru: "Точное русское название" };
  assert.equal(localizedCalendarTitle(item, "ru"), "Точное русское название");
});
