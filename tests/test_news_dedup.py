"""The feed merges the same story told twice — and never merges two real stories.

Every case here is a real pair from the served feed, audited 2026-08-11 against 200
live cards. The old dedup compared TITLES only, at 0.62, within 48h — and all of these
survived it: a retelling shares too few title words, and a story arriving in English
shares none. What two tellings of one fact do share is our own ``summary_ru``, written
in Russian by the same classifier whatever language the source wrote in. The other
side of the audit is what must NOT merge: issuer disclosures repeat identical titles
for distinct filings, and two outlets covering two same-shaped events («Узбекистан и X
обсудили проекты») overlap almost as much as a retelling does.
"""
from __future__ import annotations

import news_store as ns


def _item(id_, source_id, title, summary_ru, published_at):
    return {"id": id_, "source_id": source_id, "title": title,
            "summary_ru": summary_ru, "published_at": published_at}


def _ids(items):
    return [it["id"] for it in items]


def _dedupe(items):
    return ns._dedupe_stories(items, ns._DEDUP_SIMILARITY)


class TestTheSameStoryToldTwiceMerges:
    def test_cross_language_same_story_is_caught_by_the_summary(self) -> None:
        """uza wrote it in English, uzdaily in Russian: title overlap is ZERO, and only
        our own Russian summaries can say they are one story."""
        items = [
            _item(1141, "uzdaily", "Узбекистан и PwC Consulting обсудили сотрудничество",
                  "Узбекистан и PwC Consulting обсудили сотрудничество в геологии "
                  "и критических минералах.", "2026-08-10T16:15:00"),
            _item(1142, "uza", "Collaboration in geology: A pathway to innovative technologies",
                  "Узбекистан и PwC Consulting обсудили сотрудничество в геологии "
                  "и критических минералах.", "2026-08-11T13:06:00"),
        ]
        assert _ids(_dedupe(items)) == [1141]

    def test_a_weekend_between_the_two_tellings_is_still_inside_the_window(self) -> None:
        """kun carded the CBU reserves release 66h after spot — the old 48h window
        called that far enough apart to be two stories."""
        items = [
            _item(942, "spot",
                  "Золотовалютные резервы Узбекистана в июле выросли почти на $590 млн",
                  "Золотовалютные резервы Узбекистана выросли почти на $590 млн в июле.",
                  "2026-08-08T10:48:00"),
            _item(1137, "kun",
                  "Золотовалютные резервы Узбекистана выросли до 64,34 млрд долларов.",
                  "Золотовалютные резервы Узбекистана выросли до 64,34 млрд долларов "
                  "за счет золота и валюты.", "2026-08-11T04:45:00"),
        ]
        assert _ids(_dedupe(items)) == [942]

    def test_in_the_ambiguous_band_a_shared_figure_convicts(self) -> None:
        """kun and spot each rewrote the carbon-tax headline — overlap 0.50, below the
        clean threshold — but both quote «с 2028 года», and two different stories never
        share their figure (audited: every false pair's numbers were disjoint)."""
        items = [
            _item(569, "kun", "Для крупных предприятий может быть введён углеродный налог. "
                  "Эксперты предупредили о рисках.",
                  "С 2028 года может быть введён углеродный налог для крупных "
                  "промышленных предприятий.", "2026-07-31T11:39:00"),
            _item(496, "spot", "В Узбекистане предложили с 2028 года ввести углеродный "
                  "налог для крупных предприятий",
                  "С 2028 года предлагается ввести углеродный налог для крупных "
                  "промышленных предприятий Узбекистана.", "2026-07-30T09:45:00"),
        ]
        assert _ids(_dedupe(items)) == [569]

    def test_a_decimal_is_one_figure_not_two(self) -> None:
        """«64,34 млрд» and «$64,3 млрд» are the same 64 — and the ,34 fragment must
        not become a free-floating token that matches anything."""
        items = [
            _item(1137, "kun",
                  "Золотовалютные резервы Узбекистана выросли до 64,34 млрд долларов.",
                  "Золотовалютные резервы Узбекистана выросли до 64,34 млрд долларов "
                  "за счет золота и валюты.", "2026-08-11T04:45:00"),
            _item(1065, "uzdaily", "Международные резервы Узбекистана выросли до $64,3 млрд",
                  "Международные резервы Узбекистана в июле выросли на $589,8 млн "
                  "и достигли $64,35 млрд.", "2026-08-10T08:44:00"),
        ]
        assert _ids(_dedupe(items)) == [1137]

    def test_the_best_ranked_copy_survives_not_the_newest(self) -> None:
        """Items arrive pre-sorted best first; the later list position loses."""
        first = _item(1, "uzdaily", "Узбекистан получил тарифные льготы на грузы через порт Курык",
                      "Узбекистан получил тарифные льготы на транзит грузов через порт Курык.",
                      "2026-08-10T09:13:00")
        second = _item(2, "spot",
                       "Узбекистан получил льготы на перевозку удобрений и нефтепродуктов "
                       "через порт Курык",
                       "Узбекистан получил льготы на транзит удобрений и нефтепродуктов "
                       "через казахстанский порт Курык.", "2026-08-08T13:58:00")
        assert _ids(_dedupe([first, second])) == [1]
        assert _ids(_dedupe([second, first])) == [2]


