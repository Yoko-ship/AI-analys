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

try:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from seleniumwire import webdriver
    SELENIUM_AVAILABLE = True
except Exception:
    By = None
    WebDriverWait = None
    EC = None
    webdriver = None
    SELENIUM_AVAILABLE = False

load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────────────────

MAX_RETRIES    = 3       # попытки при падении браузера
PAGE_TIMEOUT   = 20      # сек — ждём элементы на странице
REQUEST_TIMEOUT = 30     # сек — таймаут HTTP запросов к API
ORG_CACHE_PATH = get_org_cache_path()


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session


def _normalize_company_key(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


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


def _get_cached_org_id(user_input: str) -> tuple[str, str] | None:
    cache = _load_org_cache()
    item = cache.get(_normalize_company_key(user_input))
    if not item:
        return None
    org_id = item.get("org_id")
    company_name = item.get("company_name")
    if org_id and company_name:
        logger.info(f"org_id взят из кэша: {org_id} ({company_name})")
        return org_id, company_name
    return None


def _store_org_id_cache(user_input: str, org_id: str, company_name: str) -> None:
    cache = _load_org_cache()
    payload = {"org_id": org_id, "company_name": company_name}
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

    # Стратегия 2: Поиск по первому слову
    first_word = user_input.split()[0] if user_input.split() else user_input
    if first_word != user_input:
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


def _try_secondary_indexes(query: str) -> tuple[str, str] | None:
    """Fallback search via /reports/main/ and /disclosure/dividend-calendar/.

    Both endpoints index issuers by ticker/name and expose organization id +
    organization_name, which is enough to keep the analysis pipeline running
    even when /home/autofill/ stops returning a particular ticker.
    """
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    sources = [
        ("reports/main", "https://new-api.openinfo.uz/api/v2/reports/main/",
         {"page_size": 5, "search": query}, "organization", "organization_name"),
        ("dividend-calendar", "https://new-api.openinfo.uz/api/v2/disclosure/dividend-calendar/",
         {"page_size": 5, "search": query}, "organization_id", "organization"),
    ]
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
        for item in results:
            org_id = item.get(id_key)
            name = item.get(name_key)
            if org_id is None or not name:
                continue
            org_id = str(org_id).strip()
            name = str(name).strip()
            if not org_id or not name:
                continue
            logger.info(f"org_id найден через {label}: {org_id} ({name})")
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


# Кэш полного списка организаций (загружается один раз)
_FULL_ORG_LIST: list | None = None
_FULL_ORG_LIST_PATH = Path("full_org_list_cache.json")


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

    if best_item and best_score >= 2.0:  # Минимум 1 хорошее совпадение
        org_id = str(best_item["id"])
        company_name = str(best_item.get("full_name_text", "")).strip()
        logger.info(f"org_id найден в полном списке (score={best_score:.1f}): {org_id} ({company_name})")
        _store_org_id_cache(query, org_id, company_name)
        return org_id, company_name

    return None


def _calc_match_score(query_normalized: str, name_normalized: str) -> float:
    """Вычисляет score совпадения между запросом и названием."""
    if not query_normalized or not name_normalized:
        return 0.0

    score = 0.0
    query_tokens = set(query_normalized.split())
    name_tokens = set(name_normalized.split())

    common = query_tokens & name_tokens
    score += len(common) * 2  # 2 очка за каждое совпадающее слово

    if query_normalized == name_normalized:
        score += 100
    elif query_normalized in name_normalized:
        score += 20
    elif name_normalized in query_normalized:
        score += 10

    # Бонус за все слова запроса в названии
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
            input_tokens = set(normalized_input.split())
            name_tokens = set(normalized_name.split())
            common_tokens = input_tokens & name_tokens
            score = len(common_tokens)
            if normalized_input == normalized_name:
                score += 100
            elif normalized_input in normalized_name or normalized_name in normalized_input:
                score += 10
            # Бонус если все слова запроса найдены
            if input_tokens and input_tokens <= name_tokens:
                score += 5
        if score > best_score:
            best_score = score
            best_item = item

    # Trust autofill: it already searched by substring server-side.
    # Short tickers like ALKB/IPTB/HMKB score 0 against full names, but the
    # autofill result is still the right company.
    if best_item:
        if best_score <= 0:
            logger.info(
                "Скор=0, доверяем autofill: %s",
                best_item.get("full_name_text") or best_item.get("name"),
            )
        return best_item
    return None


# ─────────────────────────────────────────────────────────
# Создание драйвера (headless — работает и локально и на сервере)
# ─────────────────────────────────────────────────────────

def _make_driver() -> webdriver.Chrome:
    """Create a more stable headless Chrome/Selenium Wire driver."""
    options = webdriver.ChromeOptions()
    options.page_load_strategy = "eager"

    if os.getenv("SELENIUM_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}:
        options.add_argument("--headless=new")
    chrome_binary = os.getenv("CHROME_BINARY") or os.getenv("GOOGLE_CHROME_BIN")
    if chrome_binary:
        options.binary_location = chrome_binary

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--lang=ru-RU")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option(
        "prefs",
        {"profile.default_content_setting_values.notifications": 2},
    )
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    seleniumwire_options = {
        "connection_timeout": REQUEST_TIMEOUT,
        "request_storage": "memory",
        "request_storage_max_size": 150,
        "verify_ssl": False,
    }
    driver = webdriver.Chrome(options=options, seleniumwire_options=seleniumwire_options)
    driver.scopes = [
        r".*new-api\.openinfo\.uz.*accounting-report.*",
        r".*new\.openinfo\.uz.*",
    ]
    return driver


# ─────────────────────────────────────────────────────────
# Скрапинг org_id через Selenium (с retry)
# ─────────────────────────────────────────────────────────

def _scrape_org_id(user_input: str) -> tuple[str, str]:
    """
    Открывает openinfo.uz, ищет компанию, нажимает кнопку «Доходы»
    и перехватывает org_id из сетевых запросов.

    Возвращает (org_id, company_full_name).
    Повторяет MAX_RETRIES раз при падении браузера.
    """
    if not SELENIUM_AVAILABLE:
        raise RuntimeError(
            "Компания не найдена через API openinfo.uz. "
            "Проверьте правильность названия или тикера. "
            "Для расширенного поиска установите: pip install selenium selenium-wire"
        )

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        driver = None
        try:
            logger.info(f"Selenium попытка {attempt}/{MAX_RETRIES}: '{user_input}'")
            driver = _make_driver()
            driver.set_page_load_timeout(60)

            driver.get("https://new.openinfo.uz/ru?tab=facts&page=1")
            wait = WebDriverWait(driver, PAGE_TIMEOUT)

            # 1. Поле поиска
            search_input = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'input[placeholder="Поиск"]')
                )
            )
            time.sleep(0.5)
            search_input.send_keys(user_input)

            # 2. Ждём выпадающий список и кликаем на ПЕРВЫЙ результат
            first_result = wait.until(
                EC.element_to_be_clickable((
                    By.CSS_SELECTOR,
                    ".absolute.z-10.w-full.mt-1.bg-white.border.border-default"
                    ".rounded-xl.shadow-lg > *:first-child"
                ))
            )
            first_result.click()
            time.sleep(2)

            # 3. Забираем полное название компании
            full_name_el = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, './/h1[contains(@class, "text-gray-800")]')
                )
            )
            company_name = full_name_el.text.strip()

            # 4. Очищаем историю запросов и жмём «Доходы»
            driver.requests.clear()
            income_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, '//button[text()="Доходы"]')
                )
            )
            income_btn.click()

            # 5. Ждём сетевой запрос с org_id (максимум 15 сек)
            org_id = None
            deadline = time.time() + 15
            while time.time() < deadline:
                for req in driver.requests:
                    if req.response and "accounting-report" in req.url and "annual" in req.url:
                        m = re.search(r"accounting-report/(\d+)/", req.url)
                        if m:
                            org_id = m.group(1)
                            break
                if org_id:
                    break
                time.sleep(0.5)

            if not org_id:
                raise ValueError(
                    f"Не удалось перехватить org_id для '{user_input}'. "
                    "Возможно компания не найдена или сайт изменился."
                )

            logger.info(f"org_id получен: {org_id} ({company_name})")
            _store_org_id_cache(user_input, org_id, company_name)
            return org_id, company_name

        except Exception as e:
            last_error = e
            logger.warning(f"Попытка {attempt} провалилась: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)  # пауза растёт с каждой попыткой
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass  # браузер уже мёртв — ничего страшного

    raise RuntimeError(
        f"Не удалось получить данные после {MAX_RETRIES} попыток. "
        f"Последняя ошибка: {last_error}"
    )


# ─────────────────────────────────────────────────────────
# Запросы к API
# ─────────────────────────────────────────────────────────

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
