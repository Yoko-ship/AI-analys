"""A single frozen counting basis shared by the report's metric families."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from .analytics_config import AnalyticsSettings, FORMULA_VERSION
from .errors import MarketingError
from .metrics import metric
from .permissions import TASHKENT, timestamp
from .report_coverage import CATEGORY_KINDS, CoverageLedger
from . import acquisition, financial_integrity, metric_windows

FINANCIAL = {"payment", "refund", "subscription", "cancellation"}


class ReportContext:
    def __init__(self, events, *, starts_on, ends_on, cutoff, settings, coverage_records=None):
        self.settings = AnalyticsSettings.model_validate(settings).model_dump(mode="json")
        self.start = datetime.combine(date.fromisoformat(starts_on), datetime.min.time(), TASHKENT)
        self.end = datetime.combine(date.fromisoformat(ends_on), datetime.min.time(), TASHKENT)
        self.cut = timestamp(cutoff)
        if self.end <= self.start or self.end - self.start > timedelta(days=366) or self.cut < self.start:
            raise MarketingError("INVALID_PERIOD", "Choose an ordered period of at most one year and a cutoff after its start.", 422)
        self.period = {"starts_on": starts_on, "ends_on": ends_on, "timezone": "Asia/Tashkent", "cutoff": cutoff}
        self.coverage_ledger = CoverageLedger(coverage_records, self.settings['dataset'], self.cut) if coverage_records is not None else None
        self.coverage = {}
        if self.coverage_ledger is not None:
            for source in CATEGORY_KINDS:
                basis = self.coverage_ledger.assess(source, self.start, min(self.end, self.cut), end_inclusive=self.cut < self.end)
                self.settings['source_status'][source] = basis['status']
                self.coverage[source] = basis['confirmation']
        raw = [e for e in events if e["dataset"] == self.settings["dataset"] and timestamp(e["at"]) <= self.cut]
        self.excluded = sum(e["traffic"] != "external" for e in raw)
        self.events = [e for e in raw if e["traffic"] == "external" and e["confirmed"]]
        self.period_events = [e for e in self.events if self.contains(e)]
        self.by_kind = defaultdict(list)
        self.by_subject = defaultdict(list)
        for e in self.period_events:
            self.by_kind[e["kind"]].append(e)
        for e in self.events:
            if e["subject_id"]:
                self.by_subject[e["subject_id"]].append(e)
        self.registrations = {}
        for e in self.events:
            if e["kind"] == "registration":
                self.registrations.setdefault(e["subject_id"], e)
        self.cohort = {key: e for key, e in self.registrations.items() if self.contains(e)}
        self.acquisition = {subject: acquisition.resolve(self.by_subject[subject], registration, self.settings['attribution_days'])
                            for subject, registration in self.registrations.items()}
        self.touches = {subject: value['touch'] for subject, value in self.acquisition.items()}
        self.channels = {subject: value['channel'] for subject, value in self.acquisition.items()}
        self.live = self.settings["monetization_live"] and any(self._launched(entity, min(self.end, self.cut)) for entity in self.settings["legal_entities"])
        self.finance = [e for e in self.events if e["kind"] in FINANCIAL and self._launched(e["legal_entity"], timestamp(e["at"]))]
        self.excluded_financial = [e["id"] for e in self.events if e["kind"] in FINANCIAL and e not in self.finance]
        self.financial_issues = financial_integrity.audit(self)
        self.first, self.entity_first = {}, {}
        for e in self.finance:
            if e["kind"] == "payment" and e["payment_type"] == "first" and e['amount'] > 0:
                self.first.setdefault(e["subject_id"], e)
                self.entity_first.setdefault((e["legal_entity"], e["subject_id"]), e)
        self.paid_period = {key: e for key, e in self.first.items() if self.contains(e)}
        self.paid_cohort = {key: e for key, e in self.first.items() if key in self.cohort
                            and timestamp(self.cohort[key]["at"]) <= timestamp(e["at"]) <= timestamp(self.cohort[key]["at"]) + timedelta(days=self.settings["conversion_days"])}
        self.expenses = [e for e in self.by_kind["expense"] if e["currency"] == self.settings["currency"]]
        self.scope = set(self.settings["acquisition_channels"]) or {e["channel"] for e in self.expenses if e["channel"] not in {"unknown", "direct", ""} and e["category"] == "advertising"}

    def contains(self, event):
        return self.start <= timestamp(event["at"]) < self.end

    def _launched(self, entity, at):
        value = self.settings["entity_launches"].get(entity)
        return self.settings["monetization_live"] and entity in self.settings["legal_entities"] and value and timestamp(value) <= at

    def channel(self, subject):
        return self.channels.get(subject, "unknown")

    def mature(self, cohort, days):
        return self.cut >= self.end and all(timestamp(event["at"]) + timedelta(days=days) <= self.cut for event in cohort.values())

    def source_basis(self, key, sources):
        if self.coverage_ledger is None:
            return {source: {'status': self.settings['source_status'].get(source, 'unavailable')} for source in sources}
        return {source: self.coverage_ledger.assess(source, **metric_windows.required(self, key, source)) for source in sources}

    def measure(self, key, numerator=None, denominator=None, *, inputs, sources=(), reference_sources=(), monetized=False, ratio=False,
                status="complete", reason="", estimate=False, unique_customers=False):
        coverage = self.source_basis(key, sources)
        statuses = [basis['status'] for basis in coverage.values()]
        attribution = acquisition.assess(self, key) if key in acquisition.METRICS else None
        if attribution and attribution['status'] != 'complete' and status not in {'unavailable', 'not_applicable', 'not_comparable'}:
            status = 'incomplete'
            reason = 'Не подтверждён источник привлечения для части применимых клиентов. ' + ' '.join(row['message'] for row in attribution['reasons'])
            if key in {'roi', 'roas', 'payback'}:
                numerator = None
            if key in {'registration_cost', 'advertising_cac', 'full_cac', 'payback'}:
                denominator = None
        issues = financial_integrity.metric_issues(self.financial_issues, key)
        if issues:
            status, reason = 'unavailable', ' '.join(dict.fromkeys(issue['message'] for issue in issues))
        if monetized and not self.live:
            status, reason = "not_applicable", "Монетизация и применимая форма ещё не запущены."
        elif unique_customers and not self.settings["shared_customer_ids"]:
            status, reason = "not_comparable", "Нет согласованного общего идентификатора клиента; смотрите формы отдельно."
        elif status in {'unavailable', 'not_applicable', 'not_comparable'}:
            pass
        elif any(value in {"unavailable", "not_connected"} for value in statuses):
            status, reason = "unavailable", "Нет подтверждённой полноты обязательных источников."
        elif any(value == "incomplete" for value in statuses) or (monetized and self.excluded_financial):
            status, reason = "incomplete", "Данные неполны либо есть операции вне подтверждённой формы и даты запуска."
        if status in {"unavailable", "not_applicable", "not_comparable"}:
            numerator = denominator = None
        result = metric(key, numerator, denominator, ratio=ratio, status=status, reason=reason,
                        multiplier=100 if ratio and key in {"activation", "retention", "churn", "ctr", "visit_to_registration", "registration_to_payment", "roi"} else 1)
        inputs = list(inputs)
        if attribution:
            inputs.extend(acquisition.proof_inputs(self, key))
        blocking_ids = {event_id for issue in issues for event_id in issue['event_ids']}
        if monetized:
            blocking_ids.update(self.excluded_financial)
        inputs.extend(row for row in self.events if row['id'] in blocking_ids)
        result.update(sources=list(sources), source_ids=sorted({e['source'] for e in inputs} | set(reference_sources)), currency=self.settings["currency"] if result["unit"] == "currency" else None,
                      period=self.period, definition_version=FORMULA_VERSION, updated_at=max((e["at"] for e in inputs), key=timestamp, default=None), estimate=estimate)
        if self.coverage_ledger is not None:
            result['coverage'] = coverage
        if attribution:
            result['attribution'] = attribution
        return result

    def financial_events(self, kind, *, period=True):
        return [e for e in self.finance if e["kind"] == kind and e["currency"] == self.settings["currency"] and (not period or self.contains(e))]

    def monthly(self):
        return self.start.day == 1 and self.end.day == 1 and (self.end.year * 12 + self.end.month) - (self.start.year * 12 + self.start.month) == 1 and self.cut >= self.end