class TestTwoRealStoriesNeverMerge:
    def test_distinct_filings_with_identical_titles_both_stay(self) -> None:
        """The same issuer files «Сделка с аффилированным лицом» week after week —
        identical wording, distinct statutory facts. Disclosures are exempt."""
        items = [
            _item(843, "openinfo_facts", '"O\'zbekneftgaz" AJ: Сделка с аффилированным лицом (3)',
                  "Эмитент заключил сделку с аффилированным лицом.", "2026-08-07T18:50:27"),
            _item(711, "openinfo_facts", '"O\'zbekneftgaz" AJ: Сделка с аффилированным лицом (8)',
                  "Заключены сделки с аффилированными лицами.", "2026-08-05T18:12:42"),
        ]
        assert _ids(_dedupe(items)) == [843, 711]

    def test_two_same_shaped_meetings_are_two_stories(self) -> None:
        """«Узбекистан и Adani…» vs «Узбекистан и KEXIM…» — the template overlaps,
        the counterparty differs. Audited at 0.42; the threshold must sit above it."""
        items = [
            _item(1068, "uzdaily", "Узбекистан и Adani Group обсудили проекты в гидроэнергетике",
                  "Узбекистан и Adani Group обсудили строительство ГЭС и ГАЭС, внедрение "
                  "технологий и инвестиционные проекты.", "2026-08-10T07:15:00"),
            _item(622, "uzdaily", "Узбекистан и KEXIM обсудили проекты на $3,6 млрд.",
                  "Узбекистан и KEXIM обсудили проекты на 3,6 млрд долларов и продолжат "
                  "сотрудничество.", "2026-08-09T04:20:00"),
        ]
        assert _ids(_dedupe(items)) == [1068, 622]

    def test_two_tax_proposals_in_one_morning_are_two_stories(self) -> None:
        """spot published a deposit-tax proposal and a carbon-tax proposal 35 minutes
        apart — same «предложили ввести налог» skeleton, band-level overlap. Their
        figures disagree (5% vs 2028), and disagreeing figures must acquit."""
        items = [
            _item(500, "spot", "В Узбекистане предложили ввести налог в 5% на проценты "
                  "по вкладам",
                  "Предлагается ввести 5% налог на проценты по банковским вкладам, что "
                  "может снизить привлекательность депозитов.", "2026-07-30T09:10:00"),
            _item(496, "spot", "В Узбекистане предложили с 2028 года ввести углеродный "
                  "налог для крупных предприятий",
                  "С 2028 года предлагается ввести углеродный налог для крупных "
                  "промышленных предприятий Узбекистана.", "2026-07-30T09:45:00"),
        ]
        assert _ids(_dedupe(items)) == [500, 496]

    def test_two_newsmakers_commenting_on_one_idea_are_two_stories(self) -> None:
        """The ЦБ and the Институт фискального анализа each spoke about the deposit-tax
        idea the same day. Audited at 0.53 — the closest non-duplicate pair we have,
        and the reason the threshold is 0.55 and not lower."""
        items = [
            _item(505, "uzdaily", "Центробанк прокомментировал идею налога на проценты по вкладам",
                  "Центробанк Узбекистана заявил, что идея налога на проценты по вкладам "
                  "носит лишь исследовательский характер.", "2026-07-30T17:13:00"),
            _item(507, "uzdaily",
                  "Институт фискального анализа разъяснил идею налога на проценты по вкладам",
                  "Институт фискального анализа подтвердил, что идея налога на проценты "
                  "по вкладам носит лишь исследовательский характер.", "2026-07-30T14:59:00"),
        ]
        assert _ids(_dedupe(items)) == [505, 507]

    def test_the_weekly_recurring_note_is_not_a_duplicate_of_last_weeks(self) -> None:
        """spot's «какие банки работают в выходные» repeats its title verbatim every
        week; the ~160h gap is what keeps each week its own card."""
        items = [
            _item(828, "spot", "Какие банки в Узбекистане будут работать в выходные дни. Список",
                  "22 банка Узбекистана будут работать в выходные для обмена валюты "
                  "и переводов.", "2026-08-07T15:08:00"),
            _item(617, "spot", "Какие банки в Узбекистане будут работать в выходные дни. Список",
                  "20 банков Узбекистана будут работать в выходные для обмена валюты "
                  "и переводов.", "2026-07-31T19:55:00"),
        ]
        assert _ids(_dedupe(items)) == [828, 617]

    def test_short_summaries_alone_cannot_merge_two_items(self) -> None:
        """A four-word summary is phrasing, not identity — below the minimum the
        summary signal is ignored and only the titles may speak."""
        items = [
            _item(1, "spot", "Ставки по автокредитам снизились",
                  "Ставки снизились в июле.", "2026-08-10T10:00:00"),
            _item(2, "kun", "Тарифы на электроэнергию пересмотрят",
                  "Ставки снизились в июле.", "2026-08-10T12:00:00"),
        ]
        assert _ids(_dedupe(items)) == [1, 2]
