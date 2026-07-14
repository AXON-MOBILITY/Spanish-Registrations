from __future__ import annotations

import csv
import io
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WHITE_LOGOS = ROOT / "public" / "logos"
OUT = ROOT / "public" / "logos-color"
SOURCES_CSV = OUT / "logo_sources.csv"
CONTACT_SHEET = OUT / "_contact_sheet.html"
CANVAS = 256
LOGO_BOX = 204

HEADERS = {"User-Agent": "Spanish-Registrations-logo-builder/1.0"}

SIMPLE_ICON_SLUGS = {
    "Abarth": "abarth", "Acura": "acura", "Alfa Romeo": "alfaromeo", "Alpine": "alpine",
    "Aston Martin": "astonmartin", "Audi": "audi", "Bentley": "bentley", "BMW": "bmw",
    "BYD": "byd", "Cadillac": "cadillac", "Caterham": "caterham", "Chevrolet": "chevrolet",
    "Citroen": "citroen", "Cupra": "cupra", "Dacia": "dacia", "DS": "dsautomobiles",
    "Ferrari": "ferrari", "Fiat": "fiat", "Ford": "ford", "Honda": "honda",
    "Hyundai": "hyundai", "Ineos": "ineos", "Isuzu": "isuzu", "Iveco": "iveco",
    "Jaguar": "jaguar", "Jeep": "jeep", "Kia": "kia", "Lamborghini": "lamborghini",
    "Lancia": "lancia", "Land Rover": "landrover", "Lexus": "lexus", "Lotus": "lotus",
    "Maserati": "maserati", "Mazda": "mazda", "McLaren": "mclaren", "MG": "mg",
    "MINI": "mini", "Mitsubishi": "mitsubishi", "Nissan": "nissan", "Opel": "opel",
    "Peugeot": "peugeot", "Polestar": "polestar", "Porsche": "porsche", "Renault": "renault",
    "Rolls-Royce": "rollsroyce", "SEAT": "seat", "Skoda": "skoda", "Smart": "smart",
    "Subaru": "subaru", "Suzuki": "suzuki", "Tesla": "tesla", "Toyota": "toyota",
    "Volkswagen": "volkswagen", "Volvo": "volvo", "Xpeng": "xpeng", "Zeekr": "zeekr",
}

SIMPLE_ICON_COLORS = {
    "Abarth": "FDDB00", "Acura": "000000", "Alfa Romeo": "981E32", "Alpine": "0068B0",
    "Aston Martin": "006F62", "Audi": "BB0A30", "Bentley": "333333", "BMW": "0066B1",
    "BYD": "ED1C24", "Cadillac": "000000", "Caterham": "004B8D", "Chevrolet": "CD9834",
    "Citroen": "DA291C", "Cupra": "5D4037", "Dacia": "646B52", "DS": "1D1717",
    "Ferrari": "D40000", "Fiat": "941711", "Ford": "003478", "Honda": "E40521",
    "Hyundai": "002C5F", "Ineos": "000000", "Isuzu": "BE1E2D", "Iveco": "1554FF",
    "Jaguar": "000000", "Jeep": "000000", "Kia": "05141F", "Lamborghini": "B6A272",
    "Lancia": "134B70", "Land Rover": "005A2B", "Lexus": "000000", "Lotus": "FFB800",
    "Maserati": "0C2340", "Mazda": "101010", "McLaren": "FF8700", "MG": "FF0000",
    "MINI": "000000", "Mitsubishi": "E60012", "Nissan": "C3002F", "Opel": "F7D900",
    "Peugeot": "000000", "Polestar": "000000", "Porsche": "B12B28", "Renault": "FFCC33",
    "Rolls-Royce": "281432", "SEAT": "33302E", "Skoda": "0E3A2F", "Smart": "242B2E",
    "Subaru": "013C74", "Suzuki": "E30613", "Tesla": "CC0000", "Toyota": "EB0A1E",
    "Volkswagen": "151F5D", "Volvo": "003057", "Xpeng": "111111", "Zeekr": "111111",
}

