// The sign-up strength meter mirrors the server's password policy
// (password_policy.py) so a refusal is explained while typing, not after.
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";
import { passwordStrength, passwordHint, translateAuthError } from "../frontend/src/lib/passwordStrength.js";

describe("passwordStrength", () => {
  it("names the same refusal reasons as the server", () => {
    assert.equal(passwordStrength("1234567").reason, "too_short");
    assert.equal(passwordStrength("12345678").reason, "common");
    assert.equal(passwordStrength("Password1").reason, "common");
    assert.equal(passwordStrength("dragon12345").reason, "common");
    assert.equal(passwordStrength("ташкент2024").reason, "common"); // Cyrillic base word + digits
    assert.equal(passwordStrength("mnopqrstu").reason, "sequence");
    assert.equal(passwordStrength("q9q9q9q9q9").reason, "sequence");
    assert.equal(passwordStrength("uzstock-2026").reason, "context");
    assert.equal(passwordStrength("gapparov2005", { email: "azam.gapparov@gmail.com" }).reason, "personal");
    assert.equal(passwordStrength("azamxon1990!", { fullName: "Azamxon Gapparov" }).reason, "personal");
  });

  it("grades acceptable passwords by length and variety", () => {
    const fair = passwordStrength("Kitobxon7");
    assert.equal(fair.reason, null);
    assert.equal(fair.level, "fair");
    assert.equal(passwordStrength("mening-sevimli-mushugim-7").level, "strong");
    assert.ok(["good", "strong"].includes(passwordStrength("zR9!vK2#pL").level));
    assert.equal(passwordStrength("").level, "empty");
  });

  it("marks any refusal as weak and blocks submission", () => {
    const weak = passwordStrength("12345678");
    assert.equal(weak.level, "weak");
    assert.equal(weak.acceptable, false);
    assert.equal(passwordStrength("Kitobxon7").acceptable, true);
  });
});

describe("hints and server messages", () => {
  it("explains a refusal in the reader's language", () => {
    assert.match(passwordHint(passwordStrength("12345678"), "ru"), /слишком распространён/);
    assert.match(passwordHint(passwordStrength("12345678"), "uz"), /juda keng tarqalgan/);
    assert.match(passwordHint(passwordStrength("12345678"), "en"), /too common/);
  });

  it("translates the server's English refusals", () => {
    assert.match(translateAuthError("This password is too common — choose a less predictable one", "ru"), /распространён/);
    assert.match(translateAuthError("Too many failed sign-in attempts. Try again in 15 min or reset your password.", "ru"), /15 мин/);
    assert.equal(translateAuthError("Something else entirely", "ru"), "Something else entirely");
  });
});
