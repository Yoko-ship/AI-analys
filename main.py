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
    url = "https://new-api.openinfo.uz/api/v2/home/autofill/"
    try:
        response = requests.get(
            url,
            params={"name": user_input},
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            verify=False,
        )
        response.raise_for_status()
        items = response.json()
    except Exception as exc:
        logger.warning(f"Не удалось получить org_id через autofill API: {exc}")
        return None

    if not items:
        return None

    normalized_input = _normalize_company_key(user_input)
    best_item = None
    best_score = -1.0

    for item in items:
        full_name = str(item.get("full_name_text", "")).strip()
        org_id = item.get("id")
        if not full_name or org_id is None:
            continue
        normalized_name = _normalize_company_key(full_name)
        score = 0.0
        if normalized_input and normalized_name:
            common_tokens = set(normalized_input.split()) & set(normalized_name.split())
            score = len(common_tokens)
            if normalized_input == normalized_name:
                score += 100
            elif normalized_input in normalized_name or normalized_name in normalized_input:
                score += 10
        if score > best_score:
            best_score = score
            best_item = item

    if not best_item:
        return None

    org_id = str(best_item["id"])
    company_name = str(best_item.get("full_name_text", "")).strip()
    logger.info(f"org_id получен через autofill API: {org_id} ({company_name})")
    _store_org_id_cache(user_input, org_id, company_name)
    return org_id, company_name


# ─────────────────────────────────────────────────────────
# Создание драйвера (headless — работает и локально и на сервере)
# ─────────────────────────────────────────────────────────

def _make_driver() -> webdriver.Chrome:
    """Создаёт Chrome в headless-режиме. Работает везде — Windows, Linux, сервер."""
    options = webdriver.ChromeOptions()

    options.add_argument("--headless=new")           # без GUI (новый headless)
    options.add_argument("--no-sandbox")             # нужно на сервере под root
    options.add_argument("--disable-dev-shm-usage")  # /dev/shm мал на VPS
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    return webdriver.Chrome(options=options)


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
            "Не удалось получить org_id через API, а Selenium fallback недоступен. "
            "Для fallback-режима установи selenium/selenium-wire и Chrome."
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
        client = session or requests
        resp = client.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Таймаут запроса к API: {url}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ошибка API запроса: {e}")


# ─────────────────────────────────────────────────────────
# Парсеры
# ─────────────────────────────────────────────────────────

def _parse_annual(data: list) -> list[dict]:
    result = []
    for report in data:
        year = report.get("reporting_year")
        for item in report.get("accounting_report", []):
            result.append({
                "reporting_year": year,
                "title":          item.get("title"),
                "value":          item.get("value"),
            })
    return result


def _parse_quarter(data: list) -> list[dict]:
    result = []
    for report in data:
        year = report.get("reporting_year")
        for item in report.get("accounting_report", []):
            for q, value in enumerate(
                [item.get(f"value{i}") for i in range(1, 5)], start=1
            ):
                if value is not None and value != 0:
                    result.append({
                        "reporting_year": year,
                        "quarter":        q,
                        "title":          item.get("title"),
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

    # 4. Собираем DataFrames
    annual_df = pd.concat([
        pd.DataFrame(_parse_annual(incomes_annual)),
        pd.DataFrame(_parse_annual(balance_annual)),
    ], ignore_index=True).sort_values("reporting_year")

    quarter_df = pd.concat([
        pd.DataFrame(_parse_quarter(incomes_quarter)),
        pd.DataFrame(_parse_quarter(balance_quarter)),
    ], ignore_index=True).sort_values(["reporting_year", "quarter"])

    # 5. Присоединяем коэффициенты эффективности
    efficiency_df = pd.DataFrame(efficiency.get("results", []))
    if not efficiency_df.empty:
        annual_df = annual_df.merge(efficiency_df, on="reporting_year", how="left")

    logger.info(f"Данные получены: {len(annual_df)} строк годовых, {len(quarter_df)} квартальных")
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
