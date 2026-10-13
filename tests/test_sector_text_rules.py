"""The analysis text rules of «AI-анализ отчётности: ТЗ по секторам» (2026-10-12).

Each rule is pinned on the real filing that showed the defect in the audit of
the published analyses (ALSM, CBSK, UZTL, URTS, METQ, TGPG, UZMK, IPTB), and
on the boundary values of its threshold, so that both the cases a rule must
catch and the ones it must leave alone stay covered.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import financial_analysis.sector_report as report_module
import financial_analysis.sector_text_checks as text_checks
import financial_analysis.sector_vocabulary as vocab
from financial_analysis.sector_writer import Sentence

TODAY = date(2026, 10, 13)
FILINGS = json.loads((Path(__file__).parent / "fixtures/text_rules_filings.json").read_text(encoding="utf8"))["filings"]


def _report(ticker, lang="ru", **changes):
    filing = deepcopy(FILINGS[ticker])
    filing["snapshot"].update(changes)
    return report_module.make_report(filing["snapshot"], filing["issuer"], lang, today=TODAY, period_label=filing["period_label"])


# ── numbers ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("thousands,lang,expected", [
    (271433512.26, "ru", "271 млрд сум"),          # «Активы … → 271 433 512.26 тыс. сум»
    (1213400000, "ru", "1,21 трлн сум"),
    (15300, "ru", "15,3 млн сум"),
    (-2211687.64, "ru", "−2,21 млрд сум"),
    (999600, "ru", "1 млрд сум"),                   # rounding carries to the next scale
    (271433512.26, "uz", "271 mlrd so‘m"),
    (271433512.26, "en", "UZS 271bn"),
])
def test_amounts_are_scaled_to_three_significant_figures(thousands, lang, expected):
    assert vocab.money(thousands, lang) == expected


def test_two_amounts_share_one_scale():
    # CBSK cash: «190 894.00 → 20 096 536.00 тыс. сум (10 427.59%)» in the old text.
    assert vocab.money_pair(190894, 20096536, "ru") == ("0,2", "20,1", "млрд сум")


@pytest.mark.parametrize("value,expected", [(4.94, "4,9%"), (9.96, "10%"), (10.4, "10%"), (16.2, "16%"), (5, "5%")])
def test_percent_has_one_decimal_below_ten_and_none_above(value, expected):
    assert vocab.percent(value, "ru") == expected


@pytest.mark.parametrize("ratio,expected", [(3.4, "в 3,4 раза"), (2, "в 2 раза"), (5, "в 5 раз"), (12, "в 12 раз"), (22, "в 22 раза")])
def test_multiples_agree_with_their_number(ratio, expected):
    assert vocab.times(ratio, "ru") == expected


@pytest.mark.parametrize("share,expected", [
    (99, "подавляющая часть"), (75, "три четверти"), (80, "около четырёх пятых"), (66, "около двух третей"),
    (52, "чуть больше половины"), (47, "почти половина"), (33, "около трети"), (40, "более трети"),
    (25, "четверть"), (20, "около пятой части"), (10, "около десятой части"), (7, "небольшая доля (7%)"),
    (3, "менее 5%"),
])
def test_shares_are_named_in_words(share, expected):
    assert vocab.share_phrase(share, "ru") == expected


# ── the change tiers ────────────────────────────────────────────────────────

@pytest.mark.parametrize("pct,tier", [
    (0.9, "stable"), (1, "slight"), (4.99, "slight"), (5, "normal"), (14.9, "normal"), (15, "significant"),
    (49.9, "significant"), (50, "sharp"), (99.9, "sharp"), (100, "multiple"), (-49.9, "significant"), (-50, "multiple"),
])
def test_tier_boundaries(pct, tier):
    assert vocab.tier_of(Decimal(str(pct))) == tier


@pytest.mark.parametrize("current,previous,kwargs,kind", [
    (-2211687.64, 13475032.18, {"profit_like": True}, "to_loss"),       # ALSM «−116.41%»
    (5, -10, {"profit_like": True}, "to_profit"),
    (-5, -10, {"profit_like": True}, "loss_narrowed"),
    (-10, -5, {"profit_like": True}, "loss_widened"),
    (0, 25498036077, {}, "to_zero"),                                      # «снизился на 100%»
    (20096536, 0, {}, "from_zero"),
    (20096536, 190894, {"floor": 2000000}, "tiny_base"),                 # CBSK cash below 1% of assets
    (2000000, 190894, {"floor": 1000}, "trend"),
    (0.684, 9094.4, {}, "extreme"),                                      # «в 13 296 раз»
])
def test_movement_kinds(current, previous, kwargs, kind):
    assert vocab.classify(current, previous, **kwargs)["kind"] == kind


# ── real filings ────────────────────────────────────────────────────────────

def test_alsm_sign_change_is_told_in_words_without_a_percent():
    assert "−116.41%" not in FILINGS["ALSM"]["published_text"] and "(-116.41%)" in FILINGS["ALSM"]["published_text"]
    report = _report("ALSM")
    assert report["headline"] == ("Страховые премии остались практически неизменными, но компания завершила период "
                                  "с чистым убытком 2,21 млрд сум после прибыли 13,5 млрд сум годом ранее.")
    assert report["verdict_line"] == "Вердикт: смешанно — страховые премии на уровне прошлого года, но получен убыток."
    assert "116" not in report["text"] and "тыс. сум" not in report["text"]


def test_cbsk_cash_from_a_negligible_base_is_two_amounts():
    from financial_analysis.sector_assessment import assess_filing
    from financial_analysis.sector_evidence import collect_evidence
    from financial_analysis.sector_validation import validate_filing
    from financial_analysis.sector_writer import Paragraph, Writer
    filing = FILINGS["CBSK"]
    validated = validate_filing(filing["snapshot"], filing["issuer"], "ru", TODAY, None, filing["period_label"])
    evidence = collect_evidence(validated)
    writer = Writer(validated, evidence, assess_filing(validated, evidence))
    assert writer.change(Paragraph("ru"), "cash").text == "Денежные средства выросли с 0,2 до 20,1 млрд сум."
    text = _report("CBSK")["text"]
    assert "за счёт роста денежных средств на 19,9 млрд сум" in text
    assert "10 427" not in text and "427%" not in text


def test_uztl_profit_from_a_low_base_is_two_amounts():
    report = _report("UZTL")
    assert "чистая прибыль увеличилась с 10 до 896 млрд сум" in report["headline"]
    assert "8 850" not in report["text"] and "8850" not in report["text"]


def test_urts_never_prints_service_names():
    text = _report("URTS")["text"]
    assert "short_term_investments" not in text
    assert not re.search(r"\b[a-z]+_[a-z_]+\b", text)
    assert "краткосрочных инвестиций" in text


def test_metq_has_a_verdict_and_no_insufficient_data_beside_comparisons():
    report = _report("METQ")
    assert report["verdict"]["status"] == "mixed"
    assert report["verdict_line"] == "Вердикт: смешанно — выручка растёт, но маржа снижается."
    assert "Недостаточно" not in report["text"]


def test_tgpg_red_flag_overrides_the_axes():
    report = _report("TGPG")
    assert report["verdict"]["status"] == "attention"
    assert report["headline_tone"] == "danger"
    assert report["verdict_line"] == "Вердикт: требует внимания — убыток съел подавляющую часть капитала."


def test_uzmk_profit_lifted_by_exchange_gains_does_not_read_as_better_profitability():
    report = _report("UZMK")
    assert report["verdict"]["axes"]["profitability"] == "worse"   # operating margin 14% → 12%
    assert report["verdict"]["status"] == "mixed"


def test_bank_subject_is_the_bank():
    assert _report("IPTB")["headline"].startswith("Банк вышел в прибыль: 1,39 трлн сум после убытка 393 млрд сум годом ранее.")


@pytest.mark.parametrize("ticker", sorted(FILINGS))
@pytest.mark.parametrize("lang", ["ru", "uz", "en"])
def test_every_real_filing_passes_every_publication_check(ticker, lang):
    report = _report(ticker, lang)
    assert report["status"] == "available", report["data_quality"]
    assert report["text_checks"]["status"] == "passed", report["text_checks"]
    assert report["text_checks"]["word_count"] <= 450
    ids = [section["id"] for section in report["sections"]]
    assert ids[0] == "headline" and ids[1] == "key_points" and ids[-1] == "footnote"
    # The caveat stands once, in the footnote.
    caveat = {"ru": "примечаниями к отчётности", "uz": "hisobotga izohlar", "en": "notes to the statements"}[lang]
    assert report["text"].count(caveat) == 1 and caveat in report["footnote"]


def test_no_comparison_at_all_is_a_snapshot_on_the_date():
    report = _report("CBSK", previous_values={}, opening_values={})
    assert report["verdict"]["status"] == "no_signal"
    assert report["verdict_line"] == "Вердикт: без динамики — нет сопоставимого периода."
    assert report["text_checks"]["status"] == "passed"
    assert not any(word in report["text"] for word in ("выросл", "снизил", "сократил", "увеличил"))


# ── the publication checks catch what they must ─────────────────────────────

def _run(sentences, status="mixed", sources=None):
    pairs = [("headline", Sentence("Заголовок.", (), "headline")), ("headline", Sentence("Вердикт: смешанно — выручка растёт, но маржа снижается.", (), "verdict"))]
    pairs += [("results", s) for s in sentences]
    result = text_checks.run(pairs, lang="ru", verdict_status=status, complete=False, comparison_sources=sources)
    return {check["code"]: check["status"] for check in result["checks"]}


def test_check_number_format():
    assert _run([Sentence("Активы: 287 094 223.79 → 271 433 512.26 тыс. сум.")])["text_number_format"] == "failed"
    assert _run([Sentence("Активы снизились на 5,5% — до 271 млрд сум.")])["text_number_format"] == "passed"


def test_check_percent_from_zero_or_sign_change():
    bad = Sentence("Чистая прибыль снизилась на 116%.", ("net_income",), "to_loss", percent_shown=True)
    assert _run([bad])["no_pct_from_zero_or_sign_change"] == "failed"
    assert _run([Sentence("Деньги выросли на 10 427%.")])["no_pct_from_zero_or_sign_change"] == "failed"
    assert _run([Sentence("Доля выросла с 12% до 18%.")])["no_pct_from_zero_or_sign_change"] == "passed"


def test_check_banned_phrases_and_unearned_evaluation():
    assert _run([Sentence("Аналитический профиль: торговля.")])["no_banned_phrases"] == "failed"
    assert _run([Sentence("Статья short_term_investments выросла.")])["no_banned_phrases"] == "failed"
    assert _run([Sentence("Положение устойчивое.")])["no_banned_phrases"] == "failed"
    assert _run([Sentence("Положение устойчивое.", evaluative=True)])["no_banned_phrases"] == "passed"


def test_check_duplicates():
    one = Sentence("Текущие обязательства выросли на 7% — до 2 млрд сум.", ("current_liabilities",), "trend", "normal", "up", Decimal(7), True)
    two = Sentence("Текущие обязательства увеличились на 7% — до 2 млрд сум.", ("current_liabilities",), "trend", "normal", "up", Decimal(7), True)
    assert _run([one, one])["no_duplicate_sentences"] == "failed"
    assert _run([one, two])["no_duplicate_sentences"] == "failed"   # one line, two statements of its move
    assert _run([one])["no_duplicate_sentences"] == "passed"


@pytest.mark.parametrize("text,tier,pct,status", [
    ("Выручка резко выросла на 3%.", "slight", 3, "failed"),
    ("Выручка немного выросла на 3%.", "slight", 3, "passed"),
    ("Активы незначительно уменьшились на 2,9%.", "slight", -2.9, "passed"),   # «незначительно» is not «значительно»
    ("Выручка значительно выросла на 3%.", "significant", 3, "failed"),
])
def test_check_verb_matches_magnitude(text, tier, pct, status):
    sentence = Sentence(text, ("revenue",), "trend", tier, "up" if pct > 0 else "down", Decimal(str(pct)), True)
    assert _run([sentence])["verb_matches_magnitude"] == status


def test_check_sentence_length():
    long = Sentence(" ".join(["слово"] * 31) + ".")
    assert _run([long])["sentence_length"] == "failed"
    assert _run([Sentence(" ".join(["слово"] * 30) + ".")])["sentence_length"] == "passed"


def test_check_verdict_has_reason_and_no_comparison_without_dynamics():
    moving = Sentence("Выручка выросла на 9% — до 1 млрд сум.", ("revenue",), "trend", "normal", "up", Decimal(9), True)
    assert _run([moving], status="no_signal")["verdict_has_reason"] == "failed"
    assert _run([moving], status="mixed")["verdict_has_reason"] == "passed"


def test_check_comparison_fallback_used():
    assert _run([], sources={"previous_available": True, "previous_used": False})["comparison_fallback_used"] == "failed"
    assert _run([], sources={"previous_available": True, "previous_used": True})["comparison_fallback_used"] == "passed"
    assert _run([], sources={"previous_available": False, "previous_used": False})["comparison_fallback_used"] == "passed"


def test_a_failed_check_withholds_the_text_and_shows_the_snapshot(monkeypatch):
    def failing(*args, **kwargs):
        return {"status": "failed", "word_count": 0, "checks": [{"code": "sentence_length", "status": "failed", "failures": ["x"]}]}
    monkeypatch.setattr(text_checks, "run", failing)
    report = _report("CBSK")
    assert report["status"] == "quality_blocked"
    assert report["headline"].startswith("Срез на 30.06.2026: выручка за период — 50,9 млрд сум")
    assert report["headline"].endswith("Анализ не публикуется: текст анализа не прошёл автоматическую проверку.")
    assert report["availability"]["reason_text"] == "текст анализа не прошёл автоматическую проверку"


def test_unbalanced_filing_names_the_gap():
    filing = deepcopy(FILINGS["CBSK"]["snapshot"])
    filing["current_values"]["total_assets"] = filing["current_values"]["total_assets"] + 3000000
    report = report_module.make_report(filing, FILINGS["CBSK"]["issuer"], "ru", today=TODAY, period_label="I полугодие 2026 года")
    assert report["status"] == "quality_blocked"
    assert report["headline"].endswith("Анализ не публикуется: баланс в отчёте не сходится на 3 млрд сум.")
    assert "выручка за период — 50,9 млрд сум" in report["headline"]
    assert "активы —" not in report["headline"]   # the failed balance is not shown


@pytest.mark.parametrize("ticker", sorted(FILINGS))
def test_every_report_can_be_published_as_json(ticker):
    # TGPG's red flag carried a Decimal share and its publication failed with
    # a 500; a published report must serialise without a custom encoder.
    json.dumps(_report(ticker))
