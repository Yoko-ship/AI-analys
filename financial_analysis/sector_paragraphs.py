"""Render bank and general sector narratives from traceable facts."""
from __future__ import annotations
from decimal import Decimal
from financial_analysis.sector_models import ReportEvidence
from financial_analysis.sector_models import SectorAssessment
from financial_analysis.sector_models import ValidatedFiling
import financial_analysis.sector_language as financial_analysis_sector_language
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_templates as financial_analysis_sector_templates
import re


class SectorLanguage:
    def __init__(self, filing: ValidatedFiling, evidence: ReportEvidence, assessment: SectorAssessment):
        self.assessment = assessment
        self.narrative_blocks = {"performance": [], "position": []}
        self.nsbu_name = financial_analysis_sector_language.tr(filing.lang, "НСБУ", "BHMS", "NSBU")
        self.filing = filing
        self.evidence = evidence
        self.display_divisor = financial_analysis_sector_numbers.decimal(filing.snapshot.get("display_divisor")) or Decimal(1)
        self.money_unit = financial_analysis_sector_language.tr(filing.lang, "млн сум", "mln so‘m", "million UZS") if self.display_divisor == 1000 else financial_analysis_sector_language.tr(filing.lang, "тыс. сум", "ming so‘m", "thousand UZS")

    def display_money(self, value):
        parsed = financial_analysis_sector_numbers.decimal(value)
        return financial_analysis_sector_language.format_number(parsed / self.display_divisor) if parsed is not None else "—"

    def metric_label(self, key):
        if self.filing.template == "insurance" and key == "revenue":
            return financial_analysis_sector_language.tr(self.filing.lang, "Чистая выручка от страховых услуг", "Sug‘urta xizmatlaridan sof tushum", "Net insurance-service revenue")
        return financial_analysis_sector_language.label(key, self.filing.lang)

    def fact_sentence(self, key, comparison=True):
        fact = self.evidence.by_code.get(key)
        if not fact:
            return None
        text = f"{self.metric_label(key)}: {self.display_money(fact['value'])} {self.money_unit}"
        if comparison and fact["previous"] is not None:
            text = f"{self.metric_label(key)}: {self.display_money(fact['previous'])} → {self.display_money(fact['value'])} {self.money_unit}"
            if fact["change_pct"] is not None:
                text += f" ({financial_analysis_sector_language.format_number(fact['change_pct'])}%)"
        return text

    def vertical_narrative(self, asset_keys, heading, bank_funding=False, exchange_funding=False):
        """Explain the balance mix as a comparison, not a list of percentages.

        This follows the useful part of a Task-1 style commentary: lead with the
        dominant feature, compare both dates in percentage points, then explain
        the economic implication without inventing an undisclosed cause.
        """
        assets_fact = self.evidence.by_code.get("total_assets") or {}
        assets_now = financial_analysis_sector_numbers.decimal(assets_fact.get("value"))
        assets_before = financial_analysis_sector_numbers.decimal(assets_fact.get("previous"))
        if not assets_now or assets_now <= 0:
            return heading + financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно данных для расчёта структуры.", "Tarkibni hisoblash uchun ma’lumot yetarli emas.", "There is insufficient data to calculate the structure.")

        rows = []
        for key in dict.fromkeys(asset_keys):
            fact = self.evidence.by_code.get(key) or {}
            current = financial_analysis_sector_numbers.ratio(fact.get("value"), assets_now, True)
            previous_share = financial_analysis_sector_numbers.ratio(fact.get("previous"), assets_before, True)
            if current is None:
                continue
            rows.append({"key": key, "current": current, "previous": previous_share,
                         "shift": financial_analysis_sector_numbers.difference(current, previous_share)})
        if not rows:
            return heading + financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно данных для расчёта структуры.", "Tarkibni hisoblash uchun ma’lumot yetarli emas.", "There is insufficient data to calculate the structure.")

        dominant = max(rows, key=lambda item: item["current"])
        first = financial_analysis_sector_language.tr(
            self.filing.lang,
            f"В структуре активов доминирует статья «{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)}» — {financial_analysis_sector_language.format_number(dominant['current'])}% итога баланса.",
            f"Aktivlar tarkibida «{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)}» ustun — balans jami aktivlarining {financial_analysis_sector_language.format_number(dominant['current'])}%i.",
            f"{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)} dominates the asset mix at {financial_analysis_sector_language.format_number(dominant['current'])}% of total assets.",
        )
        if dominant["previous"] is not None:
            first += " " + financial_analysis_sector_language.tr(
                self.filing.lang,
                f"На начало периода доля составляла {financial_analysis_sector_language.format_number(dominant['previous'])}%, то есть изменилась на {financial_analysis_sector_language.format_number(dominant['shift'])} п.п.",
                f"Davr boshida ulush {financial_analysis_sector_language.format_number(dominant['previous'])}% edi, ya’ni {financial_analysis_sector_language.format_number(dominant['shift'])} foiz punktga o‘zgardi.",
                f"At the start of the period it was {financial_analysis_sector_language.format_number(dominant['previous'])}%, a change of {financial_analysis_sector_language.format_number(dominant['shift'])} percentage points.",
            )

        comparable = sorted((row for row in rows if row["shift"] is not None),
                            key=lambda item: abs(item["shift"]), reverse=True)
        movement = ""
        if comparable:
            parts = []
            for row in comparable[:2]:
                direction = financial_analysis_sector_language.tr(self.filing.lang, "выросла", "oshdi", "rose") if row["shift"] >= 0 else financial_analysis_sector_language.tr(self.filing.lang, "снизилась", "kamaydi", "fell")
                parts.append(financial_analysis_sector_language.tr(
                    self.filing.lang,
                    f"доля «{financial_analysis_sector_language.label(row['key'], self.filing.lang)}» {direction} с {financial_analysis_sector_language.format_number(row['previous'])}% до {financial_analysis_sector_language.format_number(row['current'])}% ({financial_analysis_sector_language.format_number(abs(row['shift']))} п.п.)",
                    f"«{financial_analysis_sector_language.label(row['key'], self.filing.lang)}» ulushi {financial_analysis_sector_language.format_number(row['previous'])}%dan {financial_analysis_sector_language.format_number(row['current'])}%gacha {direction} ({financial_analysis_sector_language.format_number(abs(row['shift']))} foiz punkt)",
                    f"{financial_analysis_sector_language.label(row['key'], self.filing.lang)} {direction} from {financial_analysis_sector_language.format_number(row['previous'])}% to {financial_analysis_sector_language.format_number(row['current'])}% ({financial_analysis_sector_language.format_number(abs(row['shift']))} pp)",
                ))
            movement = financial_analysis_sector_language.tr(self.filing.lang, "Главные структурные изменения: ", "Asosiy tarkibiy o‘zgarishlar: ", "The main structural changes were: ") + "; ".join(parts) + "."

        if bank_funding:
            # Bank wording from the customer's formulation library: concentration
            # is described, never judged, and each share shift is stated plainly.
            if dominant["current"] >= 50:
                first = financial_analysis_sector_language.tr(
                    self.filing.lang,
                    f"Основную часть активов составляет «{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)}» — {financial_analysis_sector_language.format_number(dominant['current'])}%. Такая структура указывает на значительную концентрацию баланса в этом направлении.",
                    f"Aktivlarning asosiy qismini «{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)}» tashkil etadi — {financial_analysis_sector_language.format_number(dominant['current'])}%. Bunday tuzilma balansning shu yo‘nalishda sezilarli darajada jamlanganini ko‘rsatadi.",
                    f"Most of the assets are «{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)}» — {financial_analysis_sector_language.format_number(dominant['current'])}%. This structure indicates a significant concentration of the balance sheet in this area.",
                )
            else:
                first = financial_analysis_sector_language.tr(
                    self.filing.lang,
                    f"Крупнейшая раскрытая статья активов — «{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)}»: {financial_analysis_sector_language.format_number(dominant['current'])}%.",
                    f"Oshkor qilingan eng yirik aktiv moddasi — «{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)}»: {financial_analysis_sector_language.format_number(dominant['current'])}%.",
                    f"The largest disclosed asset item is «{financial_analysis_sector_language.label(dominant['key'], self.filing.lang)}»: {financial_analysis_sector_language.format_number(dominant['current'])}%.",
                )
            shifts = []
            for row in comparable[:2]:
                if not row["shift"]:
                    continue
                up = row["shift"] > 0
                shifts.append(financial_analysis_sector_language.tr(
                    self.filing.lang,
                    f"Доля «{financial_analysis_sector_language.label(row['key'], self.filing.lang)}» в активах {'выросла' if up else 'снизилась'} с {financial_analysis_sector_language.format_number(row['previous'])}% до {financial_analysis_sector_language.format_number(row['current'])}%, что отражает изменение структуры активов.",
                    f"«{financial_analysis_sector_language.label(row['key'], self.filing.lang)}»ning aktivlardagi ulushi {financial_analysis_sector_language.format_number(row['previous'])}%dan {financial_analysis_sector_language.format_number(row['current'])}%gacha {'oshdi' if up else 'kamaydi'}, bu aktivlar tuzilmasi o‘zgarganini aks ettiradi.",
                    f"The share of «{financial_analysis_sector_language.label(row['key'], self.filing.lang)}» in assets {'rose' if up else 'fell'} from {financial_analysis_sector_language.format_number(row['previous'])}% to {financial_analysis_sector_language.format_number(row['current'])}%, reflecting a change in the asset structure.",
                ))
            movement = " ".join(shifts)

        rose = dominant["shift"] is None or dominant["shift"] >= 0
        implications = {
            "fixed_assets": financial_analysis_sector_language.tr(self.filing.lang, "Высокая доля основных средств подтверждает капиталоёмкость бизнеса: значительная часть ресурсов связана в производственной базе.", "Asosiy vositalarning yuqori ulushi biznes kapital talabchanligini ko‘rsatadi: resurslarning katta qismi ishlab chiqarish bazasiga bog‘langan.", "The high fixed-asset share confirms a capital-intensive model, with substantial resources tied to the operating base."),
            "construction_in_progress": financial_analysis_sector_language.tr(self.filing.lang, "Высокая доля незавершённых вложений показывает, что значительная часть активов ещё не введена в эксплуатацию; отдачу от этих инвестиций нужно проверять после запуска объектов.", "Tugallanmagan investitsiyalarning yuqori ulushi aktivlarning katta qismi hali ishga tushirilmaganini ko‘rsatadi; bu investitsiyalar qaytimi obyektlar ishga tushgach tekshirilishi kerak.", "A high construction-in-progress share means a substantial part of assets is not yet operational; returns should be assessed after the projects are commissioned."),
            "inventories": financial_analysis_sector_language.tr(self.filing.lang, "Рост доли запасов означает, что больше средств связано в оборотном капитале; важно сопоставить это с динамикой выручки.", "Zaxiralar ulushining o‘sishi aylanma kapitalga ko‘proq mablag‘ bog‘langanini anglatadi; buni tushum dinamikasi bilan solishtirish kerak.", "A rising inventory share ties up more working capital and should be assessed against revenue growth.") if rose else financial_analysis_sector_language.tr(self.filing.lang, "Снижение доли запасов высвобождает оборотный капитал, но без примечаний нельзя отличить ускорение оборачиваемости от сокращения деятельности.", "Zaxiralar ulushining pasayishi aylanma kapitalni bo‘shatadi, ammo izohlarsiz tezroq aylanishni faoliyat qisqarishidan ajratib bo‘lmaydi.", "A lower inventory share releases working capital, although the notes are needed to distinguish faster turnover from weaker activity."),
            "receivables": financial_analysis_sector_language.tr(self.filing.lang, "Рост доли дебиторской задолженности усиливает зависимость ликвидности от своевременных расчётов покупателей.", "Debitorlik ulushining o‘sishi likvidlikni xaridorlarning o‘z vaqtida to‘lovlariga ko‘proq bog‘laydi.", "A rising receivables share makes liquidity more dependent on timely customer payments.") if rose else financial_analysis_sector_language.tr(self.filing.lang, "Снижение доли дебиторской задолженности уменьшает объём средств, связанных в расчётах с покупателями, и потенциально поддерживает ликвидность.", "Debitorlik ulushining pasayishi xaridorlar bilan hisob-kitoblarga bog‘langan mablag‘larni kamaytirib, likvidlikni qo‘llab-quvvatlashi mumkin.", "A lower receivables share reduces funds tied up in customer settlements and may support liquidity."),
            "cash": financial_analysis_sector_language.tr(self.filing.lang, "Рост доли денег усиливает немедленный запас ликвидности.", "Pul ulushining o‘sishi tezkor likvidlik zaxirasini kuchaytiradi.", "A rising cash share strengthens the immediate liquidity buffer.") if rose else financial_analysis_sector_language.tr(self.filing.lang, "Снижение доли денег ослабляет немедленный запас ликвидности и требует сопоставления с краткосрочными обязательствами.", "Pul ulushining pasayishi tezkor likvidlik zaxirasini susaytiradi va joriy majburiyatlar bilan solishtirishni talab qiladi.", "A lower cash share weakens the immediate liquidity buffer and should be assessed against current liabilities."),
            "loan_portfolio": financial_analysis_sector_language.tr(self.filing.lang, "Доминирование кредитного портфеля подтверждает кредитную специализацию банка и концентрацию активов на кредитном риске.", "Kredit portfelining ustunligi bankning kreditlashga ixtisoslashganini va aktivlar kredit riskida jamlanganini ko‘rsatadi.", "The dominant loan portfolio confirms the bank’s lending focus and concentration of assets in credit risk."),
        }
        meaning = implications.get(dominant["key"], financial_analysis_sector_language.tr(self.filing.lang, "Такое соотношение показывает, где сосредоточена основная часть ресурсов компании.", "Bu nisbat kompaniya resurslarining asosiy qismi qayerda jamlanganini ko‘rsatadi.", "This mix shows where most of the company’s resources are concentrated."))
        if bank_funding:
            meaning = ""
        if exchange_funding and dominant["key"] in {"cash", "client_cash", "own_cash"}:
            meaning = financial_analysis_sector_language.tr(
                self.filing.lang,
                "Высокая денежная доля характерна для расчётной инфраструктуры биржи, но её нельзя считать свободной ликвидностью без раздельного раскрытия собственных и клиентских средств.",
                "Pul ulushining yuqoriligi birjaning hisob-kitob infratuzilmasiga xos, ammo o‘z va mijoz mablag‘lari alohida oshkor qilinmasa, uni erkin likvidlik deb hisoblab bo‘lmaydi.",
                "A high cash share is consistent with an exchange settlement model, but it cannot be treated as freely available liquidity without a split between own and client funds.",
            )
        equity_share = financial_analysis_sector_numbers.ratio((self.evidence.by_code.get("total_equity") or {}).get("value"), assets_now, True)
        liability_share = financial_analysis_sector_numbers.ratio((self.evidence.by_code.get("total_liabilities") or {}).get("value"), assets_now, True)
        funding = ""
        if equity_share is not None and liability_share is not None:
            if bank_funding:
                funding = financial_analysis_sector_language.tr(
                    self.filing.lang,
                    f"Капитал составляет {financial_analysis_sector_language.format_number(equity_share)}% активов, обязательства — {financial_analysis_sector_language.format_number(liability_share)}%. Для банка высокая доля обязательств является частью операционной модели, включая депозиты и заимствования, и сама по себе не означает чрезмерную зависимость от внешнего финансирования.",
                    f"Kapital aktivlarning {financial_analysis_sector_language.format_number(equity_share)}%ini, majburiyatlar esa {financial_analysis_sector_language.format_number(liability_share)}%ini tashkil etadi. Bankda majburiyatlarning yuqori ulushi depozitlar va qarzlarni o‘z ichiga olgan operatsion modelning bir qismi bo‘lib, o‘z-o‘zidan tashqi moliyalashtirishga ortiqcha qaramlikni anglatmaydi.",
                    f"Equity represents {financial_analysis_sector_language.format_number(equity_share)}% of assets and liabilities {financial_analysis_sector_language.format_number(liability_share)}%. For a bank, a high liability share is inherent to the operating model, including deposits and borrowings, and is not by itself evidence of excessive external-funding dependence.",
                )
            elif exchange_funding:
                funding = financial_analysis_sector_language.tr(
                    self.filing.lang,
                    f"Капитал составляет {financial_analysis_sector_language.format_number(equity_share)}% активов, обязательства — {financial_analysis_sector_language.format_number(liability_share)}%. Для биржи обязательства могут включать клиентские расчёты и обеспечительные средства, поэтому эту долю нельзя автоматически трактовать как корпоративный долг.",
                    f"Kapital aktivlarning {financial_analysis_sector_language.format_number(equity_share)}%ini, majburiyatlar esa {financial_analysis_sector_language.format_number(liability_share)}%ini tashkil etadi. Birjada majburiyatlar mijozlar hisob-kitoblari va ta’minot mablag‘larini o‘z ichiga olishi mumkin, shuning uchun bu ulushni avtomatik ravishda korporativ qarz deb talqin qilib bo‘lmaydi.",
                    f"Equity represents {financial_analysis_sector_language.format_number(equity_share)}% of assets and liabilities {financial_analysis_sector_language.format_number(liability_share)}%. For an exchange, liabilities may include client settlements and collateral, so the ratio cannot automatically be interpreted as corporate debt.",
                )
            else:
                funding = financial_analysis_sector_language.tr(
                    self.filing.lang,
                    f"Источники финансирования распределены так: собственный капитал покрывает {financial_analysis_sector_language.format_number(equity_share)}% активов, обязательства — {financial_analysis_sector_language.format_number(liability_share)}%; это прямо показывает уровень финансовой автономии и зависимость от внешнего фондирования.",
                    f"Moliyalashtirish manbalari quyidagicha: kapital aktivlarning {financial_analysis_sector_language.format_number(equity_share)}%ini, majburiyatlar esa {financial_analysis_sector_language.format_number(liability_share)}%ini qoplaydi; bu moliyaviy mustaqillik va tashqi mablag‘larga bog‘liqlik darajasini ko‘rsatadi.",
                    f"Funding is split between equity covering {financial_analysis_sector_language.format_number(equity_share)}% of assets and liabilities covering {financial_analysis_sector_language.format_number(liability_share)}%, directly indicating financial autonomy and reliance on external funding.",
                )
        return " ".join(part.strip() for part in (heading, first, movement, meaning, funding, financial_analysis_sector_language.tr(
            self.filing.lang,
            "Точную операционную причину изменения можно подтвердить только примечаниями к отчётности.",
            "O‘zgarishning aniq operatsion sababini faqat hisobot izohlari tasdiqlashi mumkin.",
            "The exact operating cause can only be confirmed from the notes to the financial statements.",
        )) if part and part.strip())

    def moved(self, key):
        return (self.evidence.by_code.get(key) or {}).get("change_pct")

    def fact_now(self, key):
        return financial_analysis_sector_numbers.decimal((self.evidence.by_code.get(key) or {}).get("value"))

    def fact_before(self, key):
        return financial_analysis_sector_numbers.decimal((self.evidence.by_code.get(key) or {}).get("previous"))

    def amount_text(self, amount):
        return f"{self.display_money(amount)} {self.money_unit}"

    def pct_of(self, numerator, denominator):
        return financial_analysis_sector_numbers.ratio(numerator, denominator, True)

    def pct_str(self, item):
        return f"{financial_analysis_sector_language.format_number(item)}%"

    def sector_conclusion(self):
        """Close with the library's positive / mixed / negative wording."""
        insurance = self.filing.template == "insurance"
        names = {
            "revenue": financial_analysis_sector_language.tr(self.filing.lang, "чистая выручка от страховых услуг", "sug‘urta xizmatlaridan sof tushum", "net insurance-service revenue") if insurance else financial_analysis_sector_language.tr(self.filing.lang, "раскрытые доходы", "oshkor qilingan daromadlar", "disclosed income"),
            "net_income": financial_analysis_sector_language.tr(self.filing.lang, "чистая прибыль", "sof foyda", "net profit"),
            "operating_income": financial_analysis_sector_language.tr(self.filing.lang, "операционный результат", "operatsion natija", "operating result"),
            "total_equity": financial_analysis_sector_language.tr(self.filing.lang, "капитал", "kapital", "equity"),
            "total_liabilities": financial_analysis_sector_language.tr(self.filing.lang, "соотношение обязательств и капитала", "majburiyatlar va kapital nisbati", "liabilities relative to equity"),
            "receivables": financial_analysis_sector_language.tr(self.filing.lang, "дебиторская задолженность", "debitorlik qarzi", "receivables"),
            "inventories": financial_analysis_sector_language.tr(self.filing.lang, "запасы", "zaxiralar", "inventories"),
            "insurance_claims": financial_analysis_sector_language.tr(self.filing.lang, "страховые выплаты", "sug‘urta to‘lovlari", "insurance claims"),
            "profit_quality": financial_analysis_sector_language.tr(self.filing.lang, "качество прибыли", "foyda sifati", "earnings quality"),
        }
        pressure = {
            "net_income": financial_analysis_sector_language.tr(self.filing.lang, "прибыльность", "rentabellikka", "profitability"),
            "operating_income": financial_analysis_sector_language.tr(self.filing.lang, "результат основной деятельности", "asosiy faoliyat natijasiga", "the core operating result"),
            "total_liabilities": financial_analysis_sector_language.tr(self.filing.lang, "структуру баланса", "balans tuzilmasiga", "the balance-sheet structure"),
            "receivables": financial_analysis_sector_language.tr(self.filing.lang, "структуру активов", "aktivlar tuzilmasiga", "the asset structure"),
            "inventories": financial_analysis_sector_language.tr(self.filing.lang, "структуру активов", "aktivlar tuzilmasiga", "the asset structure"),
            "insurance_claims": financial_analysis_sector_language.tr(self.filing.lang, "результат услуг", "xizmatlar natijasiga", "the service result"),
            "profit_quality": financial_analysis_sector_language.tr(self.filing.lang, "прибыльность", "rentabellikka", "profitability"),
        }

        def subject(item):
            code = item["code"]
            if code == "profit_quality":
                return "profit_quality"
            return item["metric_code"]

        def seen(items):
            unique = []
            for item in items:
                key = subject(item)
                if key in names and key not in unique:
                    unique.append(key)
            return unique

        good, bad = seen(self.assessment.positives), seen(self.assessment.negatives)
        parts = []
        if self.assessment.verdict_status == "positive" and good:
            parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"За период компания увеличила показатель «{names[good[0]]}».", f"Davr mobaynida kompaniya «{names[good[0]]}» ko‘rsatkichini oshirdi.", f"Over the period the company increased «{names[good[0]]}»."))
            if len(good) > 1:
                parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"Одновременно показатель «{names[good[1]]}» изменился в благоприятном направлении.", f"Bir vaqtning o‘zida «{names[good[1]]}» ko‘rsatkichi ijobiy tomonga o‘zgardi.", f"At the same time «{names[good[1]]}» moved in a favourable direction."))
            parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"В целом динамика выглядит положительной в пределах доступных данных {self.nsbu_name}. Для подтверждения устойчивости тенденции необходимы данные за более длительный период.", f"Umuman olganda, dinamika mavjud {self.nsbu_name} ma’lumotlari doirasida ijobiy ko‘rinadi. Tendensiya barqarorligini tasdiqlash uchun uzoqroq davr ma’lumotlari kerak.", f"Overall, the trend looks positive within the available {self.nsbu_name} data. Data for a longer period are needed to confirm that the trend is sustainable."))
        elif self.assessment.verdict_status == "mixed" and good and bad:
            parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"Картина неоднородная: показатель «{names[good[0]]}» улучшился, тогда как показатель «{names[bad[0]]}» ухудшился.", f"Manzara bir xil emas: «{names[good[0]]}» ko‘rsatkichi yaxshilandi, «{names[bad[0]]}» ko‘rsatkichi esa yomonlashdi.", f"The picture is uneven: «{names[good[0]]}» improved, while «{names[bad[0]]}» worsened."))
            parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"Ключевой вопрос для дальнейшего наблюдения — дальнейшая динамика показателя «{names[bad[0]]}».", f"Keyingi kuzatuv uchun asosiy savol — «{names[bad[0]]}» ko‘rsatkichining keyingi dinamikasi.", f"The key question to monitor is the further movement of «{names[bad[0]]}»."))
        elif self.assessment.verdict_status == "negative" and bad:
            target = pressure.get(bad[0], financial_analysis_sector_language.tr(self.filing.lang, "прибыльность", "rentabellikka", "profitability"))
            parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"За период ухудшился показатель «{names[bad[0]]}», что оказало давление на {target}.", f"Davr mobaynida «{names[bad[0]]}» ko‘rsatkichi yomonlashdi va bu {target} bosim o‘tkazdi.", f"Over the period «{names[bad[0]]}» worsened, which put pressure on {target}."))
            parts.append(financial_analysis_sector_language.tr(self.filing.lang, "Наблюдаемая динамика требует внимания, но не позволяет самостоятельно заключить о нарушении нормативов или неплатёжеспособности.", "Kuzatilayotgan dinamika e’tibor talab qiladi, ammo undan mustaqil ravishda me’yorlar buzilgani yoki to‘lovga qobiliyatsizlik haqida xulosa chiqarib bo‘lmaydi.", "The observed trend requires attention, but on its own it does not support a conclusion of a breach of regulatory standards or insolvency."))
        else:
            comparable = self.filing.snapshot.get("previous_comparable_period") or financial_analysis_sector_language.tr(self.filing.lang, "прошлый год", "o‘tgan yil", "the previous year")
            parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"Сравнение ограничено отсутствием сопоставимых данных за {comparable}.", f"Taqqoslash {comparable} uchun taqqoslanadigan ma’lumotlar yo‘qligi bilan cheklangan.", f"The comparison is limited by the absence of comparable data for {comparable}."))
        parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"Вывод основан на доступных формах {self.nsbu_name} за {self.filing.period_text} и не заменяет оценку по регуляторной отчётности.", f"Xulosa {self.filing.period_text} uchun mavjud {self.nsbu_name} shakllariga asoslangan va regulyativ hisobot bo‘yicha baholashni almashtirmaydi.", f"The conclusion is based on the available {self.nsbu_name} forms for {self.filing.period_text} and does not replace an assessment based on regulatory reporting."))
        return " ".join(parts)

    def bank_analysis_paragraphs(self, headline):
        """Bank narrative in the library's wording, from verified lines only."""
        interest_income = self.fact_now("interest_income")
        noninterest_income = self.fact_now("noninterest_income")
        interest_expenses = self.fact_now("interest_expenses")
        noninterest_expenses = self.fact_now("noninterest_expenses")
        operating_expenses = self.fact_now("operating_expenses")
        net_revenue_before_opex = self.fact_now("net_revenue_before_operating_expenses")
        profit_before_tax = self.fact_now("profit_before_tax")
        net_income = self.fact_now("net_income")
        disclosed_tax = self.fact_now("tax")
        total_income = financial_analysis_sector_numbers.total(interest_income, noninterest_income)
        total_expenses = financial_analysis_sector_numbers.total(interest_expenses, noninterest_expenses, operating_expenses)
        net_interest_income = financial_analysis_sector_numbers.difference(interest_income, interest_expenses)
        interest_expense_share = self.pct_of(interest_expenses, interest_income)
        cost_to_income = self.pct_of(operating_expenses, net_revenue_before_opex)
        tax_amount = disclosed_tax
        if tax_amount is None and profit_before_tax is not None and net_income is not None:
            tax_amount = profit_before_tax - net_income

        net_change = self.moved("net_income")
        loan_change = self.moved("loan_portfolio")
        assets_change = self.moved("total_assets")
        bank_exec = []
        if net_change is not None:
            bank_exec.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистая прибыль изменилась на {financial_analysis_sector_language.format_number(net_change)}%.", f"Sof foyda {financial_analysis_sector_language.format_number(net_change)}% ga o‘zgardi.", f"Net profit changed {financial_analysis_sector_language.format_number(net_change)}%."))
        if net_interest_income is not None:
            bank_exec.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистый процентный доход составил {self.display_money(net_interest_income)} {self.money_unit}.", f"Sof foizli daromad {self.display_money(net_interest_income)} {self.money_unit}ni tashkil etdi.", f"Net interest income was {self.display_money(net_interest_income)} {self.money_unit}."))
        if cost_to_income is not None:
            bank_exec.append(financial_analysis_sector_language.tr(self.filing.lang, f"Cost-to-Income составил {self.pct_str(cost_to_income)}.", f"Cost-to-Income {self.pct_str(cost_to_income)}ni tashkil etdi.", f"Cost-to-Income was {self.pct_str(cost_to_income)}."))
        intro = f"{headline} " + (" ".join(bank_exec) or financial_analysis_sector_language.tr(self.filing.lang, "Главный вывод ограничен доступными раскрытиями.", "Asosiy xulosa mavjud ma’lumotlar bilan cheklangan.", "The key takeaway is limited by available disclosures."))

        # Assets and loan portfolio.
        asset_lines = []
        if assets_change is not None:
            grew = assets_change >= 0
            driver = ""
            loan_delta = financial_analysis_sector_numbers.difference(self.fact_now("loan_portfolio"), self.fact_before("loan_portfolio"))
            asset_delta = financial_analysis_sector_numbers.difference(self.fact_now("total_assets"), self.fact_before("total_assets"))
            if grew and loan_delta is not None and asset_delta is not None and asset_delta > 0 and loan_delta > 0 and loan_delta * 2 >= asset_delta:
                driver = financial_analysis_sector_language.tr(self.filing.lang, ", главным образом за счёт роста кредитного портфеля", ", asosan kredit portfeli o‘sishi hisobiga", ", mainly due to growth in the loan portfolio")
            asset_lines.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Активы банка за период {'увеличились' if grew else 'сократились'} на {financial_analysis_sector_language.format_number(abs(assets_change))}%{driver}.",
                f"Bank aktivlari davr mobaynida {financial_analysis_sector_language.format_number(abs(assets_change))}% ga {'oshdi' if grew else 'kamaydi'}{driver}.",
                f"The bank's assets {'increased' if grew else 'decreased'} by {financial_analysis_sector_language.format_number(abs(assets_change))}% over the period{driver}.",
            ))
        if loan_change is not None:
            if loan_change < 0:
                asset_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Кредитный портфель сократился на {financial_analysis_sector_language.format_number(abs(loan_change))}%. Для оценки причины важно сопоставить изменение с погашениями, выдачами и движением резервов — если эти данные раскрыты.", f"Kredit portfeli {financial_analysis_sector_language.format_number(abs(loan_change))}% ga qisqardi. Sababni baholash uchun o‘zgarishni so‘ndirishlar, berilgan kreditlar va zaxiralar harakati bilan solishtirish muhim — agar bu ma’lumotlar oshkor qilingan bo‘lsa.", f"The loan portfolio contracted by {financial_analysis_sector_language.format_number(abs(loan_change))}%. To assess the reason, the change should be compared with repayments, new lending and reserve movements — if these are disclosed."))
            elif assets_change is not None and loan_change > assets_change:
                asset_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Кредитный портфель рос быстрее активов: {self.pct_str(loan_change)} против {self.pct_str(assets_change)}. В структуре баланса усилилась роль кредитования.", f"Kredit portfeli aktivlardan tezroq o‘sdi: {self.pct_str(loan_change)} va {self.pct_str(assets_change)}. Balans tuzilmasida kreditlashning roli kuchaydi.", f"The loan portfolio grew faster than assets: {self.pct_str(loan_change)} versus {self.pct_str(assets_change)}. Lending now plays a larger role in the balance sheet."))
            else:
                asset_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Рост активов сопровождался расширением кредитного портфеля на {self.pct_str(loan_change)}. Это указывает на увеличение масштаба кредитных операций, но само по себе не характеризует их качество.", f"Aktivlar o‘sishi kredit portfelining {self.pct_str(loan_change)} ga kengayishi bilan birga kechdi. Bu kredit operatsiyalari ko‘lami oshganini ko‘rsatadi, ammo o‘z-o‘zidan ularning sifatini tavsiflamaydi.", f"Asset growth was accompanied by a {self.pct_str(loan_change)} expansion of the loan portfolio. This indicates larger lending operations but does not by itself describe their quality."))

        # Loan quality and reserves.  The statutory bank form reports the loan
        # line net of the reserve, so the gross book is net + reserve.
        reserve_lines = []
        reserves_now, reserves_open = self.fact_now("loan_reserves"), self.fact_before("loan_reserves")
        gross_book = self.filing.template == "bank"
        loans_now = financial_analysis_sector_numbers.total(self.fact_now("loan_portfolio"), reserves_now) if gross_book else self.fact_now("loan_portfolio")
        loans_open = financial_analysis_sector_numbers.total(self.fact_before("loan_portfolio"), reserves_open) if gross_book else self.fact_before("loan_portfolio")
        reserve_change = financial_analysis_sector_numbers.change(reserves_now, reserves_open)["change_pct"]
        book_change = financial_analysis_sector_numbers.change(loans_now, loans_open)["change_pct"]
        book_name = financial_analysis_sector_language.tr(self.filing.lang, "валовой кредитный портфель", "yalpi kredit portfeli", "the gross loan portfolio") if gross_book else financial_analysis_sector_language.tr(self.filing.lang, "кредитный портфель", "kredit portfeli", "the loan portfolio")
        if reserve_change is not None and book_change is not None:
            reserve_up, book_up = reserve_change >= 0, book_change >= 0
            reserve_lines.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Резервы под кредитные потери {'увеличились' if reserve_up else 'сократились'} на {financial_analysis_sector_language.format_number(abs(reserve_change))}%, тогда как {book_name} {'вырос' if book_up else 'сократился'} на {financial_analysis_sector_language.format_number(abs(book_change))}%.",
                f"Kredit yo‘qotishlari uchun zaxiralar {financial_analysis_sector_language.format_number(abs(reserve_change))}% ga {'oshdi' if reserve_up else 'kamaydi'}, {book_name} esa {financial_analysis_sector_language.format_number(abs(book_change))}% ga {'oshdi' if book_up else 'qisqardi'}.",
                f"Loan-loss reserves {'increased' if reserve_up else 'decreased'} by {financial_analysis_sector_language.format_number(abs(reserve_change))}%, while {book_name} {'grew' if book_up else 'contracted'} by {financial_analysis_sector_language.format_number(abs(book_change))}%.",
            ))
            if reserve_change > 0 and book_change >= 0 and reserve_change > book_change:
                reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Резервы росли быстрее кредитного портфеля. Это требует внимания, однако без данных о просрочке и классификации кредитов нельзя однозначно заключить, что качество портфеля ухудшилось.", "Zaxiralar kredit portfelidan tezroq o‘sdi. Bu e’tibor talab qiladi, ammo muddati o‘tgan kreditlar va kreditlar tasnifi haqida ma’lumotlarsiz portfel sifati yomonlashgan deb aniq xulosa chiqarib bo‘lmaydi.", "Reserves grew faster than the loan portfolio. This requires attention, but without data on overdue loans and loan classification it cannot be concluded that portfolio quality has deteriorated."))
            elif reserve_change > 0 and book_change < 0:
                reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Резервы увеличились при сокращении кредитного портфеля. Для объяснения динамики нужны данные о списаниях, восстановлении резервов и изменении качества кредитов.", "Kredit portfeli qisqargan holda zaxiralar oshdi. Dinamikani tushuntirish uchun hisobdan chiqarishlar, zaxiralarni tiklash va kreditlar sifati o‘zgarishi haqidagi ma’lumotlar kerak.", "Reserves increased while the loan portfolio contracted. Explaining this requires data on write-offs, reserve releases and changes in loan quality."))
        coverage_now, coverage_open = self.pct_of(reserves_now, loans_now), self.pct_of(reserves_open, loans_open)
        if coverage_now is not None:
            against = financial_analysis_sector_language.tr(self.filing.lang, f" против {self.pct_str(coverage_open)}", f" ({self.pct_str(coverage_open)} o‘rniga)", f" versus {self.pct_str(coverage_open)}") if coverage_open is not None else ""
            reserve_lines.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Отношение резервов к {'валовому кредитному портфелю' if gross_book else 'кредитному портфелю'} составило {self.pct_str(coverage_now)}{against}. Это аналитический коэффициент на основе отчётности, а не регуляторный норматив.",
                f"Zaxiralarning {'yalpi kredit portfeliga' if gross_book else 'kredit portfeliga'} nisbati {self.pct_str(coverage_now)}{against}ni tashkil etdi. Bu hisobotga asoslangan tahliliy koeffitsiyent, regulyativ me’yor emas.",
                f"The ratio of reserves to {'the gross loan portfolio' if gross_book else 'the loan portfolio'} was {self.pct_str(coverage_now)}{against}. This is an analytical ratio based on the financial statements, not a regulatory standard.",
            ))
        if reserves_now is not None:
            reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "В доступной форме нет достаточной детализации по просроченным и обесцененным кредитам; поэтому уровень проблемной задолженности по ней оценить нельзя.", "Mavjud shaklda muddati o‘tgan va qadrsizlangan kreditlar bo‘yicha yetarli tafsilot yo‘q; shu sababli muammoli qarzdorlik darajasini u orqali baholab bo‘lmaydi.", "The available form does not provide enough detail on overdue and impaired loans, so the level of problem debt cannot be assessed from it."))
        if reserve_change is not None and reserve_change > 0:
            reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Рост резервов может отражать как увеличение кредитного риска, так и изменение оценки ожидаемых потерь. По одной балансовой динамике различить эти причины нельзя.", "Zaxiralarning o‘sishi kredit riskining oshishini ham, kutilayotgan yo‘qotishlar bahosining o‘zgarishini ham aks ettirishi mumkin. Faqat balans dinamikasi bo‘yicha bu sabablarni ajratib bo‘lmaydi.", "Reserve growth may reflect either higher credit risk or a change in the estimate of expected losses. Balance-sheet movements alone cannot distinguish between these causes."))

        # Deposits, funding and liquidity.
        funding_lines = []
        funds_change = self.moved("customer_funds")
        if funds_change is not None and assets_change is not None and funds_change > 0 and assets_change >= 0 and funds_change > assets_change:
            lead_pp = financial_analysis_sector_language.format_number(funds_change - assets_change)
            funding_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Средства клиентов увеличились на {self.pct_str(funds_change)}, опережая рост активов на {lead_pp} п.п. В отчётности это соответствует усилению клиентской ресурсной базы.", f"Mijozlar mablag‘lari {self.pct_str(funds_change)} ga oshib, aktivlar o‘sishidan {lead_pp} foiz punktga o‘zib ketdi. Hisobotda bu mijozlar resurs bazasining kuchayishiga mos keladi.", f"Customer funds increased by {self.pct_str(funds_change)}, outpacing asset growth by {lead_pp} pp. In the statements this corresponds to a stronger customer funding base."))
        if funds_change is not None and loan_change is not None:
            funding_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Депозиты {'выросли' if funds_change >= 0 else 'сократились'} на {financial_analysis_sector_language.format_number(abs(funds_change))}%, а кредитный портфель — на {self.pct_str(loan_change)}. Для дополнительной оценки можно рассмотреть их соотношение, но оно не заменяет полноценный анализ ликвидности.", f"Depozitlar {financial_analysis_sector_language.format_number(abs(funds_change))}% ga {'oshdi' if funds_change >= 0 else 'kamaydi'}, kredit portfeli esa {self.pct_str(loan_change)} ga o‘zgardi. Qo‘shimcha baholash uchun ularning nisbatini ko‘rib chiqish mumkin, ammo u to‘laqonli likvidlik tahlilini almashtirmaydi.", f"Deposits {'grew' if funds_change >= 0 else 'contracted'} by {financial_analysis_sector_language.format_number(abs(funds_change))}%, and the loan portfolio changed by {self.pct_str(loan_change)}. Their ratio can be considered as an additional check, but it does not replace a full liquidity analysis."))
        ldr = self.pct_of(self.fact_now("loan_portfolio"), self.fact_now("customer_funds"))
        if ldr is not None:
            funding_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Расчётное отношение кредитного портфеля к средствам клиентов (LDR) составляет {self.pct_str(ldr)}. Показатель описывает соотношение двух статей баланса и не является самостоятельной оценкой платёжеспособности банка.", f"Kredit portfelining mijozlar mablag‘lariga hisoblangan nisbati (LDR) {self.pct_str(ldr)}ni tashkil etadi. Ko‘rsatkich ikki balans moddasi nisbatini tavsiflaydi va bankning to‘lov qobiliyatini mustaqil baholash emas.", f"The calculated ratio of the loan portfolio to customer funds (LDR) is {self.pct_str(ldr)}. The ratio describes the relationship between two balance-sheet items and does not by itself assess the bank's solvency."))
        term_now, term_open = self.pct_of(self.fact_now("term_deposits"), self.fact_now("customer_funds")), self.pct_of(self.fact_before("term_deposits"), self.fact_before("customer_funds"))
        demand_now, demand_open = self.pct_of(self.fact_now("demand_deposits"), self.fact_now("customer_funds")), self.pct_of(self.fact_before("demand_deposits"), self.fact_before("customer_funds"))
        if term_now is not None and term_open is not None and term_now > term_open:
            funding_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Доля срочных вкладов в средствах клиентов увеличилась с {self.pct_str(term_open)} до {self.pct_str(term_now)}; структура клиентского фондирования сместилась в сторону срочных средств.", f"Mijozlar mablag‘laridagi muddatli omonatlar ulushi {self.pct_str(term_open)}dan {self.pct_str(term_now)}gacha oshdi; mijozlar hisobidan moliyalashtirish tuzilmasi muddatli mablag‘lar tomon siljidi.", f"The share of term deposits in customer funds rose from {self.pct_str(term_open)} to {self.pct_str(term_now)}; the customer funding mix shifted towards term funds."))
        if demand_now is not None and demand_open is not None and demand_now > demand_open:
            funding_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Доля средств до востребования выросла. Это меняет структуру фондирования, но без данных о сроках активов и обязательств нельзя определить влияние на риск ликвидности.", "Talab qilinguncha mablag‘lar ulushi oshdi. Bu moliyalashtirish tuzilmasini o‘zgartiradi, ammo aktivlar va majburiyatlar muddatlari haqida ma’lumotlarsiz likvidlik riskiga ta’sirini aniqlab bo‘lmaydi.", "The share of demand funds increased. This changes the funding mix, but without data on the maturities of assets and liabilities its effect on liquidity risk cannot be determined."))
        liquid_keys = ("cash", "central_bank_balances", "due_from_banks")
        liquid_now = financial_analysis_sector_numbers.total(*(self.fact_now(key) for key in liquid_keys))
        liquid_open = financial_analysis_sector_numbers.total(*(self.fact_before(key) for key in liquid_keys))
        liquid_name = financial_analysis_sector_language.tr(self.filing.lang, "Денежные средства и средства в центральном и других банках", "Pul mablag‘lari hamda markaziy va boshqa banklardagi mablag‘lar", "Cash and balances with the central bank and other banks")
        if liquid_now is None or liquid_open is None:
            liquid_now = financial_analysis_sector_numbers.total(self.fact_now("cash"), self.fact_now("central_bank_balances"))
            liquid_open = financial_analysis_sector_numbers.total(self.fact_before("cash"), self.fact_before("central_bank_balances"))
            liquid_name = financial_analysis_sector_language.tr(self.filing.lang, "Денежные средства и средства в центральном банке", "Pul mablag‘lari va markaziy bankdagi mablag‘lar", "Cash and central bank balances")
        liquid_change = financial_analysis_sector_numbers.change(liquid_now, liquid_open)["change_pct"]
        if liquid_change is not None and liquid_change < 0:
            funding_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"{liquid_name} сократились на {financial_analysis_sector_language.format_number(abs(liquid_change))}%. Для оценки ликвидности этого недостаточно: нужны данные о сроках, доступности и составе ликвидных активов.", f"{liquid_name} {financial_analysis_sector_language.format_number(abs(liquid_change))}% ga kamaydi. Likvidlikni baholash uchun bu yetarli emas: likvid aktivlarning muddatlari, mavjudligi va tarkibi haqida ma’lumotlar kerak.", f"{liquid_name} decreased by {financial_analysis_sector_language.format_number(abs(liquid_change))}%. This is not enough to assess liquidity: data on the maturities, availability and composition of liquid assets are needed."))
            if loan_change is not None and loan_change > 0:
                funding_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Снижение отдельных денежных остатков сопровождается ростом кредитного портфеля. Это указывает на изменение размещения средств, но не позволяет само по себе сделать вывод о дефиците ликвидности.", "Ayrim pul qoldiqlarining kamayishi kredit portfelining o‘sishi bilan birga kechmoqda. Bu mablag‘larni joylashtirish o‘zgarganini ko‘rsatadi, ammo o‘z-o‘zidan likvidlik taqchilligi haqida xulosa chiqarishga imkon bermaydi.", "The decline in some cash balances is accompanied by growth in the loan portfolio. This indicates a reallocation of funds but does not by itself support a conclusion of a liquidity shortage."))
        elif liquid_change is not None:
            funding_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"{liquid_name} увеличились на {self.pct_str(liquid_change)}; для оценки ликвидности нужны также данные о сроках, доступности и составе ликвидных активов.", f"{liquid_name} {self.pct_str(liquid_change)} ga oshdi; likvidlikni baholash uchun likvid aktivlarning muddatlari, mavjudligi va tarkibi haqida ham ma’lumotlar kerak.", f"{liquid_name} increased by {self.pct_str(liquid_change)}; assessing liquidity also requires data on the maturities, availability and composition of liquid assets."))

        balance_facts = [self.fact_sentence(key) for key in ("total_assets", "loan_portfolio", "loan_reserves", "cash", "customer_funds", "total_liabilities", "total_equity")]
        balance_facts = [item for item in balance_facts if item]
        horizontal_text = " ".join(filter(None, (
            financial_analysis_sector_language.tr(self.filing.lang, "Горизонтальный анализ баланса. ", "Balansning gorizontal tahlili. ", "Horizontal balance-sheet analysis. ") + ("; ".join(balance_facts) if balance_facts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно сопоставимых строк.", "Taqqoslanadigan satrlar yetarli emas.", "Insufficient comparable lines.")) + ".",
            *asset_lines, *reserve_lines, *funding_lines,
        )))
        assets = self.fact_now("total_assets")
        vertical_text = self.vertical_narrative(
            ("loan_portfolio", "cash", "central_bank_balances", "due_from_banks"),
            financial_analysis_sector_language.tr(self.filing.lang, "Вертикальный анализ показывает не только текущие доли, но и то, как изменилась модель размещения активов. ", "Vertikal tahlil nafaqat joriy ulushlarni, balki aktivlarni joylashtirish modeli qanday o‘zgarganini ham ko‘rsatadi. ", "Vertical analysis shows both current shares and how the asset-allocation model changed. "),
            bank_funding=True,
        )

        # Income and profitability.
        income_lines = []
        nii_before = self.fact_now("net_interest_income_before_provisions")
        if nii_before is None:
            nii_before = net_interest_income
        nii_after = self.fact_now("net_interest_income_after_provisions")
        provisions = self.fact_now("credit_loss_provisions")
        if nii_before is not None and nii_after is not None:
            income_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистый процентный доход до оценки кредитных потерь составил {self.amount_text(nii_before)}. После учёта расходов на оценку потерь он составил {self.amount_text(nii_after)}.", f"Kredit yo‘qotishlarini baholashgacha sof foizli daromad {self.amount_text(nii_before)}ni tashkil etdi. Yo‘qotishlarni baholash xarajatlari hisobga olingach, u {self.amount_text(nii_after)}ni tashkil etdi.", f"Net interest income before the credit-loss estimate was {self.amount_text(nii_before)}. After the credit-loss estimate it was {self.amount_text(nii_after)}."))
        elif nii_before is not None:
            income_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистый процентный доход до оценки кредитных потерь составил {self.amount_text(nii_before)}.", f"Kredit yo‘qotishlarini baholashgacha sof foizli daromad {self.amount_text(nii_before)}ni tashkil etdi.", f"Net interest income before the credit-loss estimate was {self.amount_text(nii_before)}."))
        provision_share = self.pct_of(provisions, nii_before) if provisions is not None and provisions > 0 else None
        if provision_share is not None:
            material = provision_share >= 20
            income_lines.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Расходы на оценку кредитных потерь уменьшили чистый процентный результат на {self.pct_str(provision_share)}." + (" Их влияние существенно для итоговой оценки процентного бизнеса за период." if material else ""),
                f"Kredit yo‘qotishlarini baholash xarajatlari sof foizli natijani {self.pct_str(provision_share)} ga kamaytirdi." + (" Ularning ta’siri davr uchun foizli biznesning yakuniy bahosi uchun muhim." if material else ""),
                f"The credit-loss estimate reduced the net interest result by {self.pct_str(provision_share)}." + (" Its effect is material to the overall assessment of the interest business for the period." if material else ""),
            ))
        nii_prior = financial_analysis_sector_numbers.difference(self.fact_before("interest_income"), self.fact_before("interest_expenses"))
        nii_move = financial_analysis_sector_numbers.change(net_interest_income, nii_prior)["change_pct"] if nii_prior is not None and nii_prior > 0 else None
        if nii_move is not None:
            income_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистый процентный доход {'увеличился' if nii_move >= 0 else 'уменьшился'} на {financial_analysis_sector_language.format_number(abs(nii_move))}%. Для объяснения динамики следует отдельно рассмотреть процентные доходы и расходы.", f"Sof foizli daromad {financial_analysis_sector_language.format_number(abs(nii_move))}% ga {'oshdi' if nii_move >= 0 else 'kamaydi'}. Dinamikani tushuntirish uchun foizli daromad va xarajatlarni alohida ko‘rib chiqish kerak.", f"Net interest income {'increased' if nii_move >= 0 else 'decreased'} by {financial_analysis_sector_language.format_number(abs(nii_move))}%. Interest income and interest expense should be examined separately to explain the change."))
            income_move, expense_move = self.moved("interest_income"), self.moved("interest_expenses")
            if income_move is not None and expense_move is not None and max(income_move, expense_move) > 0:
                if income_move > expense_move:
                    income_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Процентные доходы росли быстрее процентных расходов, что поддержало чистый процентный результат.", "Foizli daromadlar foizli xarajatlardan tezroq o‘sdi va bu sof foizli natijani qo‘llab-quvvatladi.", "Interest income grew faster than interest expense, which supported the net interest result."))
                elif expense_move > income_move:
                    income_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Процентные расходы росли быстрее процентных доходов; это оказало давление на чистый процентный результат.", "Foizli xarajatlar foizli daromadlardan tezroq o‘sdi; bu sof foizli natijaga bosim o‘tkazdi.", "Interest expense grew faster than interest income, which put pressure on the net interest result."))
        fee_net = financial_analysis_sector_numbers.difference(self.fact_now("fee_income"), self.fact_now("fee_expenses"))
        fx_net = financial_analysis_sector_numbers.difference(self.fact_now("fx_income"), self.fact_now("fx_expenses"))
        if net_revenue_before_opex is not None and nii_after is not None and fee_net is not None and fx_net is not None:
            other = net_revenue_before_opex - nii_after - fee_net - fx_net
            sources = {
                "interest": (nii_after, financial_analysis_sector_language.tr(self.filing.lang, "процентные", "foizli", "interest")),
                "fee": (fee_net, financial_analysis_sector_language.tr(self.filing.lang, "комиссионные", "komission", "fee and commission")),
                "fx": (fx_net, financial_analysis_sector_language.tr(self.filing.lang, "валютные", "valyuta", "foreign-exchange")),
                "other": (other, financial_analysis_sector_language.tr(self.filing.lang, "прочие", "boshqa", "other")),
            }
            main = max(sources.values(), key=lambda item: item[0])
            if main[0] > 0:
                income_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Основной вклад в доходы до операционных расходов внесли {main[1]} операции.", f"Operatsion xarajatlargacha bo‘lgan daromadlarga asosiy hissani {main[1]} operatsiyalar qo‘shdi.", f"{main[1].capitalize()} operations made the main contribution to income before operating expenses."))
        if fx_net is not None and fx_net != 0:
            positive = fx_net > 0
            income_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистый результат по валютным операциям составил {self.amount_text(fx_net)} и оказал {'положительное' if positive else 'отрицательное'} влияние на прибыль периода.", f"Valyuta operatsiyalari bo‘yicha sof natija {self.amount_text(fx_net)}ni tashkil etdi va davr foydasiga {'ijobiy' if positive else 'salbiy'} ta’sir ko‘rsatdi.", f"The net result from foreign-exchange operations was {self.amount_text(fx_net)} and had a {'positive' if positive else 'negative'} effect on profit for the period."))

        if total_income is not None and total_income > 0 and interest_income >= 0 and noninterest_income >= 0:
            interest_share = self.pct_of(interest_income, total_income)
            noninterest_share = self.pct_of(noninterest_income, total_income)
            income_mix = financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Совокупные раскрытые доходы банка за {self.filing.period_text} составили {self.display_money(total_income)} {self.money_unit}: процентные доходы — {self.amount_text(interest_income)} ({self.pct_str(interest_share)}), непроцентные — {self.amount_text(noninterest_income)} ({self.pct_str(noninterest_share)}).",
                f"Bankning {self.filing.period_text} uchun jami oshkor qilingan daromadi {self.display_money(total_income)} {self.money_unit}: foizli daromad — {self.amount_text(interest_income)} ({self.pct_str(interest_share)}), foizsiz daromad — {self.amount_text(noninterest_income)} ({self.pct_str(noninterest_share)}).",
                f"The bank reported total disclosed income of {self.display_money(total_income)} {self.money_unit} for {self.filing.period_text}: interest income was {self.amount_text(interest_income)} ({self.pct_str(interest_share)}) and non-interest income was {self.amount_text(noninterest_income)} ({self.pct_str(noninterest_share)}).",
            )
        else:
            available_income = "; ".join(filter(None, (self.fact_sentence("interest_income"), self.fact_sentence("noninterest_income"))))
            income_mix = available_income or financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно данных для расчёта структуры доходов.", "Daromadlar tarkibini hisoblash uchun ma’lumot yetarli emas.", "Insufficient data to calculate the income mix.")
        income_text = financial_analysis_sector_language.tr(self.filing.lang, "Доходы и прибыльность. ", "Daromadlar va rentabellik. ", "Income and profitability. ") + " ".join([income_mix, *income_lines])

        expense_parts = []
        if interest_expenses is not None:
            expense_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"процентные расходы — {self.amount_text(interest_expenses)}", f"foizli xarajatlar — {self.amount_text(interest_expenses)}", f"interest expense was {self.amount_text(interest_expenses)}"))
        if interest_expense_share is not None:
            expense_parts.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"они равны {self.pct_str(interest_expense_share)} процентных доходов: это доля расходов в доходах, а не стоимость фондирования, для которой нужны средние процентные обязательства и ставки",
                f"bu foizli daromadning {self.pct_str(interest_expense_share)}iga teng: bu daromaddagi xarajat ulushi, moliyalashtirish qiymati emas; buning uchun o‘rtacha foizli majburiyatlar va stavkalar kerak",
                f"that equals {self.pct_str(interest_expense_share)} of interest income; this is an expense-to-income share, not funding cost, which requires average interest-bearing liabilities and rates",
            ))
        if operating_expenses is not None:
            expense_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"операционные расходы — {self.amount_text(operating_expenses)}", f"operatsion xarajatlar — {self.amount_text(operating_expenses)}", f"operating expenses were {self.amount_text(operating_expenses)}"))
        if noninterest_expenses is not None:
            expense_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"непроцентные расходы — {self.amount_text(noninterest_expenses)}", f"foizsiz xarajatlar — {self.amount_text(noninterest_expenses)}", f"non-interest expenses were {self.amount_text(noninterest_expenses)}"))
        expense_body = "; ".join(expense_parts)
        expense_text = financial_analysis_sector_language.tr(self.filing.lang, "Расходы и стоимость ресурсов. ", "Xarajatlar va resurslar qiymati. ", "Expenses and funding cost. ") + (expense_body[:1].upper() + expense_body[1:] if expense_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно раскрытых данных для расчёта структуры расходов.", "Xarajatlar tarkibini hisoblash uchun ma’lumot yetarli emas.", "Insufficient disclosed data to calculate the expense mix.")) + "."

        profit_parts = []
        if net_income is not None:
            profit_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистая прибыль составила {self.amount_text(net_income)}", f"Sof foyda {self.amount_text(net_income)}ni tashkil etdi", f"Net profit was {self.amount_text(net_income)}"))
            if net_change is not None:
                profit_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"изменение к сопоставимому периоду — {financial_analysis_sector_language.format_number(net_change)}%", f"taqqoslanadigan davrga nisbatan o‘zgarish — {financial_analysis_sector_language.format_number(net_change)}%", f"the change from the comparable period was {financial_analysis_sector_language.format_number(net_change)}%"))
        effective_tax = self.pct_of(tax_amount, profit_before_tax)
        if profit_before_tax is not None:
            profit_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"прибыль до налога — {self.amount_text(profit_before_tax)}", f"soliqdan oldingi foyda — {self.amount_text(profit_before_tax)}", f"profit before tax was {self.amount_text(profit_before_tax)}"))
        if tax_amount is not None:
            tax_source = financial_analysis_sector_language.tr(self.filing.lang, "раскрытый налог", "oshkor qilingan soliq", "disclosed tax") if disclosed_tax is not None else financial_analysis_sector_language.tr(self.filing.lang, "расчётная разница между прибылью до и после налога", "soliqdan oldingi va keyingi foyda o‘rtasidagi hisoblangan farq", "the calculated difference between pre- and post-tax profit")
            effective_tax_text = self.pct_str(effective_tax) if effective_tax is not None else financial_analysis_sector_language.tr(self.filing.lang, "не рассчитывается", "hisoblanmaydi", "not calculable")
            profit_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"налоговый расход — {self.amount_text(tax_amount)}, эффективная ставка — {effective_tax_text} ({tax_source})", f"soliq xarajati — {self.amount_text(tax_amount)}, samarali stavka — {effective_tax_text} ({tax_source})", f"tax expense was {self.amount_text(tax_amount)}, giving an effective rate of {effective_tax_text} ({tax_source})"))
        pbt_move = self.moved("profit_before_tax")
        tax_before = self.fact_before("tax")
        reconciles = all(
            item is not None for item in (profit_before_tax, disclosed_tax, net_income, self.fact_before("profit_before_tax"), tax_before, self.fact_before("net_income"))
        ) and profit_before_tax - disclosed_tax == net_income and self.fact_before("profit_before_tax") - tax_before == self.fact_before("net_income")
        pbt_sentence = ""
        if pbt_move is not None and net_change is not None and reconciles:
            pbt_sentence = " " + financial_analysis_sector_language.tr(self.filing.lang, f"Прибыль до налогообложения {'увеличилась' if pbt_move >= 0 else 'снизилась'} на {financial_analysis_sector_language.format_number(abs(pbt_move))}%, а чистая прибыль — на {self.pct_str(net_change)}. Разница связана с изменением налоговых расходов.", f"Soliqqa tortishgacha foyda {financial_analysis_sector_language.format_number(abs(pbt_move))}% ga {'oshdi' if pbt_move >= 0 else 'kamaydi'}, sof foyda esa {self.pct_str(net_change)} ga o‘zgardi. Farq soliq xarajatlarining o‘zgarishi bilan bog‘liq.", f"Profit before tax {'increased' if pbt_move >= 0 else 'decreased'} by {financial_analysis_sector_language.format_number(abs(pbt_move))}%, and net profit changed by {self.pct_str(net_change)}. The difference reflects the change in tax expense.")
        profit_text = financial_analysis_sector_language.tr(self.filing.lang, "Прибыль и налог. ", "Foyda va soliq. ", "Profit and tax. ") + ("; ".join(profit_parts) if profit_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно данных.", "Ma’lumot yetarli emas.", "Insufficient data.")) + "." + pbt_sentence + " " + financial_analysis_sector_language.tr(
            self.filing.lang,
            "Отклонение эффективной ставки от законодательной само по себе не доказывает наличие льгот: для вывода нужны налоговые примечания.",
            "Samarali stavkaning qonuniy stavkadan farqi imtiyoz mavjudligini o‘z-o‘zidan isbotlamaydi: xulosa uchun soliq izohlari kerak.",
            "A difference from the statutory rate does not by itself prove tax relief; tax notes are needed for that conclusion.",
        )
        results_text = " ".join((income_text, expense_text, profit_text))

        # Ratios, operating efficiency and capital.
        ratio_parts = []
        if net_interest_income is not None:
            ratio_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"NII = процентные доходы − процентные расходы = {self.amount_text(net_interest_income)}", f"NII = foizli daromad − foizli xarajat = {self.amount_text(net_interest_income)}", f"NII = interest income − interest expense = {self.amount_text(net_interest_income)}"))
        if interest_expense_share is not None:
            ratio_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"Доля процентных расходов в процентных доходах = {self.pct_str(interest_expense_share)}", f"Foizli xarajatlarning foizli daromaddagi ulushi = {self.pct_str(interest_expense_share)}", f"Interest expense / interest income = {self.pct_str(interest_expense_share)}"))
        if ldr is not None:
            ratio_parts.append(f"LDR = {financial_analysis_sector_language.tr(self.filing.lang, 'кредиты / средства клиентов', 'kreditlar / mijozlar mablag‘i', 'loans / customer funds')} = {self.pct_str(ldr)}")
        if cost_to_income is not None:
            ratio_parts.append(f"Cost-to-Income = {financial_analysis_sector_language.tr(self.filing.lang, 'операционные расходы / чистый доход до операционных расходов', 'operatsion xarajatlar / operatsion xarajatlargacha sof daromad', 'operating expenses / net revenue before operating expenses')} = {self.pct_str(cost_to_income)}")
        if coverage_now is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Резервы / валовой кредитный портфель', 'Zaxiralar / yalpi kredit portfeli', 'Loan reserves / gross loan portfolio') if gross_book else financial_analysis_sector_language.tr(self.filing.lang, 'Резервы / кредитный портфель', 'Zaxiralar / kredit portfeli', 'Loan reserves / loan portfolio')} = {self.pct_str(coverage_now)}")
        capital_share = self.pct_of(self.fact_now("total_equity"), assets)
        capital_share_open = self.pct_of(self.fact_before("total_equity"), self.fact_before("total_assets"))
        if capital_share is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Капитал / активы', 'Kapital / aktivlar', 'Equity / assets')} = {self.pct_str(capital_share)}")
        months = int(str(self.filing.period)[-1]) * 3 if re.fullmatch(r"\d{4}Q[1-4]", str(self.filing.period)) else 12
        assets_open = self.fact_before("total_assets")
        equity_now, equity_open = self.fact_now("total_equity"), self.fact_before("total_equity")
        average_basis = assets is not None and assets_open is not None and equity_now is not None and equity_open is not None
        asset_base = financial_analysis_sector_numbers.total(assets, assets_open) / 2 if assets is not None and assets_open is not None else assets
        equity_base = financial_analysis_sector_numbers.total(equity_now, equity_open) / 2 if equity_now is not None and equity_open is not None else equity_now
        annualized_profit = net_income * Decimal(12) / months if net_income is not None else None
        roa, roe = self.pct_of(annualized_profit, asset_base), self.pct_of(annualized_profit, equity_base)
        yearly = financial_analysis_sector_language.tr(self.filing.lang, " в годовом выражении", " yillik hisobda", " on an annualised basis") if months < 12 else ""
        efficiency_lines = []
        if roa is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'ROA (в годовом выражении)', 'ROA (yilliklashtirilgan)', 'ROA (annualized)')} = {self.pct_str(roa)}")
            efficiency_lines.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Рентабельность активов (ROA), рассчитанная по доступным данным, составила {self.pct_str(roa)}{yearly}. Это аналитическая оценка за {self.filing.period_text} с использованием {'средних' if average_basis else 'конечных'} активов.",
                f"Mavjud ma’lumotlar bo‘yicha hisoblangan aktivlar rentabelligi (ROA){yearly} {self.pct_str(roa)}ni tashkil etdi. Bu {self.filing.period_text} uchun {'o‘rtacha' if average_basis else 'davr oxiridagi'} aktivlardan foydalangan holda tahliliy baho.",
                f"Return on assets (ROA), calculated from the available data, was {self.pct_str(roa)}{yearly}. This is an analytical estimate for {self.filing.period_text} using {'average' if average_basis else 'closing'} assets.",
            ))
        if roe is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'ROE (в годовом выражении)', 'ROE (yilliklashtirilgan)', 'ROE (annualized)')} = {self.pct_str(roe)}")
            efficiency_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Рентабельность капитала (ROE) составила {self.pct_str(roe)}{yearly}. При сравнении важно учитывать, что расчёт может быть чувствителен к использованию конечного или среднего капитала и к пересчёту неполного года.", f"Kapital rentabelligi (ROE){yearly} {self.pct_str(roe)}ni tashkil etdi. Taqqoslashda hisob davr oxiridagi yoki o‘rtacha kapitaldan foydalanishga va to‘liq bo‘lmagan yilni qayta hisoblashga sezgir bo‘lishi mumkinligini hisobga olish muhim.", f"Return on equity (ROE) was {self.pct_str(roe)}{yearly}. When comparing, note that the calculation can be sensitive to using closing or average equity and to annualising a partial year."))
        if cost_to_income is not None:
            efficiency_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Операционные расходы составили {self.pct_str(cost_to_income)} от выбранной базы операционных доходов (Cost-to-Income). В расчёте использована формула: операционные расходы / чистый доход до операционных расходов.", f"Operatsion xarajatlar tanlangan operatsion daromadlar bazasining {self.pct_str(cost_to_income)}ini tashkil etdi (Cost-to-Income). Hisobda formula qo‘llanildi: operatsion xarajatlar / operatsion xarajatlargacha sof daromad.", f"Operating expenses were {self.pct_str(cost_to_income)} of the selected operating-income base (Cost-to-Income). The formula used is: operating expenses / net revenue before operating expenses."))
            cir_before = self.pct_of(self.fact_before("operating_expenses"), self.fact_before("net_revenue_before_operating_expenses"))
            if cir_before is not None and cost_to_income < cir_before:
                efficiency_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Показатель Cost-to-Income снизился с {self.pct_str(cir_before)} до {self.pct_str(cost_to_income)}, что соответствует уменьшению доли расходов в рассчитанной базе доходов. Это не обязательно означает абсолютное сокращение расходов.", f"Cost-to-Income ko‘rsatkichi {self.pct_str(cir_before)}dan {self.pct_str(cost_to_income)}gacha pasaydi, bu hisoblangan daromad bazasidagi xarajatlar ulushining kamayishiga mos keladi. Bu xarajatlar mutlaq qisqarganini anglatishi shart emas.", f"Cost-to-Income fell from {self.pct_str(cir_before)} to {self.pct_str(cost_to_income)}, meaning expenses took a smaller share of the calculated income base. This does not necessarily mean expenses fell in absolute terms."))
            elif cir_before is not None and cost_to_income > cir_before:
                efficiency_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Операционные расходы росли быстрее доходной базы, поэтому расчётный Cost-to-Income увеличился.", "Operatsion xarajatlar daromad bazasidan tezroq o‘sdi, shu sababli hisoblangan Cost-to-Income oshdi.", "Operating expenses grew faster than the income base, so the calculated Cost-to-Income rose."))
        equity_move = self.moved("total_equity")
        if equity_move is not None and assets_change is not None:
            equity_up, assets_up = equity_move >= 0, assets_change >= 0
            assets_clause = financial_analysis_sector_language.tr(self.filing.lang, f"а активы — на {financial_analysis_sector_language.format_number(abs(assets_change))}%", f"aktivlar esa {financial_analysis_sector_language.format_number(abs(assets_change))}% ga", f"and assets by {financial_analysis_sector_language.format_number(abs(assets_change))}%") if equity_up == assets_up else financial_analysis_sector_language.tr(self.filing.lang, f"а активы {'выросли' if assets_up else 'сократились'} на {financial_analysis_sector_language.format_number(abs(assets_change))}%", f"aktivlar esa {financial_analysis_sector_language.format_number(abs(assets_change))}% ga {'oshdi' if assets_up else 'kamaydi'}", f"while assets {'grew' if assets_up else 'contracted'} by {financial_analysis_sector_language.format_number(abs(assets_change))}%")
            shift = financial_analysis_sector_language.tr(self.filing.lang, f" Балансовое соотношение капитала к активам изменилось с {self.pct_str(capital_share_open)} до {self.pct_str(capital_share)}.", f" Kapitalning aktivlarga balans nisbati {self.pct_str(capital_share_open)}dan {self.pct_str(capital_share)}gacha o‘zgardi.", f" The balance-sheet ratio of equity to assets moved from {self.pct_str(capital_share_open)} to {self.pct_str(capital_share)}.") if capital_share is not None and capital_share_open is not None else ""
            efficiency_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Капитал {'вырос' if equity_up else 'сократился'} на {financial_analysis_sector_language.format_number(abs(equity_move))}%, {assets_clause}.", f"Kapital {financial_analysis_sector_language.format_number(abs(equity_move))}% ga {'oshdi' if equity_up else 'kamaydi'}, {assets_clause}.", f"Equity {'grew' if equity_up else 'contracted'} by {financial_analysis_sector_language.format_number(abs(equity_move))}% {assets_clause}.") + shift)
        if capital_share is not None:
            efficiency_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Соотношение капитала и активов рассчитано по бухгалтерскому балансу и не является нормативом достаточности капитала.", "Kapital va aktivlar nisbati buxgalteriya balansi bo‘yicha hisoblangan va kapital yetarliligi me’yori emas.", "The equity-to-assets ratio is calculated from the accounting balance sheet and is not a capital adequacy ratio."))
        efficiency_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"По предоставленной форме {self.nsbu_name} нельзя подтвердить соблюдение банковских пруденциальных нормативов; для этого требуются регуляторная отчётность и соответствующие нормативные данные.", f"Taqdim etilgan {self.nsbu_name} shakli bo‘yicha bankning prudensial me’yorlariga rioya qilinishini tasdiqlab bo‘lmaydi; buning uchun regulyativ hisobot va tegishli me’yoriy ma’lumotlar kerak.", f"The {self.nsbu_name} form provided cannot confirm compliance with prudential banking ratios; that requires regulatory reporting and the relevant regulatory data."))
        ratio_text = financial_analysis_sector_language.tr(self.filing.lang, "Коэффициентный анализ. ", "Koeffitsiyentlar tahlili. ", "Ratio analysis. ") + ("; ".join(ratio_parts) if ratio_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно компонентов для расчёта.", "Hisoblash komponentlari yetarli emas.", "Insufficient components for calculation.")) + ". " + " ".join(efficiency_lines)
        balance_text = financial_analysis_sector_language.tr(self.filing.lang, "Сводная оценка. ", "Yakuniy baho. ", "Summary assessment. ") + self.sector_conclusion()
        if total_expenses is None:
            balance_text += " " + financial_analysis_sector_language.tr(self.filing.lang, "Полная сумма расходов не рассчитана, поскольку не все необходимые строки раскрыты.", "Barcha zarur satrlar oshkor qilinmagani uchun jami xarajatlar hisoblanmadi.", "Total expenses were not calculated because not all required lines were disclosed.")
        self.narrative_blocks["performance"] = [
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Доходы и прибыльность", "Daromadlar va rentabellik", "Income and profitability"), "text": income_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Расходы и стоимость ресурсов", "Xarajatlar va resurslar qiymati", "Expenses and resource cost"), "text": expense_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Прибыль и налоги", "Foyda va soliqlar", "Profit and tax"), "text": profit_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Операционная эффективность и капитал", "Operatsion samaradorlik va kapital", "Operating efficiency and capital"), "text": " ".join(efficiency_lines)},
        ]
        position_blocks = [
            (financial_analysis_sector_language.tr(self.filing.lang, "Активы и кредитный портфель", "Aktivlar va kredit portfeli", "Assets and loan portfolio"), asset_lines),
            (financial_analysis_sector_language.tr(self.filing.lang, "Качество кредитов и резервы", "Kreditlar sifati va zaxiralar", "Loan quality and reserves"), reserve_lines),
            (financial_analysis_sector_language.tr(self.filing.lang, "Депозиты, финансирование и ликвидность", "Depozitlar, moliyalashtirish va likvidlik", "Deposits, funding and liquidity"), funding_lines),
        ]
        self.narrative_blocks["position"] = [
            {"lead": lead, "text": " ".join(lines)} for lead, lines in position_blocks if lines
        ] + [{"lead": financial_analysis_sector_language.tr(self.filing.lang, "Структура активов и капитала", "Aktivlar va kapital tarkibi", "Asset and capital structure"), "text": vertical_text}]
        return [intro, horizontal_text, vertical_text, results_text, ratio_text, balance_text]

    def insurance_analysis_paragraphs(self, headline):
        """Insurer narrative that keeps premiums, revenue, result and profit apart."""
        premiums = self.fact_now("insurance_premiums")
        premium_change = self.moved("insurance_premiums")
        ceded = self.fact_now("ceded_premiums")
        ceded_before = self.fact_before("ceded_premiums")
        revenue = self.fact_now("revenue")
        revenue_change = self.moved("revenue")
        service_cost = self.fact_now("insurance_service_cost")
        service_cost_change = self.moved("insurance_service_cost")
        service_result = self.fact_now("insurance_service_result")
        service_result_before = self.fact_before("insurance_service_result")
        if service_result is None:
            service_result = financial_analysis_sector_numbers.difference(revenue, service_cost)
            service_result_before = financial_analysis_sector_numbers.difference(self.fact_before("revenue"), self.fact_before("insurance_service_cost"))
        gross_reserves = self.fact_now("gross_insurance_reserves")
        reinsurer_reserves = self.fact_now("reinsurer_share_in_reserves")
        net_reserves = self.fact_now("net_insurance_reserves")
        operating_income = self.fact_now("operating_income")
        operating_change = self.moved("operating_income")
        net_income = self.fact_now("net_income")
        net_change = self.moved("net_income")
        claims = self.fact_now("insurance_claims")

        highlights = []
        if premium_change is not None:
            highlights.append(financial_analysis_sector_language.tr(self.filing.lang, f"Страховые премии изменились на {financial_analysis_sector_language.format_number(premium_change)}%.", f"Sug‘urta mukofotlari {financial_analysis_sector_language.format_number(premium_change)}% ga o‘zgardi.", f"Insurance premiums changed {financial_analysis_sector_language.format_number(premium_change)}%."))
        operating_before = self.fact_before("operating_income")
        if operating_change is not None and net_change is not None and operating_income is not None and operating_income > 0 and operating_before is not None and operating_before > 0:
            highlights.append(financial_analysis_sector_language.tr(self.filing.lang, f"Операционный результат изменился на {financial_analysis_sector_language.format_number(operating_change)}%, а чистая прибыль — на {financial_analysis_sector_language.format_number(net_change)}%.", f"Operatsion natija {financial_analysis_sector_language.format_number(operating_change)}%, sof foyda esa {financial_analysis_sector_language.format_number(net_change)}% ga o‘zgardi.", f"The operating result changed {financial_analysis_sector_language.format_number(operating_change)}% while net profit changed {financial_analysis_sector_language.format_number(net_change)}%."))
        highlights.append(financial_analysis_sector_language.tr(self.filing.lang, "В страховании важно не смешивать начисленные премии, признанную выручку от страховых услуг, страховой результат и чистую прибыль: это разные показатели и этапы учёта.", "Sug‘urtada hisoblangan mukofotlar, tan olingan sug‘urta xizmatlari tushumi, sug‘urta natijasi va sof foydani aralashtirmaslik muhim: bular turli ko‘rsatkichlar va hisobning turli bosqichlaridir.", "In insurance, written premiums, recognised insurance-service revenue, the insurance result and net profit must not be mixed: they are different indicators and different accounting stages."))
        intro = f"{headline} " + " ".join(highlights)

        # Premiums and scale of business.
        premium_lines = []
        if premiums is not None:
            if premium_change is not None and premium_change >= 0:
                premium_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Объём страховых премий за период составил {self.amount_text(premiums)}, увеличившись на {self.pct_str(premium_change)} к сопоставимому периоду.", f"Davr uchun sug‘urta mukofotlari hajmi {self.amount_text(premiums)}ni tashkil etib, taqqoslanadigan davrga nisbatan {self.pct_str(premium_change)} ga oshdi.", f"Insurance premiums for the period were {self.amount_text(premiums)}, up {self.pct_str(premium_change)} on the comparable period."))
                premium_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Рост премий указывает на расширение объёма привлечённого бизнеса, но сам по себе не подтверждает улучшение прибыльности или качества страхового портфеля.", "Mukofotlarning o‘sishi jalb qilingan biznes hajmi kengayganini ko‘rsatadi, ammo o‘z-o‘zidan rentabellik yoki sug‘urta portfeli sifati yaxshilanganini tasdiqlamaydi.", "Premium growth indicates a larger volume of business written, but does not by itself confirm better profitability or portfolio quality."))
            else:
                premium_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Объём страховых премий за период составил {self.amount_text(premiums)}.", f"Davr uchun sug‘urta mukofotlari hajmi {self.amount_text(premiums)}ni tashkil etdi.", f"Insurance premiums for the period were {self.amount_text(premiums)}."))
                if premium_change is not None:
                    premium_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Премии сократились на {financial_analysis_sector_language.format_number(abs(premium_change))}%. Для оценки устойчивости этой динамики нужны сопоставимые данные по видам страхования и каналам продаж.", f"Mukofotlar {financial_analysis_sector_language.format_number(abs(premium_change))}% ga qisqardi. Bu dinamikaning barqarorligini baholash uchun sug‘urta turlari va sotuv kanallari bo‘yicha taqqoslanadigan ma’lumotlar kerak.", f"Premiums fell by {financial_analysis_sector_language.format_number(abs(premium_change))}%. Comparable data by line of insurance and sales channel are needed to judge whether this is lasting."))
        if premium_change is not None and revenue_change is not None:
            premium_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Премии {'выросли' if premium_change >= 0 else 'снизились'} на {financial_analysis_sector_language.format_number(abs(premium_change))}%, тогда как чистая выручка от страховых услуг изменилась на {self.pct_str(revenue_change)}. Показатели отражают разные этапы учёта, поэтому их нельзя считать взаимозаменяемыми.", f"Mukofotlar {financial_analysis_sector_language.format_number(abs(premium_change))}% ga {'oshdi' if premium_change >= 0 else 'kamaydi'}, sug‘urta xizmatlaridan sof tushum esa {self.pct_str(revenue_change)} ga o‘zgardi. Ko‘rsatkichlar hisobning turli bosqichlarini aks ettiradi, shuning uchun ularni bir-birining o‘rnini bosuvchi deb hisoblab bo‘lmaydi.", f"Premiums {'rose' if premium_change >= 0 else 'fell'} by {financial_analysis_sector_language.format_number(abs(premium_change))}%, while net insurance-service revenue changed by {self.pct_str(revenue_change)}. The indicators reflect different accounting stages, so they cannot be treated as interchangeable."))

        # Reinsurance and risk retention (premium based, from ceded line c012).
        retention_lines = []
        ceded_share = self.pct_of(ceded, premiums)
        ceded_share_before = self.pct_of(ceded_before, self.fact_before("insurance_premiums"))
        if ceded_share is not None:
            versus = financial_analysis_sector_language.tr(self.filing.lang, f" — против {self.pct_str(ceded_share_before)} в сопоставимом периоде", f" — taqqoslanadigan davrdagi {self.pct_str(ceded_share_before)}ga qarshi", f", versus {self.pct_str(ceded_share_before)} in the comparable period") if ceded_share_before is not None else ""
            retention_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Переданные перестраховщикам премии составили {self.pct_str(ceded_share)} от валовых премий{versus}.", f"Qayta sug‘urtalovchilarga berilgan mukofotlar yalpi mukofotlarning {self.pct_str(ceded_share)}ini tashkil etdi{versus}.", f"Premiums ceded to reinsurers were {self.pct_str(ceded_share)} of gross premiums{versus}."))
            if ceded_share_before is not None and ceded_share > ceded_share_before:
                retention_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Доля переданных премий увеличилась. Это указывает на большую передачу премиального потока перестраховщикам, но не позволяет без дополнительных данных оценить снижение риска или экономическую эффективность перестрахования.", "Berilgan mukofotlar ulushi oshdi. Bu mukofotlar oqimining qayta sug‘urtalovchilarga ko‘proq o‘tkazilganini ko‘rsatadi, ammo qo‘shimcha ma’lumotlarsiz riskning kamayishini yoki qayta sug‘urtalashning iqtisodiy samaradorligini baholashga imkon bermaydi.", "The share of ceded premiums increased. This indicates that more of the premium flow is passed to reinsurers, but without further data it does not show whether risk fell or whether the reinsurance is economically efficient."))
            if ceded_share_before is not None and ceded_share != ceded_share_before:
                retention_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Изменение переданных премий может быть связано с изменением структуры бизнеса или перестраховочной программы; одной отчётности недостаточно, чтобы установить причину.", "Berilgan mukofotlarning o‘zgarishi biznes tuzilmasi yoki qayta sug‘urtalash dasturining o‘zgarishi bilan bog‘liq bo‘lishi mumkin; sababni aniqlash uchun birgina hisobot yetarli emas.", "The change in ceded premiums may reflect a change in the business mix or the reinsurance programme; the statements alone are not enough to establish the cause."))
            retained = financial_analysis_sector_numbers.difference(premiums, ceded)
            retention_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Расчётные удержанные премии составили {self.amount_text(retained)}: валовые премии за вычетом переданных перестраховщикам премий.", f"Hisoblangan ushlab qolingan mukofotlar {self.amount_text(retained)}ni tashkil etdi: yalpi mukofotlardan qayta sug‘urtalovchilarga berilgan mukofotlar ayirilgan.", f"Calculated retained premiums were {self.amount_text(retained)}: gross premiums less premiums ceded to reinsurers."))
            retention_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Доля удержания премий составила {self.pct_str(self.pct_of(retained, premiums))}. Это расчёт по премиям и не тождественно доле удержания страховых убытков.", f"Mukofotlarni ushlab qolish ulushi {self.pct_str(self.pct_of(retained, premiums))}ni tashkil etdi. Bu mukofotlar bo‘yicha hisob bo‘lib, sug‘urta zararlarini ushlab qolish ulushiga teng emas.", f"The premium retention rate was {self.pct_str(self.pct_of(retained, premiums))}. This is a premium-based calculation and is not the same as the retention of insurance losses."))
        reserve_retention = self.pct_of(net_reserves, gross_reserves)
        if reserve_retention is not None:
            retention_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Отдельно от премий: после учёта доли перестраховщиков на компании остаётся {self.pct_str(reserve_retention)} валовых технических резервов (удержание резервов).", f"Mukofotlardan alohida: qayta sug‘urtalovchilar ulushi hisobga olingach, kompaniyada yalpi texnik zaxiralarning {self.pct_str(reserve_retention)}i qoladi (zaxiralarni ushlab qolish).", f"Separately from premiums, after the reinsurers' share the company retains {self.pct_str(reserve_retention)} of gross technical reserves (reserve retention)."))
        if ceded_share is not None or reserve_retention is not None:
            retention_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Для оценки зависимости от перестрахования важно сопоставлять переданные премии с долей перестраховщиков в выплатах и технических резервах — если такие данные раскрыты.", "Qayta sug‘urtalashga bog‘liqlikni baholash uchun berilgan mukofotlarni qayta sug‘urtalovchilarning to‘lovlar va texnik zaxiralardagi ulushi bilan solishtirish muhim — agar bunday ma’lumotlar oshkor qilingan bo‘lsa.", "To assess dependence on reinsurance, ceded premiums should be compared with the reinsurers' share of claims and technical reserves — where these are disclosed."))

        # Insurance services, claims and result.
        service_lines = []
        if revenue is not None:
            service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Доход от страховых услуг составил {self.amount_text(revenue)}. Показатель отражает признанный в отчётности доход за период, а не обязательно сумму начисленных премий.", f"Sug‘urta xizmatlaridan daromad {self.amount_text(revenue)}ni tashkil etdi. Ko‘rsatkich hisobotda tan olingan davr daromadini aks ettiradi va hisoblangan mukofotlar summasiga teng bo‘lishi shart emas.", f"Insurance-service revenue was {self.amount_text(revenue)}. It reflects the revenue recognised for the period, not necessarily the amount of premiums written."))
            service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Чистая выручка от страховых услуг включает премии за вычетом переданных в перестрахование, результат изменения страховых резервов и прочие доходы от страховых услуг (стр. 010–050 формы) и поэтому отличается от объёма премий.", "Sug‘urta xizmatlaridan sof tushum qayta sug‘urtaga berilganlari ayirilgan mukofotlar, sug‘urta zaxiralari o‘zgarishi natijasi va boshqa sug‘urta xizmatlari daromadlarini (shaklning 010–050-satrlari) o‘z ichiga oladi, shuning uchun mukofotlar hajmidan farq qiladi.", "Net insurance-service revenue includes premiums net of reinsurance ceded, the result of changes in insurance reserves and other insurance-service income (form lines 010–050), so it differs from premium volume."))
        if service_cost_change is not None and revenue_change is not None:
            if service_cost_change > 0 and service_cost_change > revenue_change:
                gap = financial_analysis_sector_language.format_number(service_cost_change - revenue_change) if revenue_change >= 0 else None
                service_lines.append(financial_analysis_sector_language.tr(
                    self.filing.lang,
                    f"Расходы на страховые услуги увеличились на {self.pct_str(service_cost_change)}, опережая рост чистой выручки на {gap} п.п." if gap else f"Расходы на страховые услуги увеличились на {self.pct_str(service_cost_change)} при снижении чистой выручки на {financial_analysis_sector_language.format_number(abs(revenue_change))}%.",
                    f"Sug‘urta xizmatlari xarajatlari {self.pct_str(service_cost_change)} ga oshib, sof tushum o‘sishidan {gap} foiz punktga o‘zib ketdi." if gap else f"Sof tushum {financial_analysis_sector_language.format_number(abs(revenue_change))}% ga kamaygani holda sug‘urta xizmatlari xarajatlari {self.pct_str(service_cost_change)} ga oshdi.",
                    f"Insurance-service expenses rose by {self.pct_str(service_cost_change)}, outpacing net revenue growth by {gap} pp." if gap else f"Insurance-service expenses rose by {self.pct_str(service_cost_change)} while net revenue fell by {financial_analysis_sector_language.format_number(abs(revenue_change))}%.",
                ))
            elif service_cost_change < 0:
                service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Снижение расходов на страховые услуги поддержало результат периода, однако для оценки устойчивости эффекта нужно проверить, не связан ли он с изменением резервов или объёма бизнеса.", "Sug‘urta xizmatlari xarajatlarining kamayishi davr natijasini qo‘llab-quvvatladi, ammo ta’sir barqarorligini baholash uchun u zaxiralar yoki biznes hajmi o‘zgarishi bilan bog‘liq emasligini tekshirish kerak.", "Lower insurance-service expenses supported the result for the period, but to judge whether the effect will last it must be checked whether it stems from changes in reserves or business volume."))
            else:
                service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Расходы на страховые услуги выросли на {self.pct_str(service_cost_change)} — медленнее чистой выручки ({self.pct_str(revenue_change)}).", f"Sug‘urta xizmatlari xarajatlari {self.pct_str(service_cost_change)} ga oshdi — sof tushumdan ({self.pct_str(revenue_change)}) sekinroq.", f"Insurance-service expenses rose by {self.pct_str(service_cost_change)}, more slowly than net revenue ({self.pct_str(revenue_change)})."))
        if service_result is not None and service_result_before is not None:
            comparable_period = str(self.filing.snapshot.get("previous_comparable_period") or "")
            year_earlier = comparable_period[:4].isdigit() and str(self.filing.period)[:4].isdigit() and int(comparable_period[:4]) == int(str(self.filing.period)[:4]) - 1
            when = financial_analysis_sector_language.tr(self.filing.lang, "годом ранее" if year_earlier else "в сопоставимом периоде", "bir yil oldin" if year_earlier else "taqqoslanadigan davrda", "a year earlier" if year_earlier else "in the comparable period")
            service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Результат от страховых услуг составил {self.amount_text(service_result)} против {self.amount_text(service_result_before)} {when}; изменение обусловлено динамикой выручки и расходов на страховые услуги.", f"Sug‘urta xizmatlari natijasi {when} {self.amount_text(service_result_before)} bo‘lgan bo‘lsa, endi {self.amount_text(service_result)}ni tashkil etdi; o‘zgarish tushum va sug‘urta xizmatlari xarajatlari dinamikasi bilan bog‘liq.", f"The insurance-service result was {self.amount_text(service_result)} versus {self.amount_text(service_result_before)} {when}; the change reflects the movement in revenue and insurance-service expenses."))
            if service_result < service_result_before and premium_change is not None and premium_change > 0:
                service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Результат от страховых услуг снизился, несмотря на рост премий. Следовательно, рост объёма бизнеса не преобразовался в сопоставимое улучшение страхового результата.", "Mukofotlar o‘sganiga qaramay, sug‘urta xizmatlari natijasi pasaydi. Demak, biznes hajmining o‘sishi sug‘urta natijasining mos ravishda yaxshilanishiga aylanmadi.", "The insurance-service result fell despite premium growth, so the larger business volume did not translate into a comparable improvement in the insurance result."))
        if claims is not None:
            service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Рост выплат нельзя интерпретировать отдельно от заработанных премий, изменения резервов и доли перестраховщиков.", "To‘lovlar o‘sishini ishlab topilgan mukofotlar, zaxiralar o‘zgarishi va qayta sug‘urtalovchilar ulushidan alohida talqin qilib bo‘lmaydi.", "Claims growth cannot be interpreted apart from earned premiums, reserve changes and the reinsurers' share."))
        service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "В отчётности нет достаточной разбивки страховых выплат и заработанных премий; поэтому коэффициент убыточности по доступным данным не рассчитывается.", "Hisobotda sug‘urta to‘lovlari va ishlab topilgan mukofotlar bo‘yicha yetarli tafsilot yo‘q; shu sababli zararlilik koeffitsiyenti mavjud ma’lumotlar bo‘yicha hisoblanmaydi.", "The statements do not break down claims paid and earned premiums in enough detail, so the loss ratio is not calculated from the available data."))
        service_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Комбинированный коэффициент не рассчитывается: отсутствуют необходимые сопоставимые данные о выплатах, расходах на ведение дела и базе заработанных премий.", "Kombinatsiyalashgan koeffitsiyent hisoblanmaydi: to‘lovlar, ish yuritish xarajatlari va ishlab topilgan mukofotlar bazasi bo‘yicha zarur taqqoslanadigan ma’lumotlar yo‘q.", "The combined ratio is not calculated: the comparable data needed on claims, acquisition and administrative expenses and the earned-premium base are missing."))

        # Technical reserves and reinsurers.
        reserve_lines = []
        if gross_reserves is not None and reinsurer_reserves is not None and net_reserves is not None:
            reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Валовые технические резервы составили {self.amount_text(gross_reserves)}, доля перестраховщиков — {self.amount_text(reinsurer_reserves)}, расчётные резервы за вычетом доли перестраховщиков — {self.amount_text(net_reserves)}.", f"Yalpi texnik zaxiralar {self.amount_text(gross_reserves)}, qayta sug‘urtalovchilar ulushi — {self.amount_text(reinsurer_reserves)}, qayta sug‘urtalovchilar ulushi ayirilgan hisoblangan zaxiralar — {self.amount_text(net_reserves)}ni tashkil etdi.", f"Gross technical reserves were {self.amount_text(gross_reserves)}, the reinsurers' share {self.amount_text(reinsurer_reserves)}, and calculated reserves net of the reinsurers' share {self.amount_text(net_reserves)}."))
        gross_move, reinsurer_move, net_move = self.moved("gross_insurance_reserves"), self.moved("reinsurer_share_in_reserves"), self.moved("net_insurance_reserves")
        if gross_move is not None and reinsurer_move is not None:
            reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Валовые резервы {'выросли' if gross_move >= 0 else 'снизились'} на {financial_analysis_sector_language.format_number(abs(gross_move))}%, а доля перестраховщиков — на {financial_analysis_sector_language.format_number(abs(reinsurer_move)) if (reinsurer_move >= 0) == (gross_move >= 0) else financial_analysis_sector_language.format_number(reinsurer_move)}%. Изменение резервов следует рассматривать вместе с динамикой портфеля и перестрахования.", f"Yalpi zaxiralar {financial_analysis_sector_language.format_number(abs(gross_move))}% ga {'oshdi' if gross_move >= 0 else 'kamaydi'}, qayta sug‘urtalovchilar ulushi esa {financial_analysis_sector_language.format_number(reinsurer_move)}% ga o‘zgardi. Zaxiralar o‘zgarishini portfel va qayta sug‘urtalash dinamikasi bilan birga ko‘rib chiqish kerak.", f"Gross reserves {'rose' if gross_move >= 0 else 'fell'} by {financial_analysis_sector_language.format_number(abs(gross_move))}%, and the reinsurers' share changed by {financial_analysis_sector_language.format_number(reinsurer_move)}%. Reserve changes should be read together with portfolio and reinsurance movements."))
        if net_move is not None:
            reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Расчётные чистые технические резервы {'увеличились' if net_move >= 0 else 'снизились'} на {financial_analysis_sector_language.format_number(abs(net_move))}%. Это изменение балансовой оценки обязательств и само по себе не является мерой прибыльности.", f"Hisoblangan sof texnik zaxiralar {financial_analysis_sector_language.format_number(abs(net_move))}% ga {'oshdi' if net_move >= 0 else 'kamaydi'}. Bu majburiyatlar balans bahosining o‘zgarishi bo‘lib, o‘z-o‘zidan rentabellik o‘lchovi emas.", f"Calculated net technical reserves {'increased' if net_move >= 0 else 'decreased'} by {financial_analysis_sector_language.format_number(abs(net_move))}%. This is a change in the balance-sheet measurement of liabilities and is not in itself a measure of profitability."))
        reinsurer_share = self.pct_of(reinsurer_reserves, gross_reserves)
        if reinsurer_share is not None:
            reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Доля перестраховщиков в технических резервах составила {self.pct_str(reinsurer_share)}. Это показывает их участие в отражённых резервах, но не подтверждает фактическое получение возмещений.", f"Qayta sug‘urtalovchilarning texnik zaxiralardagi ulushi {self.pct_str(reinsurer_share)}ni tashkil etdi. Bu ularning aks ettirilgan zaxiralardagi ishtirokini ko‘rsatadi, ammo tovon puli haqiqatda olinishini tasdiqlamaydi.", f"The reinsurers' share of technical reserves was {self.pct_str(reinsurer_share)}. This shows their participation in the reported reserves but does not confirm that recoveries are actually received."))
        if gross_reserves is not None:
            reserve_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "По имеющейся форме нельзя определить достаточность резервов относительно будущих выплат без актуарной оценки и более детальной разбивки обязательств.", "Mavjud shakl bo‘yicha aktuar baholashsiz va majburiyatlarning batafsilroq taqsimotisiz zaxiralarning kelgusi to‘lovlarga nisbatan yetarliligini aniqlab bo‘lmaydi.", "The available form cannot establish whether reserves are adequate for future claims without an actuarial assessment and a more detailed breakdown of liabilities."))

        # Profitability and financial result.
        profit_lines = []
        if operating_income is not None:
            if operating_change is not None and not (self.evidence.by_code.get("operating_income") or {}).get("base_effect") and operating_income > 0:
                diverges = net_change is not None and (operating_change >= 0) != (net_change >= 0)
                profit_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Операционная прибыль составила {self.amount_text(operating_income)}, изменившись на {self.pct_str(operating_change)}." + (" Динамика отличается от динамики чистой прибыли." if diverges else ""), f"Operatsion foyda {self.amount_text(operating_income)}ni tashkil etib, {self.pct_str(operating_change)} ga o‘zgardi." + (" Uning dinamikasi sof foyda dinamikasidan farq qiladi." if diverges else ""), f"Operating profit was {self.amount_text(operating_income)}, a change of {self.pct_str(operating_change)}." + (" Its movement differs from that of net profit." if diverges else "")))
            else:
                before = self.fact_before("operating_income")
                versus = financial_analysis_sector_language.tr(self.filing.lang, f" против {self.amount_text(before)}", f" ({self.amount_text(before)} o‘rniga)", f" versus {self.amount_text(before)}") if before is not None else ""
                profit_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Операционный результат составил {self.amount_text(operating_income)}{versus}.", f"Operatsion natija {self.amount_text(operating_income)}ni tashkil etdi{versus}.", f"The operating result was {self.amount_text(operating_income)}{versus}."))
        finance_now = financial_analysis_sector_numbers.difference(self.fact_now("financial_income"), self.fact_now("financial_expenses"))
        fx_now, fx_before = financial_analysis_sector_numbers.difference(self.fact_now("fx_income"), self.fact_now("fx_expenses")), financial_analysis_sector_numbers.difference(self.fact_before("fx_income"), self.fact_before("fx_expenses"))
        if net_change is not None and operating_change is not None and net_change > 0 and operating_change < 0:
            drivers = []
            if finance_now is not None and finance_now > 0:
                drivers.append(financial_analysis_sector_language.tr(self.filing.lang, "финансовые доходы", "moliyaviy daromadlar", "finance income"))
            if fx_now is not None and fx_before is not None and fx_now > fx_before:
                drivers.append(financial_analysis_sector_language.tr(self.filing.lang, "валютный результат", "valyuta natijasi", "the FX result"))
            if drivers:
                profit_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистая прибыль выросла, хотя операционная прибыль снизилась; на итог повлияли {', '.join(drivers)}.", f"Operatsion foyda kamaygan bo‘lsa-da, sof foyda oshdi; yakunga {', '.join(drivers)} ta’sir qildi.", f"Net profit rose although operating profit fell; the result was influenced by {', '.join(drivers)}."))
        if finance_now is not None and finance_now > 0 and net_income is not None and net_income > 0:
            support = financial_analysis_sector_language.tr(self.filing.lang, f"Финансовый результат поддержал чистую прибыль на {self.amount_text(finance_now)}.", f"Moliyaviy natija sof foydani {self.amount_text(finance_now)}ga qo‘llab-quvvatladi.", f"The financial result supported net profit by {self.amount_text(finance_now)}.")
            if net_change is not None and net_change > 0:
                support += " " + financial_analysis_sector_language.tr(self.filing.lang, "Поэтому рост чистой прибыли не следует полностью относить к улучшению страховой деятельности.", "Shu sababli sof foyda o‘sishini to‘liq sug‘urta faoliyatining yaxshilanishiga bog‘lamaslik kerak.", "Net-profit growth should therefore not be attributed entirely to better insurance operations.")
            profit_lines.append(support)
        if fx_now is not None and fx_before is not None and fx_now != fx_before:
            helped = fx_now > fx_before
            profit_lines.append(financial_analysis_sector_language.tr(self.filing.lang, f"Чистый валютный результат составил {self.amount_text(fx_now)} против {self.amount_text(fx_before)}. Его изменение {'поддержало' if helped else 'снизило'} итоговую прибыль.", f"Sof valyuta natijasi {self.amount_text(fx_now)}ni tashkil etdi ({self.amount_text(fx_before)} o‘rniga). Uning o‘zgarishi yakuniy foydani {'qo‘llab-quvvatladi' if helped else 'kamaytirdi'}.", f"The net FX result was {self.amount_text(fx_now)} versus {self.amount_text(fx_before)}. The change {'supported' if helped else 'reduced'} the bottom line."))
        if net_change is not None and net_change > 0 and service_result is not None and service_result_before is not None and service_result < service_result_before:
            profit_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Рост прибыли сопровождается снижением результата от страховых услуг. Это означает, что улучшение итогового результата обеспечено не только основной страховой деятельностью.", "Foyda o‘sishi sug‘urta xizmatlari natijasining pasayishi bilan birga kechmoqda. Bu yakuniy natijaning yaxshilanishi faqat asosiy sug‘urta faoliyati hisobiga bo‘lmaganini anglatadi.", "Profit growth is accompanied by a lower insurance-service result, meaning the better bottom line did not come from core insurance operations alone."))
        profit_lines.append(financial_analysis_sector_language.tr(self.filing.lang, "Для оценки устойчивости прибыли важно разделять страховой результат, инвестиционный и прочий финансовый результат, а также влияние налога.", "Foyda barqarorligini baholash uchun sug‘urta natijasi, investitsiya va boshqa moliyaviy natija hamda soliq ta’sirini ajratish muhim.", "To judge how sustainable profit is, the insurance result, the investment and other financial result, and the tax effect must be separated."))

        balance_facts = [self.fact_sentence(key) for key in ("total_assets", "gross_insurance_reserves", "reinsurer_share_in_reserves", "net_insurance_reserves", "total_equity")]
        horizontal_text = " ".join(filter(None, (
            financial_analysis_sector_language.tr(self.filing.lang, "Баланс и технические резервы. ", "Balans va texnik zaxiralar. ", "Balance sheet and technical reserves. ") + "; ".join(item for item in balance_facts if item) + ".",
            *reserve_lines,
        )))
        vertical_text = financial_analysis_sector_language.tr(self.filing.lang, "Перестрахование и удержание риска. ", "Qayta sug‘urtalash va riskni ushlab qolish. ", "Reinsurance and risk retention. ") + (" ".join(retention_lines) or financial_analysis_sector_language.tr(self.filing.lang, "Компонентов для расчёта удержания недостаточно.", "Ushlab qolishni hisoblash uchun komponentlar yetarli emas.", "There are insufficient components to calculate retention."))
        result_facts = [self.fact_sentence(key) for key in ("insurance_premiums", "revenue", "insurance_service_result", "operating_income", "profit_before_tax", "net_income")]
        results_text = " ".join(filter(None, (
            financial_analysis_sector_language.tr(self.filing.lang, "Премии, страховые услуги и прибыльность. ", "Mukofotlar, sug‘urta xizmatlari va rentabellik. ", "Premiums, insurance services and profitability. ") + "; ".join(item for item in result_facts if item) + ".",
            *premium_lines, *service_lines, *profit_lines,
        )))

        ratio_parts = []
        if ceded_share is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Переданные премии / валовые премии', 'Berilgan mukofotlar / yalpi mukofotlar', 'Ceded premiums / gross premiums')} = {self.pct_str(ceded_share)}")
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Удержание премий', 'Mukofotlarni ushlab qolish', 'Premium retention')} = {self.pct_str(self.pct_of(financial_analysis_sector_numbers.difference(premiums, ceded), premiums))}")
        if reserve_retention is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Удержание резервов', 'Zaxiralarni ushlab qolish', 'Reserve retention')} = {self.pct_str(reserve_retention)}")
        if reinsurer_share is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Доля перестраховщиков в резервах', 'Zaxiralardagi qayta sug‘urtalovchilar ulushi', 'Reinsurer share of reserves')} = {self.pct_str(reinsurer_share)}")
        service_margin = self.pct_of(service_result, revenue) if revenue is not None and revenue > 0 else None
        if service_margin is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Результат от страховых услуг / чистая выручка от страховых услуг', 'Sug‘urta xizmatlari natijasi / sof tushum', 'Insurance-service result / net insurance-service revenue')} = {self.pct_str(service_margin)}")
        ratio_text = financial_analysis_sector_language.tr(self.filing.lang, "Ключевые страховые коэффициенты. ", "Asosiy sug‘urta koeffitsiyentlari. ", "Key insurance ratios. ") + ("; ".join(ratio_parts) if ratio_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно компонентов для расчёта.", "Hisoblash uchun komponentlar yetarli emas.", "Insufficient components for calculation.")) + ". " + financial_analysis_sector_language.tr(self.filing.lang, "Это аналитические коэффициенты на основе отчётности, а не нормативы, установленные регулятором; коэффициенты убыточности и комбинированный не рассчитываются без раскрытых выплат и заработанных премий.", "Bular hisobotga asoslangan tahliliy koeffitsiyentlar, regulyator belgilagan me’yorlar emas; zararlilik va kombinatsiyalashgan koeffitsiyentlar oshkor qilingan to‘lovlar va ishlab topilgan mukofotlarsiz hisoblanmaydi.", "These are analytical ratios based on the statements, not standards set by the regulator; the loss and combined ratios are not calculated without disclosed claims and earned premiums.")
        summary_text = financial_analysis_sector_language.tr(self.filing.lang, "Сводная оценка. ", "Yakuniy baho. ", "Summary assessment. ") + self.sector_conclusion()
        self.narrative_blocks["performance"] = [
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Премии и масштаб бизнеса", "Mukofotlar va biznes ko‘lami", "Premiums and scale of business"), "text": " ".join(premium_lines) or results_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Страховые услуги, выплаты и результат", "Sug‘urta xizmatlari, to‘lovlar va natija", "Insurance services, claims and result"), "text": " ".join(service_lines)},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Прибыльность и финансовый результат", "Rentabellik va moliyaviy natija", "Profitability and financial result"), "text": " ".join(profit_lines)},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Ключевые страховые коэффициенты", "Asosiy sug‘urta koeffitsiyentlari", "Key insurance ratios"), "text": ratio_text},
        ]
        self.narrative_blocks["position"] = [
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Технические резервы и перестраховщики", "Texnik zaxiralar va qayta sug‘urtalovchilar", "Technical reserves and reinsurers"), "text": horizontal_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Перестрахование и удержание риска", "Qayta sug‘urtalash va riskni ushlab qolish", "Reinsurance and risk retention"), "text": vertical_text},
        ]
        return [intro, horizontal_text, vertical_text, results_text, ratio_text, summary_text]

    def fund_analysis_paragraphs(self, headline):
        """Describe an audited investment fund through portfolio economics."""
        value = lambda key: financial_analysis_sector_numbers.decimal((self.evidence.by_code.get(key) or {}).get("value"))
        pct = lambda numerator, denominator: financial_analysis_sector_numbers.ratio(numerator, denominator, True)
        pct_text = lambda item: f"{financial_analysis_sector_language.format_number(item)}%" if item is not None else None
        portfolio = value("portfolio_fair_value")
        assets = value("total_assets")
        equity = value("total_equity")
        liabilities = value("total_liabilities")
        top5 = value("top5_holdings")
        largest = value("largest_holding")
        level3 = value("level3_investments")
        unrealized = value("unrealized_fair_value_gain")
        dividends = value("dividend_income")
        expenses = value("management_expenses")
        tax = value("tax")
        net_income = value("net_income")

        portfolio_share = pct(portfolio, assets)
        top5_share = pct(top5, portfolio)
        largest_share = pct(largest, portfolio)
        level3_share = pct(level3, portfolio)
        equity_share = pct(equity, assets)
        unrealized_to_profit = pct(unrealized, net_income)
        intro = f"{headline} " + financial_analysis_sector_language.tr(
            self.filing.lang,
            f"Фонд оценивается по структуре и концентрации инвестиционного портфеля, качеству оценки и источникам прибыли; корпоративные показатели выручки и оборотного капитала к нему не применяются. Портфель составляет {pct_text(portfolio_share) or '—'} активов.",
            f"Fond investitsiya portfeli tarkibi va jamlanishi, baholash sifati hamda foyda manbalari bo‘yicha baholanadi; korporativ tushum va aylanma kapital ko‘rsatkichlari unga qo‘llanmaydi. Portfel aktivlarning {pct_text(portfolio_share) or '—'}ini tashkil etadi.",
            f"The fund is assessed through portfolio structure and concentration, valuation quality and profit sources; corporate revenue and working-capital measures do not apply. The portfolio represents {pct_text(portfolio_share) or '—'} of assets.",
        )

        position_facts = [self.fact_sentence(key, comparison=False) for key in ("total_assets", "portfolio_fair_value", "cash", "dividends_receivable", "accounts_payable", "total_equity", "total_liabilities")]
        horizontal_text = financial_analysis_sector_language.tr(self.filing.lang, "Активы, портфель и капитал. ", "Aktivlar, portfel va kapital. ", "Assets, portfolio and capital. ") + "; ".join(item for item in position_facts if item) + "."
        concentration_parts = []
        if portfolio_share is not None:
            concentration_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"инвестиционный портфель составляет {pct_text(portfolio_share)} активов", f"investitsiya portfeli aktivlarning {pct_text(portfolio_share)}ini tashkil etadi", f"the investment portfolio equals {pct_text(portfolio_share)} of assets"))
        if top5_share is not None:
            concentration_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"пять крупнейших позиций — {pct_text(top5_share)} портфеля", f"beshta eng yirik pozitsiya portfelning {pct_text(top5_share)}ini tashkil etadi", f"the five largest holdings represent {pct_text(top5_share)} of the portfolio"))
        if largest_share is not None:
            concentration_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"крупнейшая позиция — {pct_text(largest_share)} портфеля", f"eng yirik pozitsiya portfelning {pct_text(largest_share)}ini tashkil etadi", f"the largest holding represents {pct_text(largest_share)} of the portfolio"))
        if level3_share is not None:
            concentration_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"инструменты Level 3 — {pct_text(level3_share)} портфеля", f"Level 3 vositalari portfelning {pct_text(level3_share)}ini tashkil etadi", f"Level 3 instruments represent {pct_text(level3_share)} of the portfolio"))
        if equity_share is not None:
            concentration_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"капитал покрывает {pct_text(equity_share)} активов", f"kapital aktivlarning {pct_text(equity_share)}ini qoplaydi", f"equity covers {pct_text(equity_share)} of assets"))
        vertical_text = financial_analysis_sector_language.tr(self.filing.lang, "Структура и концентрация портфеля. ", "Portfel tarkibi va jamlanishi. ", "Portfolio structure and concentration. ") + "; ".join(concentration_parts) + ". " + financial_analysis_sector_language.tr(
            self.filing.lang,
            "Высокая доля Level 3 означает зависимость стоимости портфеля от моделей и непубличных исходных данных, а не автоматически низкое качество активов.",
            "Level 3 ulushining yuqoriligi portfel qiymati modellarga va ochiq bo‘lmagan ma’lumotlarga bog‘liqligini anglatadi, lekin aktivlar sifati avtomatik ravishda past degani emas.",
            "A high Level 3 share means portfolio value depends on models and unobservable inputs; it does not automatically imply poor asset quality.",
        )

        valuation_parts = [self.fact_sentence(key, comparison=False) for key in ("unrealized_fair_value_gain", "dividend_income")]
        valuation_text = financial_analysis_sector_language.tr(self.filing.lang, "Источники инвестиционного результата. ", "Investitsiya natijasi manbalari. ", "Sources of investment return. ") + "; ".join(item for item in valuation_parts if item) + "."
        if unrealized_to_profit is not None:
            valuation_text += " " + financial_analysis_sector_language.tr(self.filing.lang, f"Нереализованная переоценка равна {pct_text(unrealized_to_profit)} чистой прибыли, поэтому устойчивость результата зависит от будущего подтверждения оценочной стоимости.", f"Realizatsiya qilinmagan qayta baholash sof foydaning {pct_text(unrealized_to_profit)}iga teng, shuning uchun natija barqarorligi baholash qiymatining kelajakda tasdiqlanishiga bog‘liq.", f"Unrealized revaluation equals {pct_text(unrealized_to_profit)} of net profit, so result sustainability depends on future confirmation of the valuation.")
        cost_parts = [self.fact_sentence(key, comparison=False) for key in ("management_expenses", "tax", "net_income")]
        profit_text = financial_analysis_sector_language.tr(self.filing.lang, "Расходы и итоговая прибыль. ", "Xarajatlar va yakuniy foyda. ", "Expenses and final profit. ") + "; ".join(item for item in cost_parts if item) + "."
        ratio_parts = []
        for title, result in (
            (financial_analysis_sector_language.tr(self.filing.lang, "Портфель / активы", "Portfel / aktivlar", "Portfolio / assets"), portfolio_share),
            (financial_analysis_sector_language.tr(self.filing.lang, "Топ-5 / портфель", "Top-5 / portfel", "Top five / portfolio"), top5_share),
            (financial_analysis_sector_language.tr(self.filing.lang, "Крупнейшая позиция / портфель", "Eng yirik pozitsiya / portfel", "Largest holding / portfolio"), largest_share),
            (financial_analysis_sector_language.tr(self.filing.lang, "Level 3 / портфель", "Level 3 / portfel", "Level 3 / portfolio"), level3_share),
            (financial_analysis_sector_language.tr(self.filing.lang, "Капитал / активы", "Kapital / aktivlar", "Equity / assets"), equity_share),
        ):
            if result is not None:
                ratio_parts.append(f"{title} = {pct_text(result)}")
        ratio_text = financial_analysis_sector_language.tr(self.filing.lang, "Ключевые показатели фонда. ", "Fondning asosiy ko‘rsatkichlari. ", "Key fund metrics. ") + "; ".join(ratio_parts) + "."
        summary_text = financial_analysis_sector_language.tr(
            self.filing.lang,
            "Сводная оценка. Главные вопросы — концентрация портфеля, доля нереализованной переоценки и надёжность Level 3-оценок. Без сопоставимого прошлого периода нельзя делать вывод о тренде доходности.",
            "Yakuniy baho. Asosiy masalalar — portfel jamlanishi, realizatsiya qilinmagan qayta baholash ulushi va Level 3 baholarining ishonchliligi. Taqqoslanadigan oldingi davrsiz daromadlilik trendi haqida xulosa qilib bo‘lmaydi.",
            "Summary assessment. The central questions are portfolio concentration, the unrealized-revaluation share and reliability of Level 3 valuations. A return trend cannot be established without a comparable prior period.",
        )
        self.narrative_blocks["performance"] = [
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Переоценка портфеля", "Portfelni qayta baholash", "Portfolio revaluation"), "text": valuation_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Расходы и чистая прибыль", "Xarajatlar va sof foyda", "Expenses and net profit"), "text": profit_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Ключевые показатели фонда", "Fondning asosiy ko‘rsatkichlari", "Key fund metrics"), "text": ratio_text},
        ]
        self.narrative_blocks["position"] = [
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Активы, портфель и капитал", "Aktivlar, portfel va kapital", "Assets, portfolio and capital"), "text": horizontal_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Концентрация и качество оценки", "Jamlanish va baholash sifati", "Concentration and valuation quality"), "text": vertical_text},
        ]
        return [intro, horizontal_text, vertical_text, f"{valuation_text} {profit_text}", ratio_text, summary_text]

    def general_analysis_paragraphs(self, headline):
        """Detailed non-bank narrative using only traceable statement totals."""
        value = lambda key: financial_analysis_sector_numbers.decimal((self.evidence.by_code.get(key) or {}).get("value"))
        pct = lambda numerator, denominator: financial_analysis_sector_numbers.ratio(numerator, denominator, True)
        money = lambda key: f"{self.display_money(value(key))} {self.money_unit}" if value(key) is not None else None
        pct_text = lambda item: f"{financial_analysis_sector_language.format_number(item)}%" if item is not None else None
        profile = financial_analysis_sector_templates.SECTOR_PROFILES.get(self.filing.template)
        sector_name = financial_analysis_sector_language.tr(self.filing.lang, *profile["name"]) if profile else financial_analysis_sector_language.tr(self.filing.lang, "товарная биржа", "tovar birjasi", "commodity exchange") if self.filing.template == "commodity_exchange" else financial_analysis_sector_language.tr(self.filing.lang, "универсальный профиль", "umumiy profil", "general profile")
        oked_code = self.filing.resolution.get("input_oked")

        revenue = value("revenue") or value("insurance_premiums") or value("operating_income")
        revenue_key = "revenue" if value("revenue") is not None else "insurance_premiums" if value("insurance_premiums") is not None else "operating_income"
        cost = value("cost_of_sales") or value("insurance_claims")
        gross = value("gross_profit")
        period_expenses = value("period_expenses") or value("expenses") or value("management_expenses")
        operating_income = value("operating_income")
        profit_before_tax = value("profit_before_tax")
        net_income = value("net_income")
        disclosed_tax = value("tax")
        tax_amount = disclosed_tax
        if tax_amount is None and profit_before_tax is not None and net_income is not None:
            tax_amount = profit_before_tax - net_income

        revenue_change = (self.evidence.by_code.get(revenue_key) or {}).get("change_pct")
        operating_change = (self.evidence.by_code.get("operating_income") or {}).get("change_pct")
        net_change = (self.evidence.by_code.get("net_income") or {}).get("change_pct")
        cash_change = (self.evidence.by_code.get("cash") or {}).get("change_pct")
        liabilities_change = (self.evidence.by_code.get("total_liabilities") or {}).get("change_pct")
        operating_margin = pct(operating_income, revenue)
        financial_result = financial_analysis_sector_numbers.difference(value("financial_income"), value("financial_expenses"))
        previous_financial_result = financial_analysis_sector_numbers.difference(
            (self.evidence.by_code.get("financial_income") or {}).get("previous"),
            (self.evidence.by_code.get("financial_expenses") or {}).get("previous"),
        )
        financial_result_change = financial_analysis_sector_numbers.difference(financial_result, previous_financial_result)
        executive = []
        if revenue_change is not None and revenue_change > 0 and operating_change is not None and operating_change < 0:
            executive.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Выручка выросла на {financial_analysis_sector_language.format_number(revenue_change)}%, однако операционная прибыль снизилась на {financial_analysis_sector_language.format_number(abs(operating_change))}%; операционная маржа составила {pct_text(operating_margin) or '—'}. Это означает, что рост масштаба не улучшил эффективность основной деятельности.",
                f"Tushum {financial_analysis_sector_language.format_number(revenue_change)}% ga oshdi, biroq operatsion foyda {financial_analysis_sector_language.format_number(abs(operating_change))}% ga kamaydi; operatsion marja {pct_text(operating_margin) or '—'} bo‘ldi. Demak, faoliyat ko‘lami o‘sishi asosiy faoliyat samaradorligini yaxshilamadi.",
                f"Revenue grew {financial_analysis_sector_language.format_number(revenue_change)}%, but operating profit fell {financial_analysis_sector_language.format_number(abs(operating_change))}%; operating margin was {pct_text(operating_margin) or '—'}. Greater scale therefore did not improve core operating efficiency.",
            ))
        elif revenue_change is not None and net_change is not None:
            executive.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Доходы изменились на {financial_analysis_sector_language.format_number(revenue_change)}%, чистая прибыль — на {financial_analysis_sector_language.format_number(net_change)}%. Разница между темпами показывает, улучшается ли конверсия выручки в итоговый результат.",
                f"Daromad {financial_analysis_sector_language.format_number(revenue_change)}%, sof foyda esa {financial_analysis_sector_language.format_number(net_change)}% ga o‘zgardi. O‘sish sur’atlari farqi tushumning yakuniy natijaga aylanishi yaxshilanayotganini ko‘rsatadi.",
                f"Income changed {financial_analysis_sector_language.format_number(revenue_change)}% and net profit {financial_analysis_sector_language.format_number(net_change)}%. The gap shows whether revenue is converting into final earnings more effectively.",
            ))
        if operating_change is not None and operating_change < 0 and net_change is not None and net_change > 0 and financial_result_change is not None:
            executive.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"При этом чистая прибыль выросла не вслед за основной деятельностью: чистый финансовый результат улучшился на {self.display_money(financial_result_change)} {self.money_unit}. Курсовые разницы входят в этот финансовый результат и отдельно не суммируются.",
                f"Shu bilan birga sof foyda asosiy faoliyat ortidan oshmadi: sof moliyaviy natija {self.display_money(financial_result_change)} {self.money_unit}ga yaxshilandi. Kurs farqlari ushbu moliyaviy natija tarkibiga kiradi va alohida qo‘shilmaydi.",
                f"Net profit therefore did not rise with core operations: the net finance result improved by {self.display_money(financial_result_change)} {self.money_unit}. FX differences are included in that finance result and are not added again.",
            ))
        if cash_change is not None and liabilities_change is not None and cash_change < 0 < liabilities_change:
            executive.append(financial_analysis_sector_language.tr(
                self.filing.lang,
                f"Одновременно деньги сократились на {financial_analysis_sector_language.format_number(abs(cash_change))}%, а обязательства выросли на {financial_analysis_sector_language.format_number(liabilities_change)}%, поэтому главный риск периода — ослабление ликвидной позиции.",
                f"Shu bilan birga pul {financial_analysis_sector_language.format_number(abs(cash_change))}% ga kamaydi, majburiyatlar {financial_analysis_sector_language.format_number(liabilities_change)}% ga oshdi; davrning asosiy xavfi — likvidlik holatining zaiflashishi.",
                f"At the same time, cash fell {financial_analysis_sector_language.format_number(abs(cash_change))}% while liabilities rose {financial_analysis_sector_language.format_number(liabilities_change)}%, making weaker liquidity the period’s main risk.",
            ))
        if not executive:
            executive.append(financial_analysis_sector_language.tr(self.filing.lang, "Главный вывод формируется из динамики прибыли, маржи и баланса; неподтверждённые причины не используются.", "Asosiy xulosa foyda, marja va balans dinamikasidan tuziladi; tasdiqlanmagan sabablar ishlatilmaydi.", "The main conclusion is based on profit, margin and balance-sheet movements; unverified causes are excluded."))
        basis = financial_analysis_sector_language.tr(
            self.filing.lang,
            f"Аналитический профиль: {sector_name}" + (f" (ОКЭД {oked_code})" if oked_code else "") + ".",
            f"Tahlil profili: {sector_name}" + (f" (IFUT {oked_code})" if oked_code else "") + ".",
            f"Analysis profile: {sector_name}" + (f" (OKED {oked_code})" if oked_code else "") + ".",
        )
        intro = f"{headline} {basis} " + " ".join(executive)

        income_parts = [self.fact_sentence(revenue_key)] if revenue_key in self.evidence.by_code else []
        if cost is not None:
            cost_key = "cost_of_sales" if value("cost_of_sales") is not None else "insurance_claims"
            cost_share = pct(cost, revenue)
            income_parts.append(f"{financial_analysis_sector_language.label(cost_key, self.filing.lang)}: {money(cost_key)}" + (f" ({pct_text(cost_share)} {financial_analysis_sector_language.tr(self.filing.lang, 'доходов', 'daromadga nisbatan', 'of income')})" if cost_share is not None else ""))
        if gross is not None:
            income_parts.append(f"{financial_analysis_sector_language.label('gross_profit', self.filing.lang)}: {money('gross_profit')}" + (f" ({financial_analysis_sector_language.tr(self.filing.lang, 'маржа', 'marja', 'margin')} {pct_text(pct(gross, revenue))})" if pct(gross, revenue) is not None else ""))
        income_text = financial_analysis_sector_language.tr(self.filing.lang, "Доходы и прямые затраты. ", "Daromadlar va bevosita xarajatlar. ", "Income and direct costs. ") + ("; ".join(filter(None, income_parts)) if income_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно данных для расчёта структуры.", "Tarkibni hisoblash uchun ma’lumot yetarli emas.", "Insufficient data to calculate the structure.")) + "."
        if profile:
            income_text += " " + financial_analysis_sector_language.tr(self.filing.lang, *profile["result"])

        expense_parts = []
        if period_expenses is not None:
            expense_key = "period_expenses" if value("period_expenses") is not None else "expenses" if value("expenses") is not None else "management_expenses"
            expense_parts.append(f"{financial_analysis_sector_language.label(expense_key, self.filing.lang)}: {money(expense_key)}" + (f" ({pct_text(pct(period_expenses, revenue))} {financial_analysis_sector_language.tr(self.filing.lang, 'доходов', 'daromadga nisbatan', 'of income')})" if pct(period_expenses, revenue) is not None else ""))
        for key in ("financial_income", "financial_expenses", "interest_expenses"):
            if value(key) is not None:
                expense_parts.append(f"{financial_analysis_sector_language.label(key, self.filing.lang)}: {money(key)}")
        if operating_income is not None:
            expense_parts.append(f"{financial_analysis_sector_language.label('operating_income', self.filing.lang)}: {money('operating_income')}" + (f" ({financial_analysis_sector_language.tr(self.filing.lang, 'операционная маржа', 'operatsion marja', 'operating margin')} {pct_text(pct(operating_income, revenue))})" if pct(operating_income, revenue) is not None else ""))
        if financial_result is not None:
            financial_text = financial_analysis_sector_language.tr(self.filing.lang, "чистый финансовый результат", "sof moliyaviy natija", "net finance result")
            if previous_financial_result is not None:
                expense_parts.append(f"{financial_text}: {self.display_money(previous_financial_result)} → {self.display_money(financial_result)} {self.money_unit}")
            else:
                expense_parts.append(f"{financial_text}: {self.display_money(financial_result)} {self.money_unit}")
        expense_text = financial_analysis_sector_language.tr(self.filing.lang, "Операционные и финансовые расходы. ", "Operatsion va moliyaviy xarajatlar. ", "Operating and finance costs. ") + ("; ".join(expense_parts) if expense_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно раскрытых данных.", "Oshkor qilingan ma’lumot yetarli emas.", "Insufficient disclosed data.")) + "."

        profit_parts = []
        if net_income is not None:
            profit_parts.append(f"{financial_analysis_sector_language.label('net_income', self.filing.lang)}: {money('net_income')}" + (f" ({financial_analysis_sector_language.tr(self.filing.lang, 'чистая маржа', 'sof marja', 'net margin')} {pct_text(pct(net_income, revenue))})" if pct(net_income, revenue) is not None else ""))
            movement = (self.evidence.by_code.get("net_income") or {}).get("change_pct")
            if movement is not None:
                profit_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"изменение к сопоставимому периоду — {financial_analysis_sector_language.format_number(movement)}%", f"taqqoslanadigan davrga nisbatan o‘zgarish — {financial_analysis_sector_language.format_number(movement)}%", f"change from the comparable period — {financial_analysis_sector_language.format_number(movement)}%"))
        if profit_before_tax is not None:
            profit_parts.append(f"{financial_analysis_sector_language.label('profit_before_tax', self.filing.lang)}: {money('profit_before_tax')}")
        effective_tax = pct(tax_amount, profit_before_tax)
        if tax_amount is not None:
            tax_basis = financial_analysis_sector_language.tr(self.filing.lang, "раскрытая строка", "oshkor qilingan satr", "disclosed line") if disclosed_tax is not None else financial_analysis_sector_language.tr(self.filing.lang, "расчётная разница до/после налога", "soliqdan oldingi/keyingi hisoblangan farq", "calculated pre/post-tax difference")
            profit_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"налог — {self.display_money(tax_amount)} {self.money_unit}, эффективная ставка — {pct_text(effective_tax) or 'не рассчитывается'} ({tax_basis})", f"soliq — {self.display_money(tax_amount)} {self.money_unit}, samarali stavka — {pct_text(effective_tax) or 'hisoblanmaydi'} ({tax_basis})", f"tax — {self.display_money(tax_amount)} {self.money_unit}, effective rate — {pct_text(effective_tax) or 'not calculable'} ({tax_basis})"))
        profit_text = financial_analysis_sector_language.tr(self.filing.lang, "Итоговая прибыль и налог. ", "Yakuniy foyda va soliq. ", "Final profit and tax. ") + ("; ".join(profit_parts) if profit_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно данных.", "Ma’lumot yetarli emas.", "Insufficient data.")) + "."

        profile_assets = profile["assets"] if profile else ("own_cash", "client_cash", "cash", "short_term_investments", "receivables") if self.filing.template == "commodity_exchange" else ("cash", "receivables", "inventories", "fixed_assets")
        asset_parts = [self.fact_sentence(key) for key in ("total_assets",) + tuple(profile_assets)]
        asset_parts = [item for item in asset_parts if item]
        asset_text = financial_analysis_sector_language.tr(self.filing.lang, "Активы и оборотный капитал. ", "Aktivlar va aylanma kapital. ", "Assets and working capital. ") + ("; ".join(asset_parts[:5]) if asset_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно данных.", "Ma’lumot yetarli emas.", "Insufficient data.")) + ". " + financial_analysis_sector_language.tr(self.filing.lang, "Рост доходов следует оценивать вместе с движением денег, дебиторской задолженности и запасов.", "Daromad o‘sishini pul, debitorlik va zaxiralar harakati bilan birga baholash kerak.", "Income growth should be assessed alongside cash, receivables and inventory movements.")

        funding_parts = [self.fact_sentence(key) for key in ("total_liabilities", "total_equity", "current_liabilities")]
        funding_parts = [item for item in funding_parts if item]
        debt_share = pct(value("total_liabilities"), value("total_assets"))
        if debt_share is not None:
            funding_parts.append(financial_analysis_sector_language.tr(self.filing.lang, f"обязательства составляют {pct_text(debt_share)} активов", f"majburiyatlar aktivlarning {pct_text(debt_share)}ini tashkil etadi", f"liabilities equal {pct_text(debt_share)} of assets"))
        funding_text = financial_analysis_sector_language.tr(self.filing.lang, "Капитал и обязательства. ", "Kapital va majburiyatlar. ", "Capital and liabilities. ") + ("; ".join(funding_parts) if funding_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно данных о структуре финансирования.", "Moliyalashtirish tarkibi haqida ma’lumot yetarli emas.", "Insufficient funding-structure data.")) + "."
        horizontal_text = asset_text + " " + funding_text
        assets = value("total_assets")
        vertical_keys = tuple(dict.fromkeys(tuple(profile_assets) + ("total_liabilities", "total_equity")))
        vertical_text = self.vertical_narrative(
            tuple(key for key in vertical_keys if key not in {"total_liabilities", "total_equity", "current_liabilities"}),
            financial_analysis_sector_language.tr(self.filing.lang, f"Для профиля «{sector_name}» важно оценить не перечень долей сам по себе, а концентрацию ресурсов и её изменение за период. ", f"«{sector_name}» profili uchun ulushlar ro‘yxatining o‘zi emas, balki resurslar jamlanishi va uning davr ichidagi o‘zgarishi muhim. ", f"For the {sector_name} profile, the key question is not the list of percentages itself but where resources are concentrated and how that changed. "),
            exchange_funding=self.filing.template == "commodity_exchange",
        )
        results_text = " ".join((income_text, expense_text, profit_text))
        ratio_parts = []
        for ratio_label, numerator in ((financial_analysis_sector_language.tr(self.filing.lang, "Валовая маржа", "Yalpi marja", "Gross margin"), gross), (financial_analysis_sector_language.tr(self.filing.lang, "Операционная маржа", "Operatsion marja", "Operating margin"), operating_income), (financial_analysis_sector_language.tr(self.filing.lang, "Чистая маржа", "Sof marja", "Net margin"), net_income)):
            calculated = pct(numerator, revenue)
            if calculated is not None:
                ratio_parts.append(f"{ratio_label} = {pct_text(calculated)}")
        if debt_share is not None:
            ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Обязательства / активы', 'Majburiyatlar / aktivlar', 'Liabilities / assets')} = {pct_text(debt_share)}")
        if self.filing.template in {"industry", "cement", "metallurgy", "extractive", "transport", "aviation", "telecom"}:
            fixed_asset_share = pct(value("fixed_assets"), assets)
            if fixed_asset_share is not None:
                ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Основные средства / активы', 'Asosiy vositalar / aktivlar', 'Fixed assets / assets')} = {pct_text(fixed_asset_share)}")
            construction_share = pct(value("construction_in_progress"), assets)
            if construction_share is not None:
                ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Незавершённые вложения / активы', 'Tugallanmagan investitsiyalar / aktivlar', 'Construction in progress / assets')} = {pct_text(construction_share)}")
        if self.filing.template == "trade":
            working_capital_share = pct(financial_analysis_sector_numbers.total(value("inventories"), value("receivables")), assets)
            if working_capital_share is not None:
                ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Запасы и дебиторка / активы', 'Zaxira va debitorlik / aktivlar', 'Inventory and receivables / assets')} = {pct_text(working_capital_share)}")
        if self.filing.template == "leasing":
            receivables_share = pct(value("receivables"), assets)
            if receivables_share is not None:
                ratio_parts.append(f"{financial_analysis_sector_language.tr(self.filing.lang, 'Дебиторская задолженность / активы', 'Debitorlik / aktivlar', 'Receivables / assets')} = {pct_text(receivables_share)}")
        ratio_text = financial_analysis_sector_language.tr(self.filing.lang, "Коэффициентный анализ. ", "Koeffitsiyentlar tahlili. ", "Ratio analysis. ") + ("; ".join(ratio_parts) if ratio_parts else financial_analysis_sector_language.tr(self.filing.lang, "Недостаточно компонентов для расчёта.", "Hisoblash komponentlari yetarli emas.", "Insufficient components for calculation.")) + "."
        summary_parts = []
        if revenue_change is not None and operating_change is not None and revenue_change > 0 > operating_change:
            summary_parts.append(financial_analysis_sector_language.tr(self.filing.lang, "Сильная сторона — рост выручки; основной риск — снижение операционной маржи.", "Kuchli tomon — tushum o‘sishi; asosiy xavf — operatsion marja pasayishi.", "The strength is revenue growth; the main risk is the lower operating margin."))
        if cash_change is not None and liabilities_change is not None and cash_change < 0 < liabilities_change:
            summary_parts.append(financial_analysis_sector_language.tr(self.filing.lang, "Снижение денег при росте обязательств усиливает риск ликвидности.", "Majburiyatlar o‘sib, pul kamayishi likvidlik xavfini kuchaytiradi.", "Falling cash alongside rising liabilities increases liquidity risk."))
        if profile:
            summary_parts.append(financial_analysis_sector_language.tr(self.filing.lang, *profile["risk"]))
        elif self.filing.template == "commodity_exchange":
            summary_parts.append(financial_analysis_sector_language.tr(self.filing.lang, "Для биржи ключевой вопрос — разделение собственных ресурсов и клиентских расчётов; без него высокая доля денег и обязательств не показывает ни ликвидность, ни долговую нагрузку компании сама по себе.", "Birja uchun asosiy masala — o‘z mablag‘lari va mijozlar hisob-kitoblarini ajratish; bunday ajratishsiz pul va majburiyatlarning yuqori ulushi kompaniyaning likvidligi yoki qarz yukini o‘z-o‘zidan ko‘rsatmaydi.", "For an exchange, the key issue is separating own resources from client settlements; without that split, high cash and liability shares do not by themselves establish corporate liquidity or leverage."))
        summary_text = financial_analysis_sector_language.tr(self.filing.lang, "Сводная оценка. ", "Yakuniy baho. ", "Summary assessment. ") + (" ".join(summary_parts) or financial_analysis_sector_language.tr(self.filing.lang, "Оценка ограничена раскрытыми показателями; ключевые изменения приведены выше.", "Baho oshkor qilingan ko‘rsatkichlar bilan cheklangan; asosiy o‘zgarishlar yuqorida keltirilgan.", "The assessment is limited to disclosed metrics; the key movements are shown above."))
        self.narrative_blocks["performance"] = [
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Выручка и прямые затраты", "Tushum va bevosita xarajatlar", "Revenue and direct costs"), "text": income_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Операционный и финансовый результат", "Operatsion va moliyaviy natija", "Operating and finance result"), "text": expense_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Чистая прибыль и налог", "Sof foyda va soliq", "Net profit and tax"), "text": profit_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Маржинальность и финансовая нагрузка", "Marjinallik va moliyaviy yuk", "Margins and financial load"), "text": ratio_text},
        ]
        self.narrative_blocks["position"] = [
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Динамика активов и обязательств", "Aktivlar va majburiyatlar dinamikasi", "Asset and liability movement"), "text": horizontal_text},
            {"lead": financial_analysis_sector_language.tr(self.filing.lang, "Концентрация активов и капитал", "Aktivlar jamlanishi va kapital", "Asset concentration and capital"), "text": vertical_text},
        ]
        return [intro, horizontal_text, vertical_text, results_text, ratio_text, summary_text]