COMMONS_QUERIES = {
    "Alpina": ["Alpina automobile logo", "Alpina logo"],
    "Baojun": ["Baojun logo"], "BAW": ["Beijing Automobile Works logo", "BAW logo automobile"],
    "Bestune": ["Bestune logo", "FAW Bestune logo"], "Changan": ["Changan Automobile logo"],
    "Cirelli": ["Cirelli Motor Company logo", "Cirelli logo automobile"], "DFSK": ["DFSK logo"],
    "Dongfeng": ["Dongfeng Motor logo"], "DR": ["DR Automobiles logo"], "Ebro": ["Ebro automotive logo"],
    "EVO": ["EVO automobile logo DR"], "Faw": ["FAW Group logo", "First Automobile Works logo"],
    "Foton Motors": ["Foton Motor logo"], "Geely": ["Geely logo"],
    "GWM": ["Great Wall Motors logo", "GWM logo automobile"], "Herrator": ["Herrator logo"],
    "Jaecoo": ["Jaecoo logo"], "Kg Mobility": ["KG Mobility logo", "SsangYong KG Mobility logo"],
    "Leapmotor": ["Leapmotor logo"], "Livan": ["Livan Automotive logo"], "Lynk & Co": ["Lynk & Co logo"],
    "MAN": ["MAN Truck & Bus logo"], "Maxus": ["Maxus logo SAIC"], "Mercedes": ["Mercedes-Benz logo"],
    "Mercedes-V": ["Mercedes-Benz logo"], "Mitsubishi-Fuso": ["Mitsubishi Fuso logo"],
    "Moke": ["Moke International logo"], "Morgan": ["Morgan Motor Company logo"], "Omoda": ["Omoda automobile logo"],
    "Renault Trucks": ["Renault Trucks logo"], "Seres": ["Seres automobile logo"], "Shineray": ["Shineray logo"],
    "Skywell": ["Skywell automobile logo"], "Sportequipe": ["Sportequipe logo automobile"], "Ssangyong": ["SsangYong logo"],
    "Tiger": ["Tiger automobile logo"], "Tripod": ["Tripod mobility logo"], "Voyah": ["Voyah logo"], "Yudo": ["Yudo Auto logo"],
}

ATTACHED_SOURCES = {
    "Alpina": Path(r"C:\Users\Nacho\AppData\Local\Temp\codex-clipboard-04e800dc-9918-4bfd-aaae-caa070a63f1a.png"),
}

FALLBACK_COLORS = {
    "Baojun": "C9002B", "BAW": "1F5AA6", "Bestune": "C8102E", "Changan": "005BBB",
    "Cirelli": "0F172A", "DFSK": "E30613", "Dongfeng": "DD1E25", "DR": "111827",
    "Ebro": "0D5C63", "EVO": "D71920", "Faw": "004B93", "Foton Motors": "1D4ED8",
    "Geely": "124E91", "GWM": "005BAC", "Herrator": "111827", "Jaecoo": "111827",
    "Kg Mobility": "0F2F57", "Leapmotor": "111827", "Livan": "0F5E9C", "Lynk & Co": "111827",
    "MAN": "00529B", "Maxus": "A71930", "Mercedes": "111827", "Mercedes-V": "111827",
    "Mitsubishi-Fuso": "E60012", "Moke": "111827", "Morgan": "0B3D2E", "Omoda": "111827",
    "Renault Trucks": "FFCC33", "Seres": "1F4E79", "Shineray": "E30613", "Skywell": "005BAC",
    "Sportequipe": "111827", "Ssangyong": "003B71", "Tiger": "E87722", "Tripod": "111827",
    "Voyah": "111827", "Yudo": "005BAC",
}

BAD_TITLE_BITS = ["album", "antique", "bank", "bkk", "car park", "dealership", "dealer", "emoji", "football", "game", "generic", "history", "hotel", "mobility service", "museum", "old", "registered trademark", "service", "sign", "station", "taxi"]

@dataclass
class LogoSource:
    brand: str
    file: str
    status: str
    source_type: str
    source_url: str
    source_title: str
    notes: str = ""

