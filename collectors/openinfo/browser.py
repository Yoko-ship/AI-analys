"""Optional browser fallback, imported only after HTTP issuer lookup fails."""
from __future__ import annotations
import logging
import os
import re
import time

logger = logging.getLogger(__name__)
MAX_RETRIES = 3
PAGE_TIMEOUT = 20
REQUEST_TIMEOUT = 30

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
