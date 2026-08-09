"""Build self-hosted logo assets under logos/.

The Google favicon icon-marks read well, but several have a baked-in white
(or dark) background that looks like an ugly square when the logo floats on
the app's dark catalog rows. This script downloads those favicons and flood-
fills a solid white/dark background to transparent (colored brand tiles are
left intact), then autocrops so the mark fills the frame.

Some favicons are too low-res (16–40px) and look blurry when scaled up, so a
handful of logos are pulled directly from the company site as crisp SVG /
high-res PNG instead (CRISP_FLOAT / CRISP_PLATE below).

Layout:
  logos/<T>.{png,svg}        -> floats transparently on the dark surface
  logos/plate/<T>.{png,svg}  -> kept on a light plate (wordmark / dark logo)

Re-run with:  python process_logos.py
"""
from __future__ import annotations
from collections import deque, Counter
from pathlib import Path
from io import BytesIO
import shutil
import requests
from PIL import Image

ROOT = Path(__file__).with_name("logos")
PLATE = ROOT / "plate"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Favicon icon-marks that look good floating once a solid bg is stripped.
FLOAT_DOMAINS = {
    "AGBA": "agrobank.uz", "ALKB": "aloqabank.uz", "DORI": "doridarmon.uz",
    "HMKB": "hamkorbank.uz", "MCBA": "mikrokreditbank.uz", "TNGB": "tengebank.uz",
    "UZNGP": "ung.uz", "UZTL": "uztelecom.uz",
}

# Crisp logos pulled straight from the company site (favicon was too low-res).
# strip=True flood-fills a white background to transparent.
CRISP_FLOAT = {
    "AGMKP": ("https://agmk.uz/assets/public/images/logo1.svg", False),
    "BRBN":  ("https://brb.uz/assets/logo/korotkii-logotip-brb.svg", False),
    "SQBN":  ("https://sqb.uz/upload/img/sqbMobile.svg", False),
    "UNVB":  ("https://universalbank.uz/apple-touch-icon.png", True),
}
# Wordmark / dark logos that need a light plate to stay legible.
CRISP_PLATE = {
    "ALSM": "https://alskom.uz/local/templates/alskom/img/alskom_logo.svg",
}

def fetch(url: str) -> bytes:
    r = requests.get(url, headers=H, timeout=20)
    r.raise_for_status()
    return r.content

def favicon_bytes(domain: str) -> bytes:
    return fetch(f"https://www.google.com/s2/favicons?domain={domain}&sz=128")

def strip_solid_bg(im: Image.Image, tol: int = 40) -> Image.Image:
    """Make a connected solid white/dark background transparent; keep colored tiles."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    opaque = [c for c in corners if c[3] > 200]
    if opaque:
        bg = Counter([c[:3] for c in opaque]).most_common(1)[0][0]
        if all(v >= 235 for v in bg) or all(v <= 40 for v in bg):  # white / dark only
            def close(a, b):
                return all(abs(a[i] - b[i]) <= tol for i in range(3))
            vis = [[False] * w for _ in range(h)]
            dq = deque()
            for x in range(w):
                dq.append((x, 0)); dq.append((x, h - 1))
            for y in range(h):
                dq.append((0, y)); dq.append((w - 1, y))
            while dq:
                x, y = dq.popleft()
                if x < 0 or y < 0 or x >= w or y >= h or vis[y][x]:
                    continue
                r, g, b, a = px[x, y]
                if a < 40 or close((r, g, b), bg):
                    vis[y][x] = True
                    px[x, y] = (r, g, b, 0)
                    dq.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
    bbox = im.getbbox()
    return im.crop(bbox) if bbox else im

def save_raster(data: bytes, dst: Path, strip: bool) -> None:
    im = Image.open(BytesIO(data))
    (strip_solid_bg(im) if strip else im).save(dst)

def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    PLATE.mkdir(parents=True, exist_ok=True)

    for ticker, domain in FLOAT_DOMAINS.items():
        try:
            save_raster(favicon_bytes(domain), ROOT / f"{ticker}.png", strip=True)
            print(f"  float  {ticker} <- favicon {domain}")
        except Exception as exc:
            print(f"  ERROR  {ticker} ({domain}): {exc}")

    for ticker, (url, strip) in CRISP_FLOAT.items():
        try:
            data = fetch(url)
            if url.lower().split("?")[0].endswith(".svg"):
                (ROOT / f"{ticker}.svg").write_bytes(data)
            else:
                save_raster(data, ROOT / f"{ticker}.png", strip=strip)
            print(f"  float  {ticker} <- {url}")
        except Exception as exc:
            print(f"  ERROR  {ticker}: {exc}")

    for ticker, url in CRISP_PLATE.items():
        try:
            data = fetch(url)
            ext = "svg" if url.lower().split("?")[0].endswith(".svg") else "png"
            (PLATE / f"{ticker}.{ext}").write_bytes(data)
            print(f"  plate  {ticker} <- {url}")
        except Exception as exc:
            print(f"  ERROR  {ticker}: {exc}")

    print(f"Done -> {ROOT}")

if __name__ == "__main__":
    main()