def request_get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("headers", HEADERS)
    kwargs.setdefault("timeout", 30)
    for attempt in range(3):
        try:
            response = requests.get(url, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(1 + attempt)
                continue
            return response
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError(f"Unable to fetch {url}")

def commons_api(params: dict) -> dict:
    response = request_get("https://commons.wikimedia.org/w/api.php", params=params)
    response.raise_for_status()
    return response.json()

def score_commons_title(brand: str, title: str, mime: str) -> int:
    lower = title.lower()
    score = 0
    brand_bits = [bit for bit in re.split(r"[^a-z0-9]+", brand.lower()) if bit and bit not in {"co", "motors"}]
    if any(bit in lower for bit in brand_bits): score += 20
    if "logo" in lower: score += 16
    if "emblem" in lower or "wordmark" in lower: score += 4
    if mime == "image/svg+xml" or lower.endswith(".svg"): score += 12
    if any(bit in lower for bit in BAD_TITLE_BITS): score -= 50
    return score

def search_commons(brand: str) -> dict | None:
    candidates = []
    for query in COMMONS_QUERIES.get(brand, [f"{brand} logo automobile", f"{brand} logo"]):
        data = commons_api({"action":"query", "format":"json", "generator":"search", "gsrnamespace":6, "gsrsearch":query, "gsrlimit":12, "prop":"imageinfo", "iiprop":"url|mime"})
        for page in data.get("query", {}).get("pages", {}).values():
            title = page.get("title", "")
            infos = page.get("imageinfo") or []
            if not infos: continue
            info = infos[0]
            score = score_commons_title(brand, title, info.get("mime", ""))
            if score > 0:
                candidates.append({"title": title, "url": info.get("url", ""), "mime": info.get("mime", ""), "score": score})
    return sorted(candidates, key=lambda x: x["score"], reverse=True)[0] if candidates else None

def load_logo_bytes(url: str) -> tuple[Image.Image | bytes, str]:
    response = request_get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    content = response.content
    if "svg" in content_type or url.lower().endswith(".svg") or content[:5].lower() == b"<?xml" or content[:4].lower() == b"<svg":
        return content, "svg"
    return Image.open(io.BytesIO(content)).convert("RGBA"), "bitmap"

def remove_flat_light_background(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    width, height = im.size
    corners = [im.getpixel((0,0)), im.getpixel((width-1,0)), im.getpixel((0,height-1)), im.getpixel((width-1,height-1))]
    if not all(px[3] > 245 and min(px[:3]) > 230 for px in corners):
        return im
    pixels = im.load()
    for y in range(height):
        for x in range(width):
            r,g,b,a = pixels[x,y]
            if a > 0 and r > 235 and g > 235 and b > 235:
                pixels[x,y] = (255,255,255,0)
    return im

def normalize_logo(im: Image.Image) -> Image.Image:
    im = remove_flat_light_background(im)
    bbox = im.getchannel("A").getbbox()
    if bbox: im = im.crop(bbox)
    width, height = im.size
    if width == 0 or height == 0:
        return Image.new("RGBA", (CANVAS, CANVAS), (0,0,0,0))
    scale = min(LOGO_BOX / width, LOGO_BOX / height)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    im = im.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0,0,0,0))
    canvas.alpha_composite(im, ((CANVAS - new_size[0]) // 2, (CANVAS - new_size[1]) // 2))
    return canvas

def recolor_existing_white_logo(brand: str, color: str) -> Image.Image:
    source = Image.open(WHITE_LOGOS / f"{brand}.png").convert("RGBA")
    bbox = source.getchannel("A").getbbox()
    if bbox: source = source.crop(bbox)
    rgb = tuple(int(color[i:i+2], 16) for i in (0,2,4))
    alpha = source.getchannel("A")
    colored = Image.new("RGBA", source.size, (*rgb, 255))
    colored.putalpha(alpha)
    return normalize_logo(colored)

def source_from_simple_icons(brand: str) -> tuple[Image.Image | bytes, LogoSource] | None:
    slug = SIMPLE_ICON_SLUGS.get(brand)
    if not slug: return None
    color = SIMPLE_ICON_COLORS.get(brand, "111111")
    url = f"https://cdn.simpleicons.org/{slug}/{color}"
    response = request_get(url)
    if response.status_code != 200: return None
    return response.content, LogoSource(brand, f"{brand}.svg", "public_vector", "simple-icons", url, slug, "SVG monocromo con color de marca de Simple Icons")

def source_from_attachment(brand: str) -> tuple[Image.Image | bytes, LogoSource] | None:
    path = ATTACHED_SOURCES.get(brand)
    if not path or not path.exists(): return None
    return Image.open(path).convert("RGBA"), LogoSource(brand, f"{brand}.png", "user_provided", "attached-image", str(path), path.name, "Imagen de referencia aportada por el usuario")

def source_from_commons(brand: str) -> tuple[Image.Image | bytes, LogoSource] | None:
    candidate = search_commons(brand)
    if not candidate: return None
    image, kind = load_logo_bytes(candidate["url"])
    file = f"{brand}.svg" if kind == "svg" else f"{brand}.png"
    return image, LogoSource(brand, file, "public_best_effort", "wikimedia-commons", candidate["url"], candidate["title"], f"score={candidate['score']}; formato={kind}")

def build_contact_sheet(rows: Iterable[LogoSource]) -> None:
    cards = []
    for row in rows:
        cls = "ok" if row.status in {"public_vector", "user_provided"} else "warn" if "public" in row.status else "bad"
        cards.append(f'''<article class="card"><div class="logo"><img src="{row.file}" alt="{row.brand}"></div><h2>{row.brand}</h2><p class="{cls}">{row.status.replace('_',' ')}</p><small>{row.source_type}</small></article>''')
    html = """<!doctype html><meta charset="utf-8"><title>Logos color</title><style>
body{margin:0;font-family:Arial,sans-serif;background:#f5f7fb;color:#111827}header{padding:28px 32px 12px}h1{margin:0;font-size:28px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:14px;padding:20px 32px 36px}.card{background:white;border:1px solid #d8dee9;border-radius:10px;padding:14px;min-height:172px}.logo{height:92px;display:grid;place-items:center;border-radius:8px;background:#fff}.logo img{max-width:86px;max-height:76px;object-fit:contain}h2{margin:12px 0 5px;font-size:14px;line-height:1.2}p{margin:0 0 4px;font-size:12px;font-weight:700}small{color:#64748b;font-size:11px}.ok{color:#166534}.warn{color:#92400e}.bad{color:#991b1b}
</style><header><h1>Logos color</h1></header><main class="grid">""" + "\n".join(cards) + "</main>"
    CONTACT_SHEET.write_text(html, encoding="utf-8")

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    brands = sorted(path.stem for path in WHITE_LOGOS.glob("*.png"))
    rows, failures = [], []
    for brand in brands:
        result = None
        for loader in (source_from_attachment, source_from_simple_icons, source_from_commons):
            try:
                result = loader(brand)
            except Exception as exc:
                failures.append(f"{brand}: {loader.__name__}: {exc}")
                result = None
            if result: break
        if result:
            image, source = result
            if isinstance(image, bytes):
                (OUT / source.file).write_bytes(image)
            else:
                normalize_logo(image).save(OUT / source.file)
        else:
            color = FALLBACK_COLORS.get(brand, "111827")
            source = LogoSource(brand, f"{brand}.png", "fallback_existing_shape", "local-white-logo", str(WHITE_LOGOS / f"{brand}.png"), f"{brand}.png", f"Sin fuente publica fiable automatica; recoloreado provisional {color}, revisar manualmente")
            recolor_existing_white_logo(brand, color).save(OUT / source.file)
        rows.append(source)
        print(f"{brand}: {source.status} ({source.source_type})")
    with SOURCES_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["brand","file","status","source_type","source_url","source_title","notes"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)
    build_contact_sheet(rows)
    summary = {status: sum(1 for row in rows if row.status == status) for status in sorted({row.status for row in rows})}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"contact_sheet={CONTACT_SHEET}")

if __name__ == "__main__":
    main()
