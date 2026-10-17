import test from "node:test";
import assert from "node:assert/strict";
import {
  TAB_KEYS, commandText, parseCommand, suggestCommands, tickerIndex,
} from "../frontend/src/lib/terminalCommands.js";

const companies = [
  { ticker: "SQBN", tickers: ["SQBN"], company_name: "Узпромстройбанк" },
  { ticker: "AGBA", tickers: ["AGBA"], company_name: "Агробанк" },
  { ticker: "UZIN", tickers: ["UZIN", "UZINP"], company_name: "Узбекинвест" },
  { ticker: "KVTS", tickers: ["KVTS"], company_name: "Кварц" },
];
const index = tickerIndex(companies);

test("a ticker and a function open that screen, in either order", () => {
  assert.deepEqual(parseCommand("SQBN PL", index), { ticker: "SQBN", func: "PL", market: null, form: null, unknown: [] });
  assert.deepEqual(parseCommand("pl sqbn", index).ticker, "SQBN");
});

test("Bloomberg aliases and the standard are understood", () => {
  const fa = parseCommand("SQBN FA", index);
  assert.equal(fa.func, "PL");
  assert.equal(parseCommand("AGBA DES", index).func, "SUM");
  assert.equal(parseCommand("AGBA MSFO PL", index).form, "MSFO");
  assert.equal(parseCommand("AGBA IFRS", index).form, "MSFO");
  assert.equal(parseCommand("AGBA МСФО", index).form, "MSFO");
  assert.equal(parseCommand("AGBA нсбу", index).form, "NSBU");
});

test("any ticker of an issuer opens the issuer", () => {
  assert.equal(parseCommand("UZINP BS", index).ticker, "UZIN");
});

test("market functions need no ticker", () => {
  const help = parseCommand("help", index);
  assert.equal(help.market, "HELP");
  assert.equal(help.ticker, null);
});

test("words that match nothing are reported, the rest still parses", () => {
  const parsed = parseCommand("SQBX PL", index);
  assert.deepEqual(parsed.unknown, ["SQBX"]);
  assert.equal(parsed.func, "PL");
  assert.deepEqual(parseCommand("   ", index).unknown, []);
});

test("number keys map to the first ten issuer functions", () => {
  assert.deepEqual(TAB_KEYS.map((t) => t.key), ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]);
  assert.equal(TAB_KEYS[0].code, "SUM");
  assert.equal(TAB_KEYS[9].code, "DQ");
});

test("suggestions complete tickers first, by prefix and by company name", () => {
  const byPrefix = suggestCommands("sq", companies);
  assert.equal(byPrefix[0].code, "SQBN");
  assert.equal(byPrefix[0].value, "SQBN ");
  const byName = suggestCommands("агро", companies);
  assert.equal(byName[0].code, "AGBA");
});

test("after a ticker, suggestions are functions and keep what was typed", () => {
  const list = suggestCommands("SQBN B", companies);
  assert.deepEqual(list.map((s) => s.code), ["BS"]);
  assert.equal(list[0].value, "SQBN BS ");
  assert.ok(suggestCommands("SQBN ", companies).some((s) => s.code === "DQ"));
});

test("the canonical command text drops the default standard", () => {
  assert.equal(commandText({ ticker: "SQBN", func: "PL", form: "NSBU" }), "SQBN PL");
  assert.equal(commandText({ ticker: "AGBA", func: "BS", form: "MSFO" }), "AGBA MSFO BS");
  assert.equal(commandText({ market: "EQS" }), "EQS");
});
