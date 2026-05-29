"""Drive deployed UI to surface visual/UX issues."""
from __future__ import annotations

import io
import json
import re
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://ai-analys-production.up.railway.app/"
TOKEN = "bfqhUkAOaBFjmjAPuHOWu6gkO5jPYzFHzJEq5E4g5Tc"
SHOTS = Path(__file__).parent
OBS: list[str] = []
RUN_TAG = "v4"  # set "after" to keep first-run shots, or "before" to overwrite


def log(msg: str) -> None:
    print(msg, flush=True)
    OBS.append(msg)


def shoot(page, name: str, full: bool = True) -> None:
    path = SHOTS / f"{RUN_TAG}_{name}.png"
    page.screenshot(path=str(path), full_page=full)
    log(f"📸 {path.name}")


def probe_contrast(page, label: str) -> None:
    """Scrape computed colors for newly-introduced cards."""
    info = page.evaluate(
        """() => {
          const selectors = [
            '.hero-verdict', '.hero-verdict__title', '.hero-verdict__paragraph p',
            '.hero-verdict__col li', '.hero-verdict__crown-score',
            '.tldr-card', '.tldr-card__col li', '.tldr-card__foryou-text',
            '.tldr-card__tone-label', '.tldr-card__score',
            '.section-card summary', '.section-card .section-title-text',
            '.analysis-para', '.analysis-bullet', '.analysis-kv',
            '.bank-metrics-panel', '.bank-metric-value', '.bank-metric-note',
            '.panel', '.panel h2', '.panel-label', '.panel-copy',
          ];
          const out = {};
          for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (!el) { out[sel] = null; continue; }
            const cs = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            out[sel] = {
              color: cs.color, bg: cs.backgroundColor,
              borderColor: cs.borderColor, w: Math.round(rect.width),
              h: Math.round(rect.height),
              text: (el.textContent || '').slice(0, 80).trim(),
            };
          }
          out._theme = document.body.dataset.theme;
          out._bodyBg = getComputedStyle(document.body).backgroundColor;
          out._bodyColor = getComputedStyle(document.body).color;
          return out;
        }"""
    )
    log(f"\n--- contrast probe @ {label} ---")
    log(f"  body theme={info.pop('_theme')} bg={info.pop('_bodyBg')} color={info.pop('_bodyColor')}")
    for sel, val in info.items():
        if val is None:
            log(f"  {sel} → ABSENT")
        else:
            log(f"  {sel} ({val['w']}x{val['h']}) color={val['color']} bg={val['bg']} text={val['text']!r}")


def parse_rgb(s: str) -> tuple[int, int, int, float] | None:
    m = re.match(r"rgba?\(([^)]+)\)", s.strip())
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(",")]
    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
    a = float(parts[3]) if len(parts) > 3 else 1.0
    return r, g, b, a


