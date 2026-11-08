"""Only these existing production services can be requested by an administrator."""
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class Job:
    id: str
    title: str
    title_ru: str
    title_uz: str
    schedule: str

    @property
    def unit(self):
        return f"uzstock-{self.id}.service"

    def public(self):
        return {**asdict(self), "unit": self.unit,
                "run_command": f"sudo systemctl start --no-block {self.unit}",
                "logs_command": f"sudo journalctl --no-pager -n 200 _SYSTEMD_UNIT={self.unit} + UNIT={self.unit} + SYSLOG_IDENTIFIER=uzstock-{self.id}"}

JOBS = {job.id: job for job in [
    Job("collector", "Full collection", "Полный сбор", "To‘liq yig‘ish", "08:00 Mon–Fri"),
    Job("quotes-catchup", "Quotes", "Котировки", "Kotirovkalar", "09:30 daily; 16:10, 18:00, 21:30, 23:30 Mon–Sat"),
    Job("hourly-bars", "Intraday chart", "Внутридневной график", "Kunlik grafik", "11:05–16:05 hourly, Mon–Sat"),
    Job("reports-watch", "New filings", "Новые отчёты", "Yangi hisobotlar", "23:00 Mon–Sat"),
    Job("bank-history", "Bank history", "История банков", "Banklar tarixi", "07:00 daily"),
    Job("financial-ingestion", "Financial documents", "Финансовые документы", "Moliyaviy hujjatlar", "02:00 daily"),
    Job("bank-fx", "Bank exchange rates", "Курсы банков", "Bank kurslari", "11:10 daily"),
    Job("terminal-cbu", "Central Bank publications", "Публикации ЦБ", "Markaziy bank nashrlari", "06:30 daily"),
    Job("event-evidence", "Corporate disclosures", "Корпоративные раскрытия", "Korporativ ma’lumotlar", "19:20 daily"),
    Job("news-collector", "News", "Новости", "Yangiliklar", "16:10 daily"),
]}

# Keep historical results and queued requests addressable after merging schedules.
# Only JOBS are installed/observed; aliases never launch retired services.
ALIASES = {"quotes-1610": "quotes-catchup", "quotes-2130": "quotes-catchup"}


def canonical_id(job):
    return ALIASES.get(job, job)


def related_ids(job):
    current = canonical_id(job)
    return (current, *(old for old, target in ALIASES.items() if target == current))
