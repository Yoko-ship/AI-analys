from __future__ import annotations

import os
import re
import time
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from dotenv import load_dotenv
import openinfo_http
from uzse_parser import build_liquidity_df
from db import get_org_cache_path


load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────────────────

REQUEST_TIMEOUT = 30     # сек — таймаут HTTP запросов к API
ORG_CACHE_PATH = get_org_cache_path()


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session


def _normalize_company_key(value: str) -> str:
    value = (value or "").lower().strip()
    # Apostrophes are letter modifiers in Uzbek Latin names (O'zmetkombinat),
    # not word separators — drop them before splitting so the name stays one
    # token instead of degrading into {o, zmetkombinat}.
    value = re.sub(r"[''`ʼ’ʻ]", "", value)
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


# Legal-form and generic corporate words that appear in almost every issuer
# name. They carry no identity, so they never count toward a fuzzy match —
# otherwise "Акционерное общество «X»" matches every other акционерное общество.
_GENERIC_NAME_TOKENS = {
    # uz latin legal forms / fillers
    "aj", "oaj", "yoaj", "atb", "atib", "akb", "xatb", "mchj", "xk", "ak", "mmt",
    "aksiyadorlik", "jamiyati", "jamiyat", "tijorat", "banki", "bank",
    "kompaniyasi", "kompaniya", "korxonasi", "korxona", "shirkati",
    "ochiq", "yopiq", "turdagi", "chet", "el", "kapitali", "ishtirokidagi",
    # ru
    "ао", "оао", "зао", "ооо", "акб", "чаб", "аж", "ат",
    "акционерное", "акционерный", "общество", "обществo", "коммерческий",
    "банк", "банка", "компания",
}


def _meaningful_tokens(normalized: str) -> set[str]:
    return {t for t in normalized.split() if len(t) >= 2 and t not in _GENERIC_NAME_TOKENS}