def relative_lum(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        cs = c / 255.0
        return cs / 12.92 if cs <= 0.03928 else ((cs + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg: str, bg: str) -> float | None:
    f = parse_rgb(fg)
    b = parse_rgb(bg)
    if not f or not b:
        return None
    l1 = relative_lum(f[:3])
    l2 = relative_lum(b[:3])
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def audit_contrast(page, label: str) -> None:
    rows = page.evaluate(
        """() => {
          const sels = [
            '.hero-verdict__title', '.hero-verdict__paragraph p',
            '.hero-verdict__col li', '.hero-verdict__crown-label',
            '.hero-verdict__crown-score', '.hero-verdict__col-label',
            '.tldr-card__tone-label', '.tldr-card__col li',
            '.tldr-card__foryou-text', '.tldr-card__score', '.tldr-card__summary',
            '.tldr-card__col-label',
            '.section-card summary .section-title-text',
            '.section-tldr-inline',
            '.analysis-para', '.analysis-bullet', '.analysis-kv-value',
            '.analysis-kv-label',
            '.bank-metric-value', '.bank-metric-note', '.bank-metric-label',
            '.metric-card strong', '.metric-card .metric-label',
            '.panel h2', '.panel-label', '.panel-copy',
          ];
          // Walk up parents to find the first non-transparent bg.
          // A surface only "counts" as backing the text if its computed
          // alpha is >= 0.5 — otherwise the underlying body color shows
          // through (a 5%-white card on a near-black body reads as black).
          const opaque = (rgba) => {
            const m = rgba.match(/rgba?\\(([^)]+)\\)/);
            if (!m) return false;
            const p = m[1].split(',').map((s) => s.trim());
            const a = p.length > 3 ? parseFloat(p[3]) : 1;
            return a >= 0.5;
          };
          // Composite an rgba over an opaque background into a single rgb.
          const composite = (fg, bg) => {
            const fm = fg.match(/rgba?\\(([^)]+)\\)/);
            const bm = bg.match(/rgba?\\(([^)]+)\\)/);
            if (!fm || !bm) return bg;
            const f = fm[1].split(',').map((s) => parseFloat(s.trim()));
            const b = bm[1].split(',').map((s) => parseFloat(s.trim()));
            const fa = f.length > 3 ? f[3] : 1;
            const r = Math.round(f[0] * fa + b[0] * (1 - fa));
            const g = Math.round(f[1] * fa + b[1] * (1 - fa));
            const bl = Math.round(f[2] * fa + b[2] * (1 - fa));
            return `rgb(${r}, ${g}, ${bl})`;
          };
          const findBg = (el) => {
            const stack = [];
            let cur = el;
            while (cur) {
              const bg = getComputedStyle(cur).backgroundColor;
              if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                stack.push(bg);
                if (opaque(bg)) break;
              }
              cur = cur.parentElement;
            }
            // Add the document background as the final opaque layer.
            const docBg = getComputedStyle(document.documentElement).backgroundColor;
            const bodyBg = getComputedStyle(document.body).backgroundColor;
            const root = opaque(bodyBg) ? bodyBg : (opaque(docBg) ? docBg : 'rgb(7, 17, 31)');
            stack.push(root);
            // Composite from bottom up.
            let acc = stack[stack.length - 1];
            for (let i = stack.length - 2; i >= 0; i--) {
              acc = composite(stack[i], acc);
            }
            return acc;
          };
          const rows = [];
          for (const sel of sels) {
            const els = document.querySelectorAll(sel);
            els.forEach((el, i) => {
              if (i > 2) return;
              const rect = el.getBoundingClientRect();
              if (rect.width === 0 || rect.height === 0) return;
              const cs = getComputedStyle(el);
              rows.push({
                sel: sel + (els.length > 1 ? `[${i}]` : ''),
                color: cs.color, bg: findBg(el),
                text: (el.textContent || '').slice(0, 64).trim(),
              });
            });
          }
          return rows;
        }"""
    )
    log(f"\n=== WCAG audit @ {label} ===")
    fails = []
    for row in rows:
        ratio = contrast_ratio(row["color"], row["bg"])
        tag = "?" if ratio is None else f"{ratio:.2f}:1"
        flag = ""
        if ratio is not None and ratio < 4.5:
            flag = " ❌ FAIL"
            fails.append((row["sel"], ratio, row["text"]))
        elif ratio is not None and ratio < 7.0:
            flag = " ⚠ AA only"
        log(f"  [{tag}{flag}] {row['sel']}  text={row['text']!r}")
    if fails:
        log(f"\n🚨 {len(fails)} contrast failures at {label}:")
        for sel, r, t in fails:
            log(f"   - {sel}  ratio={r:.2f}  text={t!r}")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()

        page.on("console", lambda m: log(f"  console {m.type}: {m.text[:140]}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: log(f"  pageerror: {e}"))

        log(f"→ goto {URL}  (token injected)")
        page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
        page.evaluate(f'localStorage.setItem("uz_stock_analyzer_token", "{TOKEN}")')
        page.reload(wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=10_000)
        time.sleep(2)

        cur_theme = page.evaluate("() => document.body.dataset.theme")
        log(f"default theme: {cur_theme}")
        shoot(page, f"01_landing_{cur_theme}")

        # Navigate to analysis view.
        log("→ open analysis view")
        try:
            page.get_by_role("button", name=re.compile(r"анализ|analysis|tahlil", re.I)).first.click(timeout=5000)
        except Exception as e:
            log(f"  nav-by-role failed: {e}; trying topbar link")
            page.locator(".topbar-nav-btn").nth(2).click()
        time.sleep(1)
        shoot(page, f"02_analysis_form_{cur_theme}")

        # Try to enable force_refresh checkbox if exists.
        try:
            cb = page.locator('input[type="checkbox"]').first
            if cb.count() > 0:
                cb.check()
                log("  force_refresh checked")
        except Exception:
            pass

        # Find input and submit.
        log("→ type HMKB and submit")
        # Click HMKB company chip if visible (auto-fills the form).
        chip_clicked = False
        try:
            chip = page.locator('button:has-text("HMKB"), .analysis-company-chip:has-text("HMKB")').first
            if chip.count() > 0:
                chip.click(timeout=4000)
                chip_clicked = True
                log("  clicked HMKB chip")
        except Exception as e:
            log(f"  no HMKB chip: {e}")
        if not chip_clicked:
            inp = page.locator('input').first
            try:
                inp.wait_for(timeout=5000)
                inp.fill("HMKB")
                time.sleep(0.3)
            except Exception as e:
                log(f"  no input: {e}")
        # Click submit button — try multiple selectors.
        submitted = False
        for sel in [
            'button:has-text("Анализиро")',
            'button:has-text("Анализ")',
            '.analysis-form button[type="submit"]',
            '.primary-btn',
        ]:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3000)
                    submitted = True
                    log(f"  clicked {sel}")
                    break
            except Exception:
                continue
        if not submitted:
            try:
                page.locator('input').first.press("Enter")
                log("  pressed Enter")
            except Exception as e:
                log(f"  enter failed: {e}")

        # Wait for analysis to complete — look for actual content cards, NOT empty-state.
        log("→ waiting for analysis result (max 300s)")
        try:
            page.wait_for_selector(".hero-verdict, .section-card", timeout=300_000, state="visible")
        except PWTimeout:
            log("⛔ TIMEOUT waiting for results")
            shoot(page, f"03_TIMEOUT_{cur_theme}")
            return
        time.sleep(4)  # let the rest of the panels populate

        shoot(page, f"03_analysis_top_{cur_theme}")
        # Scroll down to capture more.
        page.evaluate("window.scrollTo(0, 600)")
        time.sleep(0.5)
        shoot(page, f"04_analysis_mid_{cur_theme}", full=False)
        page.evaluate("window.scrollTo(0, 1400)")
        time.sleep(0.5)
        shoot(page, f"05_analysis_lower_{cur_theme}", full=False)
        page.evaluate("window.scrollTo(0, 0)")

        probe_contrast(page, f"{cur_theme} theme")
        audit_contrast(page, f"{cur_theme} theme")

        # Toggle theme.
        log("\n→ toggle theme")
        try:
            page.locator(".theme-toggle").first.click(timeout=3000)
            time.sleep(1)
        except Exception as e:
            log(f"  theme toggle failed: {e}")
        new_theme = page.evaluate("() => document.body.dataset.theme")
        log(f"  theme now: {new_theme}")

        shoot(page, f"06_analysis_top_{new_theme}")
        page.evaluate("window.scrollTo(0, 600)")
        time.sleep(0.5)
        shoot(page, f"07_analysis_mid_{new_theme}", full=False)
        page.evaluate("window.scrollTo(0, 1400)")
        time.sleep(0.5)
        shoot(page, f"08_analysis_lower_{new_theme}", full=False)
        page.evaluate("window.scrollTo(0, 0)")

        probe_contrast(page, f"{new_theme} theme")
        audit_contrast(page, f"{new_theme} theme")

        # Specifically check if the hero-verdict actually rendered.
        info = page.evaluate(
            """() => {
              const hv = document.querySelector('.hero-verdict');
              const sc = document.querySelectorAll('.section-card');
              const tc = document.querySelectorAll('.tldr-card');
              return {
                hero: !!hv,
                heroClass: hv ? hv.className : null,
                heroH: hv ? hv.getBoundingClientRect().height : 0,
                sectionCount: sc.length,
                tldrCount: tc.length,
                tldrClasses: Array.from(tc).slice(0, 5).map(t => t.className),
                first_section_summary: sc[0] ? sc[0].querySelector('summary')?.textContent?.slice(0, 200) : null,
              };
            }"""
        )
        log("\n--- final element census ---")
        log(json.dumps(info, ensure_ascii=False, indent=2))

        # Try opening a closed section to see its body.
        try:
            page.evaluate("document.querySelectorAll('details.section-card').forEach(d => d.open = true)")
            time.sleep(0.5)
            shoot(page, f"09_all_sections_open_{new_theme}")
        except Exception:
            pass

        browser.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        log(f"❌ FATAL {type(e).__name__}: {e}")
        raise
    finally:
        (SHOTS / "_log.txt").write_text("\n".join(OBS), encoding="utf-8")
        print(f"\nlog written: {SHOTS / '_log.txt'}", flush=True)
