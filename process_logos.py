"""Build self-hosted transparent logo icon-marks under logos/.

The Google favicon icon-marks read well, but several have a baked-in white
(or dark) background that looks like an ugly square when the logo floats on
the app's dark catalog rows. This script downloads those favicons and flood-
fills a solid white/dark background to transparent (colored brand tiles are
left intact), then autocrops so the mark fills the frame.

Only the companies whose mark looks good *floating* on a dark surface are
processed here; the rest keep a light "plate" in the UI (see CompanyLogo).
Re-run with:  python process_logos.py
"""
from __future__ import annotations
from collections import deque, Counter
from pathlib import Path
import requests
from PIL import Image
from io import BytesIO

OUT = Path(__file__).with_name("logos")

# Companies whose brand icon-mark looks good floating on a dark background.
FLOAT_DOMAINS = {
    "AGBA": "agrobank.uz", "AGMKP": "agmk.uz", "ALKB": "aloqabank.uz",
    "ALSM": "alskom.uz", "BRBN": "brb.uz", "DORI": "doridarmon.uz",
    "HMKB": "hamkorbank.uz", "KPBA": "kapitalbank.uz", "MCBA": "mikrokreditbank.uz",
    "SQBN": "sqb.uz", "TNGB": "tengebank.uz",
    "UNVB": "universalbank.uz", "UZNGP": "ung.uz", "UZTL": "uztelecom.uz",
}

def favicon_bytes(domain: str) -> bytes:
    url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    return r.content

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

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for ticker, domain in FLOAT_DOMAINS.items():
        try:
            im = Image.open(BytesIO(favicon_bytes(domain)))
            strip_solid_bg(im).save(OUT / f"{ticker}.png")
            print(f"  {ticker} <- {domain}")
        except Exception as exc:
            print(f"  ERROR {ticker} ({domain}): {exc}")
    print(f"Done -> {OUT}")

if __name__ == "__main__":
    main()