def _load_org_cache() -> dict:
    if not ORG_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(ORG_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_org_cache(cache: dict) -> None:
    ORG_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# A wrong resolution must not live forever: entries expire so they get
# re-resolved against current matching rules. Legacy entries without a
# timestamp are treated as expired — that alone purges historical poison.
ORG_CACHE_TTL_DAYS = int(os.getenv("ORG_CACHE_TTL_DAYS", "30"))


def _get_cached_org_id(user_input: str) -> tuple[str, str] | None:
    cache = _load_org_cache()
    item = cache.get(_normalize_company_key(user_input))
    if not item:
        return None
    cached_at = item.get("cached_at")
    if not cached_at or (time.time() - float(cached_at)) > ORG_CACHE_TTL_DAYS * 86400:
        return None
    org_id = item.get("org_id")
    company_name = item.get("company_name")
    if org_id and company_name:
        logger.info(f"org_id взят из кэша: {org_id} ({company_name})")
        return org_id, company_name
    return None


def _store_org_id_cache(user_input: str, org_id: str, company_name: str) -> None:
    cache = _load_org_cache()
    payload = {"org_id": org_id, "company_name": company_name, "cached_at": time.time()}
    for key in {_normalize_company_key(user_input), _normalize_company_key(company_name)}:
        if key:
            cache[key] = payload
    _save_org_cache(cache)


def _fetch_api_bundle(urls: dict[str, str]) -> dict[str, dict | list]:
    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        futures = {
            name: executor.submit(_api_get, url)
            for name, url in urls.items()
        }
        return {
            name: future.result()
            for name, future in futures.items()
        }


def _lookup_org_id_via_api(user_input: str) -> tuple[str, str] | None:
    """
    Пытается найти org_id через несколько стратегий:
    1. Autofill API с различными вариантами написания
    2. Поиск по индексам отчётов и дивидендов (страховка, если autofill потерял запись)
    3. Полный список организаций с fuzzy matching
    """
    normalized_input = _normalize_company_key(user_input)

    # Генерируем все варианты поиска
    variants = _get_search_variants(user_input)
    logger.debug(f"Варианты поиска для '{user_input}': {variants}")

    # Стратегия 1: Autofill API с разными вариантами
    for variant in variants:
        result = _try_autofill_api(variant, _normalize_company_key(variant))
        if result:
            return result

    # Стратегия 2: Поиск по первому слову — только если это слово несёт смысл.
    # Первое слово вроде «Акционерное» совпадает с сотнями компаний и раньше
    # закрепляло в кэше первую попавшуюся организацию.
    first_word = user_input.split()[0] if user_input.split() else user_input
    first_norm = _normalize_company_key(first_word)
    if first_word != user_input and first_norm and _meaningful_tokens(first_norm):
        first_variants = _get_search_variants(first_word)
        for variant in first_variants:
            result = _try_autofill_api(variant, _normalize_company_key(variant))
            if result:
                return result

    # Стратегия 3: индексы отчётов/дивидендов (autofill иногда теряет тикеры)
    for variant in variants:
        result = _try_secondary_indexes(variant)
        if result:
            return result

    # Стратегия 4: Полный список организаций с fuzzy matching
    logger.info("Autofill и индексы не нашли, загружаем полный список организаций...")
    result = _search_in_full_org_list(user_input, normalized_input)
    if result:
        return result

    return None


# Minimum _calc_match_score for a search hit to be accepted as "this company".
# The same floor the full-org-list path uses: shared generic tokens alone never
# clear it, only an exact match, a substring, or every meaningful query word
# present in the name. Below it the resolver reports failure instead of caching
# whatever the search engine happened to rank first.
SECONDARY_INDEX_MATCH_FLOOR = float(os.getenv("ORG_MATCH_FLOOR", "10.0"))


def _ticket_names(item: dict) -> set[str]:
    """Tickers openinfo lists for an organization ('AGMK,AGMKP' -> {agmk, agmkp}).

    An exact ticker hit is the strongest identity signal these endpoints carry —
    stronger than any name similarity — because it comes from the issuer's own
    registered symbol list rather than from a text search.
    """
    raw = item.get("organization_ticket_name") or item.get("ticket_name") or ""
    return {t.strip().lower() for t in str(raw).split(",") if t.strip()}


def _try_secondary_indexes(query: str) -> tuple[str, str] | None:
    """Fallback search via /reports/main/ and /disclosure/dividend-calendar/.

    Both endpoints index issuers by ticker/name and expose organization id +
    organization_name, which is enough to keep the analysis pipeline running
    even when /home/autofill/ stops returning a particular ticker.

    These are *text search* endpoints: they answer "documents matching these
    words", not "the company with this identity". Taking their first row on faith
    is what produced the historic wrong-company ingestions (KVTS/BIOK) — a search
    for one issuer returns another's filing, the org id gets cached under the
    query, and every later lookup inherits it. So a hit is only accepted when it
    either carries the queried ticker outright or clears the same name-similarity
    floor as the full-org-list path, and the best candidate on the page wins
    rather than the first.
    """
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    sources = [
        ("reports/main", "https://new-api.openinfo.uz/api/v2/reports/main/",
         {"page_size": 10, "search": query}, "organization", "organization_name"),
        ("dividend-calendar", "https://new-api.openinfo.uz/api/v2/disclosure/dividend-calendar/",
         {"page_size": 10, "search": query}, "organization_id", "organization"),
    ]
    normalized_query = _normalize_company_key(query)
    query_ticker = query.strip().lower()
    for label, url, params, id_key, name_key in sources:
        try:
            response = openinfo_http.get(url, params=params, headers=headers,
                                         timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning(f"Fallback {label} ошибка: {exc}")
            continue

        results = payload.get("results", []) if isinstance(payload, dict) else []
        best: tuple[float, str, str] | None = None
        for item in results:
            org_id = item.get(id_key)
            name = item.get(name_key)
            if org_id is None or not name:
                continue
            org_id = str(org_id).strip()
            name = str(name).strip()
            if not org_id or not name:
                continue
            if query_ticker and query_ticker in _ticket_names(item):
                score = 100.0  # the issuer's own registered symbol — unambiguous
            else:
                score = _calc_match_score(normalized_query, _normalize_company_key(name))
            if best is None or score > best[0]:
                best = (score, org_id, name)

        if best is None:
            continue
        score, org_id, name = best
        if score < SECONDARY_INDEX_MATCH_FLOOR:
            logger.info(
                "Fallback %s: лучший результат «%s» (org %s) не проходит порог "
                "совпадения (%.1f < %.1f) — пропускаем, чтобы не закрепить чужую компанию",
                label, name, org_id, score, SECONDARY_INDEX_MATCH_FLOOR,
            )
            continue
        logger.info(f"org_id найден через {label} (score={score:.1f}): {org_id} ({name})")
        _store_org_id_cache(query, org_id, name)
        return org_id, name
    return None


# Таблица транслитерации кириллицы в латиницу (основной вариант)
_TRANSLIT_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'j', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sh', 'ъ': '',
    'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'ў': "o'", 'қ': 'q', 'ғ': "g'", 'ҳ': 'h',
}

# Альтернативные варианты транслитерации для fuzzy поиска
_TRANSLIT_ALTERNATIVES = {
    'х': ['h', 'x', 'kh'],  # Хамкор -> Hamkor, Xamkor, Khamkor
    'ж': ['j', 'zh'],
    'ш': ['sh', 'sch'],
    'ч': ['ch', 'tch'],
    'й': ['y', 'i', 'j'],
    'ю': ['yu', 'iu', 'u'],
    'я': ['ya', 'ia', 'a'],
    'е': ['e', 'ye'],
    'ё': ['yo', 'e', 'io'],
}


def _transliterate_to_latin(text: str) -> str:
    """Транслитерация кириллицы в латиницу (узбекский стиль)."""
    result = []
    for char in text:
        lower = char.lower()
        if lower in _TRANSLIT_MAP:
            mapped = _TRANSLIT_MAP[lower]
            result.append(mapped.upper() if char.isupper() else mapped)
        else:
            result.append(char)
    return "".join(result)


# Словарь общих слов с известным переводом (кириллица -> латиница)
_COMMON_WORDS = {
    'авто': 'auto', 'банк': 'bank', 'телеком': 'telecom', 'газ': 'gaz',
    'нефть': 'neft', 'электро': 'elektro', 'пром': 'prom', 'строй': 'stroy',
    'транс': 'trans', 'агро': 'agro', 'фарм': 'farm', 'текстиль': 'tekstil',
}


def _get_search_variants(text: str) -> list[str]:
    """Генерирует варианты поиска для лучшего fuzzy matching."""
    variants = [text]

    # Добавляем транслитерированный вариант
    translit = _transliterate_to_latin(text)
    if translit != text:
        variants.append(translit)

    # Заменяем общие слова на известные варианты и транслитерируем остальное
    text_lower = text.lower()
    for rus, eng in _COMMON_WORDS.items():
        if rus in text_lower:
            # Сначала заменяем общее слово, потом транслитерируем остальное
            replaced = text_lower.replace(rus, eng)
            # Теперь транслитерируем оставшуюся кириллицу
            fully_latin = _transliterate_to_latin(replaced)
            if fully_latin not in [v.lower() for v in variants]:
                variants.append(fully_latin)

    # Добавляем варианты с альтернативной транслитерацией
    for cyrillic, alternatives in _TRANSLIT_ALTERNATIVES.items():
        if cyrillic in text.lower():
            for alt in alternatives[1:]:  # Пропускаем первый (основной) вариант
                alt_text = ""
                for char in text:
                    if char.lower() == cyrillic:
                        replacement = alt.upper() if char.isupper() else alt
                        alt_text += replacement
                    else:
                        lower = char.lower()
                        if lower in _TRANSLIT_MAP:
                            mapped = _TRANSLIT_MAP[lower]
                            alt_text += mapped.upper() if char.isupper() else mapped
                        else:
                            alt_text += char
                if alt_text not in variants:
                    variants.append(alt_text)

    # Варианты без дефисов и апострофов
    for v in variants[:]:
        clean = v.replace("-", " ").replace("'", "").replace("`", "")
        if clean not in variants:
            variants.append(clean)

    return variants[:6]  # Максимум 6 вариантов


def _try_autofill_api(query: str, normalized_query: str) -> tuple[str, str] | None:
    """Поиск через autofill endpoint."""
    url = "https://new-api.openinfo.uz/api/v2/home/autofill/"
    try:
        response = openinfo_http.get(
            url,
            params={"name": query},
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        items = response.json()
    except Exception as exc:
        logger.warning(f"Autofill API ошибка: {exc}")
        return None

    if not items:
        logger.debug(f"Autofill API: пустой результат для '{query}'")
        return None

    best_item = _find_best_match(items, normalized_query)
    if not best_item:
        return None

    org_id = str(best_item["id"])
    company_name = str(best_item.get("full_name_text", "")).strip()
    logger.info(f"org_id получен через autofill API: {org_id} ({company_name})")
    _store_org_id_cache(query, org_id, company_name)
    return org_id, company_name


# Кэш полного списка организаций (загружается один раз).
# Хранится в APP_DATA_DIR (как остальные кэши), а не в текущей директории —
# путь больше не зависит от того, откуда запущен процесс.
_FULL_ORG_LIST: list | None = None
_FULL_ORG_LIST_PATH = (
    Path(os.getenv("FULL_ORG_LIST_CACHE_PATH")).expanduser()
    if os.getenv("FULL_ORG_LIST_CACHE_PATH")
    else ORG_CACHE_PATH.parent / "full_org_list_cache.json"
)


def _load_full_org_list() -> list:
    """Загружает полный список организаций (из кэша или API)."""
    global _FULL_ORG_LIST

    if _FULL_ORG_LIST is not None:
        return _FULL_ORG_LIST

    # Пробуем загрузить из файлового кэша
    if _FULL_ORG_LIST_PATH.exists():
        try:
            cache_data = json.loads(_FULL_ORG_LIST_PATH.read_text(encoding="utf-8"))
            # Кэш валиден 24 часа
            if time.time() - cache_data.get("timestamp", 0) < 86400:
                _FULL_ORG_LIST = cache_data.get("organizations", [])
                logger.info(f"Список организаций загружен из кэша: {len(_FULL_ORG_LIST)} записей")
                return _FULL_ORG_LIST
        except Exception as exc:
            logger.warning(f"Не удалось загрузить кэш организаций: {exc}")

    # Загружаем из API
    logger.info("Загружаем полный список организаций из API...")
    all_orgs = []
    page = 1
    max_pages = 50  # Защита от бесконечного цикла

    while page <= max_pages:
        try:
            response = openinfo_http.get(
                "https://new-api.openinfo.uz/api/v2/home/organizations/",
                params={"page": page, "page_size": 100},
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            all_orgs.extend(results)

            if not data.get("next"):
                break
            page += 1
        except Exception as exc:
            logger.error(f"Ошибка загрузки списка организаций (страница {page}): {exc}")
            break

    logger.info(f"Загружено {len(all_orgs)} организаций из API")

    # Сохраняем в кэш
    if all_orgs:
        try:
            _FULL_ORG_LIST_PATH.write_text(
                json.dumps({"timestamp": time.time(), "organizations": all_orgs}, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as exc:
            logger.warning(f"Не удалось сохранить кэш организаций: {exc}")

    _FULL_ORG_LIST = all_orgs
    return _FULL_ORG_LIST


def _search_in_full_org_list(query: str, normalized_query: str) -> tuple[str, str] | None:
    """Fuzzy поиск по полному списку организаций."""
    orgs = _load_full_org_list()
    if not orgs:
        return None

    # Генерируем все варианты запроса для поиска
    query_variants = _get_search_variants(query)
    normalized_variants = [_normalize_company_key(v) for v in query_variants]

    best_item = None
    best_score = 0.0

    for org in orgs:
        full_name = str(org.get("full_name_text", "") or org.get("name", "")).strip()
        org_id = org.get("id")
        if not full_name or org_id is None:
            continue

        normalized_name = _normalize_company_key(full_name)

        # Считаем score по всем вариантам запроса
        score = 0.0
        for nv in normalized_variants:
            score = max(score, _calc_match_score(nv, normalized_name))

        if score > best_score:
            best_score = score
            best_item = org

    # Floor: общие токены сами по себе не проходят — нужен структурный сигнал
    # (точное совпадение, подстрока или все значимые слова запроса в названии).
    # Раньше порог 2.0 = одно общее слово, и «O'z…» совпадал с любой «O'z…».
    if best_item and best_score >= 10.0:
        org_id = str(best_item["id"])
        company_name = str(best_item.get("full_name_text", "")).strip()
        logger.info(f"org_id найден в полном списке (score={best_score:.1f}): {org_id} ({company_name})")
        _store_org_id_cache(query, org_id, company_name)
        return org_id, company_name

    return None


def _calc_match_score(query_normalized: str, name_normalized: str) -> float:
    """Вычисляет score совпадения между запросом и названием.

    Учитываются только значимые токены — юридические формы («AJ», «банк»,
    «акционерное») не считаются совпадением.
    """
    if not query_normalized or not name_normalized:
        return 0.0

    score = 0.0
    query_tokens = _meaningful_tokens(query_normalized)
    name_tokens = _meaningful_tokens(name_normalized)

    common = query_tokens & name_tokens
    score += len(common) * 2  # 2 очка за каждое значимое совпадающее слово

    if query_normalized == name_normalized:
        score += 100
    elif query_normalized in name_normalized:
        score += 20
    elif name_normalized in query_normalized:
        score += 10

    # Бонус: все значимые слова запроса найдены в названии
    if query_tokens and query_tokens <= name_tokens:
        score += 15

    return score


def _find_best_match(items: list, normalized_input: str) -> dict | None:
    """Находит лучшее совпадение по нормализованному имени."""
    best_item = None
    best_score = -1.0

    for item in items:
        full_name = str(item.get("full_name_text", "") or item.get("name", "")).strip()
        org_id = item.get("id") or item.get("org_id")
        if not full_name or org_id is None:
            continue
        normalized_name = _normalize_company_key(full_name)
        score = 0.0
        if normalized_input and normalized_name:
            input_tokens = _meaningful_tokens(normalized_input)
            name_tokens = _meaningful_tokens(normalized_name)
            common_tokens = input_tokens & name_tokens
            score = len(common_tokens)
            if normalized_input == normalized_name:
                score += 100
            elif normalized_input in normalized_name or normalized_name in normalized_input:
                score += 10
            # Бонус если все значимые слова запроса найдены
            if input_tokens and input_tokens <= name_tokens:
                score += 5
        if score > best_score:
            best_score = score
            best_item = item

    # /home/autofill/ игнорирует параметр поиска и возвращает ПОЛНЫЙ список
    # организаций, поэтому «доверять autofill» при нулевом скоре — значит взять
    # произвольную первую компанию. Принимаем только структурное совпадение.
    if best_item and best_score >= 6.0:
        return best_item
    return None


# ─────────────────────────────────────────────────────────
# Создание драйвера (headless — работает и локально и на сервере)
# ─────────────────────────────────────────────────────────

def _scrape_org_id(user_input: str) -> tuple[str, str]:
    from collectors.openinfo.browser import _scrape_org_id as scrape

    org_id, company_name = scrape(user_input)
    _store_org_id_cache(user_input, org_id, company_name)
    return org_id, company_name


def _api_get(url: str, session: requests.Session | None = None) -> dict | list:
    """HTTP GET с таймаутом и понятной ошибкой."""
    try:
        client = session or openinfo_http.shared_session()
        resp = client.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.debug(f"API response from {url}: {type(data).__name__}, len={len(data) if isinstance(data, (list, dict)) else 'N/A'}")
        return data
    except requests.exceptions.Timeout:
        logger.error(f"Таймаут запроса к API: {url}")
        return [] if "accounting-report" in url else {}
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка API запроса {url}: {e}")
        return [] if "accounting-report" in url else {}


# ─────────────────────────────────────────────────────────
# Парсеры
# ─────────────────────────────────────────────────────────

def _parse_annual(data: list) -> list[dict]:
    result = []
    if not data:
        logger.debug("_parse_annual: входные данные пусты")
        return result

    for report in data:
        year = report.get("reporting_year")
        accounting_report = report.get("accounting_report", [])

        if not accounting_report:
            # Попробуем альтернативные ключи
            accounting_report = report.get("data", []) or report.get("items", []) or report.get("results", [])
            if accounting_report:
                logger.info(f"Найдены данные в альтернативном ключе для года {year}")

        if not accounting_report:
            logger.debug(f"Нет accounting_report для года {year}. Ключи: {list(report.keys())}")
            continue

        for item in accounting_report:
            value = item.get("value")
            # Пробуем альтернативные ключи для значения
            if value is None:
                value = item.get("amount") or item.get("sum") or item.get("total")
            result.append({
                "reporting_year": year,
                "title":          item.get("title") or item.get("name") or item.get("label"),
                "value":          value,
            })
    return result


def _parse_quarter(data: list) -> list[dict]:
    result = []
    if not data:
        logger.debug("_parse_quarter: входные данные пусты")
        return result

    for report in data:
        year = report.get("reporting_year")
        accounting_report = report.get("accounting_report", [])

        if not accounting_report:
            accounting_report = report.get("data", []) or report.get("items", []) or report.get("results", [])

        if not accounting_report:
            logger.debug(f"Нет квартальных данных для года {year}")
            continue

        for item in accounting_report:
            title = item.get("title") or item.get("name") or item.get("label")
            for q, value in enumerate(
                [item.get(f"value{i}") for i in range(1, 5)], start=1
            ):
                if value is not None and value != 0:
                    result.append({
                        "reporting_year": year,
                        "quarter":        q,
                        "title":          title,
                        "value":          value,
                    })
    return result


# ─────────────────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────────────────

def get_data(user_input: str | None = None):
    if user_input is None:
        user_input = input("Название компании: ").strip()
    else:
        user_input = user_input.strip()
    if not user_input:
        raise ValueError("Название компании не может быть пустым")

    # 1. Получаем org_id: сначала кэш, потом autofill API, затем Selenium как fallback
    cached_org = _get_cached_org_id(user_input)
    if cached_org:
        org_id, company_name = cached_org
    else:
        api_org = _lookup_org_id_via_api(user_input)
        if api_org:
            org_id, company_name = api_org
        else:
            org_id, company_name = _scrape_org_id(user_input)

    # 2. Формируем URL
    base = f"https://new-api.openinfo.uz/api/v2/reports/accounting-report/{org_id}/"
    urls = {
        "income_annual":   base + "?accounting_type=form2&report_type=annual",
        "balance_annual":  base + "?accounting_type=form1&report_type=annual",
        "income_quarter":  base + "?accounting_type=form2&report_type=quarter",
        "balance_quarter": base + "?accounting_type=form1&report_type=quarter",
        "efficiency":      f"https://new-api.openinfo.uz/api/v2/reports/financial_indicators/?organization_id={org_id}",
    }

    # 3. Скачиваем данные
    logger.info("Запрашиваю данные с API...")
    with ThreadPoolExecutor(max_workers=2) as executor:
        bundle_future = executor.submit(_fetch_api_bundle, urls)
        liquidity_future = executor.submit(
            build_liquidity_df, user_input, company_name, False
        )
        bundle = bundle_future.result()
        try:
            liquidity_df = liquidity_future.result()
        except Exception as exc:
            logger.warning(f"Не удалось получить ликвидность с UZSE: {exc}")
            liquidity_df = pd.DataFrame()

    incomes_annual  = bundle["income_annual"]
    balance_annual  = bundle["balance_annual"]
    incomes_quarter = bundle["income_quarter"]
    balance_quarter = bundle["balance_quarter"]
    efficiency      = bundle["efficiency"]

    # Debug: если данных нет, сохраняем сырой ответ API для диагностики
    all_empty = not incomes_annual and not balance_annual and not incomes_quarter and not balance_quarter
    if all_empty:
        debug_path = Path("debug_api_response.json")
        debug_data = {
            "org_id": org_id,
            "company_name": company_name,
            "urls": urls,
            "responses": {
                "income_annual": incomes_annual,
                "balance_annual": balance_annual,
                "income_quarter": incomes_quarter,
                "balance_quarter": balance_quarter,
                "efficiency": efficiency,
            }
        }
        debug_path.write_text(json.dumps(debug_data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning(f"API вернул пустые данные. Диагностика сохранена в {debug_path.absolute()}")

    # Логируем что получили от API
    logger.info(f"API ответы - annual income: {len(incomes_annual)} записей, annual balance: {len(balance_annual)} записей")
    logger.info(f"API ответы - quarter income: {len(incomes_quarter)} записей, quarter balance: {len(balance_quarter)} записей")

    # 4. Собираем DataFrames
    annual_income_parsed = _parse_annual(incomes_annual)
    annual_balance_parsed = _parse_annual(balance_annual)

    if not annual_income_parsed and not annual_balance_parsed:
        logger.warning(f"Нет годовых данных для org_id={org_id}. Возможно, компания использует другой формат отчётности.")

    annual_df = pd.concat([
        pd.DataFrame(annual_income_parsed),
        pd.DataFrame(annual_balance_parsed),
    ], ignore_index=True)

    if not annual_df.empty:
        annual_df = annual_df.sort_values("reporting_year")

    quarter_income_parsed = _parse_quarter(incomes_quarter)
    quarter_balance_parsed = _parse_quarter(balance_quarter)

    quarter_df = pd.concat([
        pd.DataFrame(quarter_income_parsed),
        pd.DataFrame(quarter_balance_parsed),
    ], ignore_index=True)

    if not quarter_df.empty:
        quarter_df = quarter_df.sort_values(["reporting_year", "quarter"])

    # 5. Присоединяем коэффициенты эффективности
    efficiency_results = efficiency.get("results", []) if isinstance(efficiency, dict) else []
    efficiency_df = pd.DataFrame(efficiency_results)
    if not efficiency_df.empty and not annual_df.empty:
        annual_df = annual_df.merge(efficiency_df, on="reporting_year", how="left")

    logger.info(f"Данные получены: {len(annual_df)} строк годовых, {len(quarter_df)} квартальных")

    if annual_df.empty and quarter_df.empty:
        logger.warning(f"Данные не найдены для '{company_name}' (org_id={org_id}). Проверьте наличие отчётов на openinfo.uz")

    return annual_df, quarter_df, liquidity_df, company_name


# ─────────────────────────────────────────────────────────
# Запуск напрямую
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    annual_data, quarter_data, liquidity_data, company = get_data()

    print(f"\nКомпания: {company}")
    print("\n=== ГОДОВЫЕ ДАННЫЕ ===")
    print(annual_data.head())
    print("\n=== КВАРТАЛЬНЫЕ ДАННЫЕ ===")
    print(quarter_data.head())
    if liquidity_data is not None and not liquidity_data.empty:
        print("\n=== ЛИКВИДНОСТЬ АКЦИИ ===")
        print(liquidity_data.to_string(index=False))

    # annual_data.to_excel("annual_data.xlsx", index=False)
    # quarter_data.to_excel("quarter_data.xlsx", index=False)
