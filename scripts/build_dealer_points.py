#!/usr/bin/env python3
"""Build a normalized all-brand sales-point master with traceable sources."""

import argparse
import csv
import html
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "masters" / "master_dealer_points.csv"
AUDI_SALES_POINTS = ROOT / "masters" / "sources" / "audi_official_sales_points.csv"
PORSCHE_SALES_POINTS = ROOT / "masters" / "sources" / "porsche_official_sales_points.csv"
VOLVO_SALES_POINTS = ROOT / "masters" / "sources" / "volvo_official_sales_points.csv"
TESLA_SALES_POINTS = ROOT / "masters" / "sources" / "tesla_official_sales_points.csv"
BYD_SALES_POINTS = ROOT / "masters" / "sources" / "byd_official_sales_points.csv"
USER_AGENT = "AxonMobilityDealerMaster/1.0"
SUPPORTED = (
    "Toyota", "Renault", "Dacia", "Hyundai", "Kia", "Seat", "Cupra",
    "Lexus", "Nissan", "Audi", "Mercedes", "Mercedes-V", "Porsche", "Volvo",
    "Tesla", "BYD", "Land Rover", "Jaguar",
)
MINIMUM_SALES_POINTS = {
    "Toyota": 140, "Renault": 300, "Dacia": 300,
    "Hyundai": 140, "Kia": 180, "Seat": 170, "Cupra": 85,
    "Lexus": 25, "Nissan": 120, "Audi": 60,
    "Mercedes": 130, "Mercedes-V": 110, "Porsche": 20, "Volvo": 70,
    "Tesla": 15, "BYD": 80, "Land Rover": 25, "Jaguar": 4,
}
GRID = (
    (43.36, -8.41), (43.26, -2.94), (42.82, -1.64), (41.65, -0.89),
    (41.39, 2.17), (39.47, -0.38), (38.35, -0.48), (37.98, -1.13),
    (37.18, -3.60), (36.72, -4.42), (37.39, -5.99), (38.88, -6.97),
    (40.42, -3.70), (41.65, -4.72), (43.53, -5.66), (28.12, -15.44),
    (28.46, -16.25), (39.57, 2.65),
)
OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
GEONAMES_URL = "https://download.geonames.org/export/zip/ES.zip"
_POSTCODE_CENTROIDS = None
_MERCEDES_DEALERS = None

DGT_BRAND_ALIASES = {
    "Toyota": ("Toyota",),
    "Dacia": ("Dacia",),
    "Kia": ("Kia",),
    "Volkswagen": ("Volkswagen", "VW"),
    "Renault": ("Renault",),
    "BYD": ("BYD",),
    "MG": ("MG", "MG Motor"),
    "Tesla": ("Tesla",),
    "Hyundai": ("Hyundai",),
    "Seat": ("Seat",),
    "Ebro": ("Ebro", "Ebro Motors"),
    "Peugeot": ("Peugeot",),
    "Citroen": ("Citroen", "Citroën"),
    "Skoda": ("Skoda", "Škoda"),
    "Mazda": ("Mazda",),
    "Audi": ("Audi",),
    "Mercedes": ("Mercedes", "Mercedes-Benz"),
    "Ford": ("Ford",),
    "BMW": ("BMW",),
    "Omoda": ("Omoda",),
    "Nissan": ("Nissan",),
    "Cupra": ("Cupra",),
    "Jaecoo": ("Jaecoo",),
    "Leapmotor": ("Leapmotor",),
    "Opel": ("Opel",),
    "Lexus": ("Lexus",),
    "Volvo": ("Volvo",),
    "Mini": ("Mini",),
    "Honda": ("Honda",),
    "Changan": ("Changan",),
    "Suzuki": ("Suzuki",),
    "Fiat": ("Fiat",),
    "Mitsubishi": ("Mitsubishi",),
    "Jeep": ("Jeep",),
    "Xpeng": ("Xpeng", "XPeng"),
    "KG Mobility": ("KG Mobility", "KGM", "SsangYong"),
    "Geely": ("Geely",),
    "Porsche": ("Porsche",),
    "Lynk & Co": ("Lynk & Co", "Lynk and Co"),
    "Alpine": ("Alpine",),
    "Subaru": ("Subaru",),
    "Evo": ("Evo", "EVO"),
    "Smart": ("Smart",),
    "Polestar": ("Polestar",),
    "Land Rover": ("Land Rover",),
    "Shineray": ("Shineray",),
    "Alfa Romeo": ("Alfa Romeo",),
    "DS": ("DS", "DS Automobiles"),
    "Livan": ("Livan",),
    "BAW": ("BAW",),
    "FAW": ("FAW",),
    "DR": ("DR", "DR Automobiles"),
    "Mercedes-V": ("Mercedes Vans", "Mercedes-Benz Vans"),
    "Dongfeng": ("Dongfeng",),
    "DFSK": ("DFSK",),
    "Lamborghini": ("Lamborghini",),
    "Ferrari": ("Ferrari",),
    "Maserati": ("Maserati",),
    "Baojun": ("Baojun",),
    "Cirelli": ("Cirelli",),
    "Zeekr": ("Zeekr",),
    "Bentley": ("Bentley",),
    "Aston Martin": ("Aston Martin",),
    "BAIC": ("BAIC",),
    "SportEquipe": ("SportEquipe", "Sport Equipe"),
    "Lancia": ("Lancia",),
    "ICH-X": ("ICH-X", "ICH X"),
    "Abarth": ("Abarth",),
    "Ineos": ("Ineos", "Ineos Grenadier"),
    "Moke": ("Moke", "Moke International", "Moke International Ltd"),
    "Tripod": ("Tripod",),
    "Gruau": ("Gruau",),
    "Tiger": ("Tiger",),
    "Sin marca": ("Sin marca",),
}
DGT_BRANDS = tuple(DGT_BRAND_ALIASES)

FIELDS = (
    "brand", "dealer_id", "dealer_name", "point_of_sale", "point_of_sale_id",
    "address", "postcode", "city", "province", "latitude", "longitude",
    "source_kind", "source_confidence", "source_url", "retrieved_date",
)


def get(url, data=None, headers=None, timeout=90, attempts=3):
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, urllib.error.URLError):
            if attempt + 1 == attempts:
                raise
            time.sleep(1 + attempt)


def text(url):
    return get(url).decode("utf-8", errors="replace")


def clean(value):
    return " ".join(str(value or "").strip().split())


def postcode(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(5) if 1 <= len(digits) <= 5 else ""


def make_point(brand, dealer_id, dealer_name, pos, pos_id, address, cp, city,
               province, lat, lon, source_kind, source_url, source_confidence="official"):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (27 <= lat <= 44.5 and -19 <= lon <= 5):
        return None
    pos_id = clean(pos_id)
    pos = clean(pos)
    dealer_id = clean(dealer_id) or pos_id
    dealer_name = clean(dealer_name) or pos
    pos_id = pos_id or dealer_id
    pos = pos or dealer_name
    cp = postcode(cp)
    if not all((dealer_id, dealer_name, pos_id, pos)):
        return None
    return {
        "brand": brand, "dealer_id": dealer_id,
        "dealer_name": dealer_name, "point_of_sale": pos,
        "point_of_sale_id": pos_id, "address": clean(address),
        "postcode": cp, "city": clean(city), "province": clean(province),
        "latitude": f"{lat:.7f}", "longitude": f"{lon:.7f}",
        "source_kind": source_kind, "source_confidence": source_confidence,
        "source_url": source_url,
        "retrieved_date": date.today().isoformat(),
    }


def fetch_renault_group(brand):
    key = brand.lower()
    page_url = f"https://www.{key}.es/concesionarios.html"
    api_url = f"https://www.{key}.es/wired/commerce/v2/dealers/locator"
    found = {}
    for lat, lon in GRID:
        body = json.dumps({
            "brand": key, "location": {"lat": lat, "lon": lon, "country": "ES"},
            "count": 100, "language": "es",
        }).encode()
        payload = json.loads(get(api_url, body, {
            "Content-Type": "application/json", "Origin": f"https://www.{key}.es",
        }))
        found.update({item.get("dealerId", ""): item for item in payload})
    rows = []
    for item in found.values():
        brand_data = item.get(key) or {}
        is_sales = (brand_data.get("domains") or {}).get("newVehicles")
        is_sales = is_sales or bool(set(item.get("activities") or []) & {"01", "18"})
        if not is_sales:
            continue
        geo = item.get("geolocalization") or {}
        row = make_point(
            brand, item.get("birId") or item.get("dealerId"),
            item.get("legalName") or item.get("name"), item.get("name"),
            item.get("dealerId"), item.get("streetAddress"), item.get("postalCode"),
            item.get("locality"), "", geo.get("lat"), geo.get("lon"),
            "official_api", page_url,
        )
        if row:
            rows.append(row)
    return rows


def fetch_hyundai():
    url = "https://www.hyundai.com/es/es/concesionarios.html"
    match = re.search(r"data-js-content='([^']+)'", text(url))
    if not match:
        raise RuntimeError("Hyundai payload not found")
    dealers = json.loads(html.unescape(match.group(1)))["dealers"]["es"]
    rows = []
    for item in dealers:
        services = {
            service.get("serviceId")
            for group in item.get("dealerProperties") or []
            for service in group.get("services") or []
        }
        if item.get("onlyService") or "Nuevos" not in services:
            continue
        row = make_point(
            "Hyundai", item.get("localId") or item.get("dealerId"),
            item.get("fullDealerName"), item.get("shortOutletName") or item.get("fullDealerName"),
            item.get("dealerId") or item.get("id"),
            f"{clean(item.get('addressLine1'))} {clean(item.get('houseStreetNumber'))}",
            item.get("postalCode"), item.get("city"), item.get("province"),
            item.get("lat"), item.get("lng"), "official_page_payload", url,
        )
        if row:
            rows.append(row)
    return rows


def fetch_kia():
    page_url = "https://www.kia.com/es/buscador-concesionarios/"
    query = urllib.parse.urlencode({"program": "dealerLocatorSearch", "locale": "es-es"})
    dealers = json.loads(get(f"https://www.kia.com/api/bin/dealer?{query}"))["list"]
    rows = []
    for item in dealers:
        kind = clean(item.get("dealerDealertype")).lower()
        services = clean(item.get("dealerServiceType")).lower()
        if "sales" not in kind and "exposici" not in services:
            continue
        dealer = item.get("groupDealerName") or item.get("dealerName")
        city = clean(item.get("dealerResidence"))
        pos = clean(item.get("dealerName"))
        if city and city.lower() not in pos.lower():
            pos = f"{pos} ({city})"
        row = make_point(
            "Kia", dealer, dealer, pos,
            item.get("dealerInternalid") or item.get("dealerExternalid"),
            item.get("dealerAddress"), item.get("dealerPostcode"), city, "",
            item.get("dealerLatitude"), item.get("dealerLongitude"),
            "official_api", page_url,
        )
        if row:
            rows.append(row)
    return rows


def decode_js(value):
    output, index = [], 0
    simple = {"n": "\n", "r": "\r", "t": "\t", "/": "/", '"': '"', "\\": "\\"}
    while index < len(value):
        if value[index] != "\\":
            output.append(value[index]); index += 1; continue
        kind = value[index + 1]
        if kind == "x":
            output.append(chr(int(value[index + 2:index + 4], 16))); index += 4
        elif kind == "u":
            output.append(chr(int(value[index + 2:index + 6], 16))); index += 6
        else:
            output.append(simple.get(kind, kind)); index += 2
    return "".join(output)


def toyota_payload(page, name):
    pattern = rf"window\.dxp\.retailers\.{name}\s*=\s*JSON\.parse\(\"(.*?)\"\);"
    match = re.search(pattern, page, flags=re.DOTALL)
    return json.loads(decode_js(match.group(1))) if match else None


def fetch_toyota():
    directory_url = "https://www.toyota.es/concesionarios"
    urls = set(re.findall(
        r"https://www\.toyota\.es/concesionarios/[a-z0-9-]+", text(directory_url)
    ))
    found = {}
    for url in sorted(urls):
        retailer, outlets = {}, None
        for attempt in range(3):
            page = text(url)
            retailer = toyota_payload(page, "retailer") or {}
            outlets = toyota_payload(page, "outlets")
            if outlets is not None:
                break
            time.sleep(1 + attempt)
        if outlets is None:
            continue
        for item in outlets:
            services = {service.get("service") for service in item.get("services") or []}
            authorized = any(a.get("authorisedRetailer") for a in item.get("addresses") or [])
            if "ShowRoom" not in services and not authorized:
                continue
            address = item.get("address") or {}
            geo = address.get("geo") or address.get("origin") or {}
            row = make_point(
                "Toyota", retailer.get("uuid"),
                retailer.get("name") or (item.get("operatingCompany") or {}).get("name"),
                item.get("name"), item.get("uuid") or item.get("id"),
                address.get("address1"), address.get("zip"), address.get("city"),
                address.get("region"), geo.get("lat"), geo.get("lon"),
                "official_page_payload", url,
            )
            if row:
                found[row["point_of_sale_id"]] = row
    return list(found.values())


def fetch_seat_group(brand):
    source_url = "https://www.seat.es/red-de-concesionarios-seat"
    endpoint = (
        "https://www.seat.es/content/countries/es/seat-website/es/"
        "red-de-concesionarios-seat.snw.xml?app=seat-esp&brandseat=true"
        "&max_dist=9999&city=40,-3&newcars=true&max_count=9999"
    )
    root = ET.fromstring(get(endpoint))
    rows = []
    for item in root.findall(".//partner"):
        if brand == "Cupra" and item.findtext("cupra_specialized") != "true":
            continue
        partner_id = clean(item.findtext("partner_id"))
        name = clean(item.findtext("name"))
        street = clean(" ".join(filter(None, (
            item.findtext("street"), item.findtext("street_supplementary")
        ))))
        row = make_point(
            brand, partner_id, name, name, partner_id, street,
            item.findtext("zip_code"), item.findtext("city"),
            item.findtext("region_text"), item.findtext("mapcoordinate/latitude"),
            item.findtext("mapcoordinate/longitude"), "official_api_xml", source_url,
        )
        if row:
            rows.append(row)
    return rows

def load_postcode_centroids():
    global _POSTCODE_CENTROIDS
    if _POSTCODE_CENTROIDS is not None:
        return _POSTCODE_CENTROIDS
    grouped = {}
    with zipfile.ZipFile(io.BytesIO(get(GEONAMES_URL, timeout=120))) as archive:
        name = next(
            item for item in archive.namelist()
            if item.upper().endswith("ES.TXT")
        )
        with archive.open(name) as handle:
            for raw_line in handle:
                fields = raw_line.decode("utf-8").rstrip("\n").split("\t")
                if len(fields) < 11 or not re.fullmatch(r"[0-5][0-9]{4}", fields[1]):
                    continue
                grouped.setdefault(fields[1], []).append(
                    (float(fields[9]), float(fields[10]))
                )
    _POSTCODE_CENTROIDS = {
        cp: (
            sum(lat for lat, _ in values) / len(values),
            sum(lon for _, lon in values) / len(values),
        )
        for cp, values in grouped.items()
    }
    return _POSTCODE_CENTROIDS


def parse_lexus_sales_points(page, centroids):
    """Parse explicitly labelled Lexus showroom points from the official page."""
    rows = []
    blocks = re.split(r'<div class="retailer-details"[^>]*>', page)[1:]
    for block in blocks:
        title_match = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.DOTALL)
        if not title_match:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", " ", title_match.group(1)))
        if "EXPOSICION" not in normalize_brand_text(title):
            continue
        address_match = re.search(
            r'<li class="address">(.*?)</li>', block, re.DOTALL
        )
        link_match = re.search(
            r'<a[^>]+data-gt-action="view-dealer"[^>]+>', block, re.DOTALL
        )
        if not link_match:
            continue
        tag = link_match.group(0)
        attrs = dict(re.findall(r'data-gt-([a-z]+)="([^"]*)"', tag))
        href_match = re.search(r'href="([^"]+)"', tag)
        cp = postcode(attrs.get("dealerzipcode"))
        if cp not in centroids:
            continue
        lat, lon = centroids[cp]
        dealer_name = re.sub(r"\s*\(.*$", "", title).strip(" -")
        dealer_name = re.sub(
            r"\s*-\s*(?:LEXUS|EXPOSICION).*$", "", dealer_name,
            flags=re.IGNORECASE,
        ).strip(" -")
        dealer_id = normalize_brand_text(dealer_name)
        source_url = (
            html.unescape(href_match.group(1))
            if href_match else "https://www.lexusauto.es/concesionarios"
        )
        row = make_point(
            "Lexus", dealer_id, dealer_name, title, attrs.get("dealerid"),
            html.unescape(re.sub(r"<[^>]+>", " ", address_match.group(1)))
            if address_match else "",
            cp, attrs.get("dealercity"), attrs.get("dealerregion"), lat, lon,
            "official_page_postcode_centroid", source_url,
        )
        if row:
            rows.append(row)
    return rows


def fetch_lexus():
    url = "https://www.lexusauto.es/concesionarios"
    page = get(url).decode("utf-8", errors="replace")
    return parse_lexus_sales_points(page, load_postcode_centroids())


def parse_nissan_sales_points(page):
    """Parse Nissan points whose official activity includes new-vehicle sales."""
    match = re.search(r"var\s+mijsontodas\s*=\s*(\{.*?\});", page, re.DOTALL)
    if not match:
        raise RuntimeError("Nissan dealer payload not found")
    payload = json.loads(match.group(1))
    rows = []
    for item in payload.get("todas") or []:
        activity = normalize_brand_text(item.get("ventasyservicios"))
        if "VENTAS" not in activity or not postcode(item.get("cp")):
            continue
        link = clean(item.get("link"))
        dealer_id = urllib.parse.urlparse(link).path.strip("/").split("/")[-1]
        dealer_id = dealer_id or normalize_brand_text(item.get("nombre"))
        row = make_point(
            "Nissan", dealer_id, item.get("nombre"), item.get("nombre"),
            item.get("id"), item.get("direccion"), item.get("cp"),
            item.get("poblacion"), item.get("provincia"), item.get("latitud"),
            item.get("longitud"), "official_page_payload",
            link or "https://serviciosweb.nissan.es/dloc/concesionario/concesionario",
        )
        if row:
            rows.append(row)
    return rows


def fetch_nissan():
    url = "https://serviciosweb.nissan.es/dloc/concesionario/concesionario"
    page = get(url).decode("iso-8859-1", errors="replace")
    return parse_nissan_sales_points(page)


def load_audi_sales_points(path, centroids):
    """Load sales locations verified against Audi's official dealer pages."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            cp = postcode(item.get("postcode"))
            if cp not in centroids:
                continue
            lat, lon = centroids[cp]
            source_url = clean(item.get("source_url"))
            parts = urllib.parse.urlparse(source_url).path.strip("/").split("/")
            dealer_name = clean(item.get("dealer_name"))
            row = make_point(
                "Audi", normalize_brand_text(dealer_name), dealer_name,
                item.get("point_of_sale"), ":".join(parts[-2:]),
                item.get("address"), cp, item.get("city"), item.get("province"),
                lat, lon, "official_page_postcode_centroid", source_url,
            )
            if row:
                rows.append(row)
    return rows


def fetch_audi():
    return load_audi_sales_points(AUDI_SALES_POINTS, load_postcode_centroids())


def load_porsche_sales_points(path, centroids):
    """Load sales locations verified against Porsche's official dealer-search page."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            cp = postcode(item.get("postcode"))
            if cp not in centroids:
                continue
            lat, lon = centroids[cp]
            dealer_name = clean(item.get("dealer_name"))
            row = make_point(
                "Porsche", normalize_brand_text(dealer_name), dealer_name,
                item.get("point_of_sale"), normalize_brand_text(item.get("point_of_sale")),
                item.get("address"), cp, item.get("city"), item.get("province"),
                lat, lon, "official_page_postcode_centroid",
                clean(item.get("source_url")),
            )
            if row:
                rows.append(row)
    return rows


def fetch_porsche():
    return load_porsche_sales_points(PORSCHE_SALES_POINTS, load_postcode_centroids())


def load_volvo_sales_points(path):
    """Load sales locations verified against Volvo's official dealer-locator page.

    Volvo's page embeds each dealer's own latitude/longitude in its Next.js
    payload, so no postcode-centroid approximation is needed here.
    """
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            dealer_name = clean(item.get("dealer_name"))
            pos = clean(item.get("point_of_sale"))
            row = make_point(
                "Volvo", normalize_brand_text(dealer_name), dealer_name,
                pos, normalize_brand_text(pos), "",
                item.get("postcode"), item.get("city"), "",
                item.get("latitude"), item.get("longitude"),
                "official_page_payload", clean(item.get("source_url")),
            )
            if row:
                rows.append(row)
    return rows


def fetch_volvo():
    return load_volvo_sales_points(VOLVO_SALES_POINTS)


def load_tesla_sales_points(path, centroids):
    """Load Tesla's official Spain store list (direct sales, no franchise dealers)."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            cp = postcode(item.get("postcode"))
            if cp not in centroids:
                continue
            lat, lon = centroids[cp]
            dealer_name = clean(item.get("dealer_name"))
            row = make_point(
                "Tesla", normalize_brand_text(dealer_name), dealer_name,
                item.get("point_of_sale"), normalize_brand_text(item.get("point_of_sale")),
                item.get("address"), cp, item.get("city"), item.get("province"),
                lat, lon, "official_page_postcode_centroid",
                clean(item.get("source_url")),
            )
            if row:
                rows.append(row)
    return rows


def fetch_tesla():
    return load_tesla_sales_points(TESLA_SALES_POINTS, load_postcode_centroids())


def load_byd_sales_points(path):
    """Load BYD's official Spain sales network (eu-site-api.byd.com, type=sales).

    Excludes points still in "Próxima Apertura" (not yet open) even though the
    API marks them as softLaunch; BYD's own lat/lon are used directly.
    """
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            dealer_name = clean(item.get("dealer_name"))
            pos = clean(item.get("point_of_sale"))
            row = make_point(
                "BYD", normalize_brand_text(dealer_name), dealer_name,
                pos, normalize_brand_text(pos), "",
                item.get("postcode"), item.get("city"), "",
                item.get("latitude"), item.get("longitude"),
                "official_api", clean(item.get("source_url")),
            )
            if row:
                rows.append(row)
    return rows


def fetch_byd():
    return load_byd_sales_points(BYD_SALES_POINTS)


def fetch_jlr_group(brand):
    """Grid-sample Jaguar Land Rover's shared, unauthenticated retailer-locator API.

    The API caps results at 30 per call and ignores radius beyond that, so
    coverage comes from sampling many points (like the Renault/Dacia grid)
    and deduplicating by the dealer's stable ciCode.
    """
    page_url = "https://www.landrover.es/national-dealer-locator.html"
    endpoint = "https://retailerlocator.jaguarlandrover.com/dealers"
    found = {}
    for lat, lon in GRID:
        query = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "requestMarketLocale": "es_es",
            "brand": brand, "filter": "dealer", "radius": 150,
            "unitOfMeasure": "Kilometres", "country": "es",
            "fetchOpeningTimes": "false",
        })
        payload = json.loads(get(f"{endpoint}?{query}"))
        for item in payload.get("dealers") or []:
            code = item.get("ciCode")
            if code:
                found[code] = item
    rows = []
    for item in found.values():
        sells_new = any(
            (service.get("type") or "") == "sales"
            for service in item.get("services") or []
        )
        if not sells_new:
            continue
        address = item.get("address") or {}
        street = clean(" ".join(filter(None, (
            address.get("line1"), address.get("line2"),
        ))))
        row = make_point(
            brand, item.get("ciCode"), item.get("name"), item.get("name"),
            item.get("ciCode"), street, address.get("postCode"),
            address.get("town"), address.get("county"),
            item.get("latitude"), item.get("longitude"),
            "official_api", page_url,
        )
        if row:
            rows.append(row)
    return rows


def fetch_landrover():
    return fetch_jlr_group("Land Rover")


def fetch_jaguar():
    return fetch_jlr_group("Jaguar")


def mercedes_dealers():
    """Fetch the complete Spanish network from Mercedes-Benz's public locator."""
    global _MERCEDES_DEALERS
    if _MERCEDES_DEALERS is not None:
        return _MERCEDES_DEALERS
    page_url = (
        "https://www.mercedes-benz.es/passengercars/mercedes-benz-cars/"
        "dealer-locator.html/"
    )
    page = html.unescape(text(page_url))
    key = re.search(r'"apiKey"\s*:\s*"([^"]+)"', page)
    profile = re.search(r'"searchProfileCode"\s*:\s*"([^"]+)"', page)
    if not key or not profile:
        raise RuntimeError("Mercedes-Benz locator configuration not found")
    endpoint = (
        "https://api.oneweb.mercedes-benz.com/dms-plus/v3/"
        "api/dealers/market"
    )
    dealers = []
    for page_number in range(1, 21):
        query = urllib.parse.urlencode({
            "marketCode": "ES", "searchProfile": profile.group(1),
            "page": page_number, "size": 25, "includeFields": "*",
        })
        payload = json.loads(get(
            f"{endpoint}?{query}", headers={"x-apikey": key.group(1)}
        ))
        current = payload.get("dealers") or []
        dealers.extend(current)
        if len(current) < 25:
            break
    if not dealers:
        raise RuntimeError("Mercedes-Benz dealer payload is empty")
    _MERCEDES_DEALERS = dealers
    return dealers


def parse_mercedes_sales_points(dealers, brand, product_group):
    """Keep only valid new-vehicle sales services for one Mercedes product line."""
    page_url = (
        "https://www.mercedes-benz.es/passengercars/mercedes-benz-cars/"
        "dealer-locator.html/"
    )
    rows = []
    for item in dealers:
        sells_new = any(
            str((value.get("service") or {}).get("id")) in {"120", "900"}
            and (value.get("productGroup") or {}).get("id") == product_group
            and (value.get("validity") or {}).get("valid", True)
            for value in item.get("offeredServices") or []
        )
        if not sells_new:
            continue
        address = item.get("address") or {}
        coordinates = address.get("coordinates") or {}
        names = [
            clean(value.get("businessName")) for value in item.get("brands") or []
            if clean(value.get("businessName"))
        ]
        dealer_name = names[0] if names else item.get("legalName")
        street = clean(" ".join(filter(None, (
            address.get("street"), address.get("streetNumber"),
        ))))
        row = make_point(
            brand, item.get("companyId"), dealer_name, dealer_name,
            item.get("outletId"), street, address.get("zipCode"),
            address.get("city"), (address.get("region") or {}).get("province"),
            coordinates.get("latitude"), coordinates.get("longitude"),
            "official_api", page_url,
        )
        if row:
            rows.append(row)
    return rows


def fetch_mercedes(brand, product_group):
    return parse_mercedes_sales_points(mercedes_dealers(), brand, product_group)


def normalize_brand_text(value):
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", value.upper()).split())


def osm_brand_index():
    return {
        normalize_brand_text(alias): brand
        for brand, aliases in DGT_BRAND_ALIASES.items()
        for alias in aliases
    }


def match_osm_brands(tags):
    index = osm_brand_index()
    matches = {}
    explicit = ";".join(filter(None, (tags.get("brand:sales"), tags.get("brand"))))
    for value in re.split(r"[;,|/]", explicit):
        normalized = normalize_brand_text(value)
        if not normalized:
            continue
        if normalized in index:
            matches[index[normalized]] = "openstreetmap_brand_tag"
            continue
        padded = f" {normalized} "
        for alias, brand in sorted(index.items(), key=lambda item: len(item[0]), reverse=True):
            if f" {alias} " in padded:
                matches[brand] = "openstreetmap_brand_tag"
    if matches:
        return matches

    haystack = normalize_brand_text(" ".join(filter(None, (
        tags.get("name"), tags.get("operator"),
    ))))
    padded = f" {haystack} "
    for alias, brand in sorted(index.items(), key=lambda item: len(item[0]), reverse=True):
        if f" {alias} " in padded:
            matches[brand] = "openstreetmap_name_match"
    return matches


def fetch_osm_dealers(excluded=()):
    excluded = set(excluded)
    found = {}
    query = (
        '[out:json][timeout:180];'
        'area["ISO3166-1"="ES"][admin_level=2]->.spain;'
        'nwr["shop"="car"]["name"](area.spain);'
        'out center tags;'
    )
    url = f"{OSM_OVERPASS_URL}?{urllib.parse.urlencode({'data': query})}"
    payload = json.loads(get(url, timeout=240))
    if payload.get("remark"):
        raise RuntimeError(f"Incomplete OpenStreetMap extraction: {payload['remark']}")
    elements = payload.get("elements") or []
    raw_elements = len(elements)
    for item in elements:
        tags = item.get("tags") or {}
        if tags.get("second_hand") == "only":
            continue
        if tags.get("service:vehicle:new_car_sales") == "no":
            continue
        center = item.get("center") or item
        matches = match_osm_brands(tags)
        for brand, source_kind in matches.items():
            if brand in excluded:
                continue
            osm_id = f"osm:{item.get('type')}:{item.get('id')}"
            name = tags.get("name")
            address = clean(" ".join(filter(None, (
                tags.get("addr:street"), tags.get("addr:housenumber"),
            ))))
            row = make_point(
                brand, osm_id, name, name, osm_id, address,
                tags.get("addr:postcode"), tags.get("addr:city"),
                tags.get("addr:province"), center.get("lat"), center.get("lon"),
                source_kind, f"https://www.openstreetmap.org/{item.get('type')}/{item.get('id')}",
                source_confidence="community",
            )
            if row:
                found[(brand, osm_id)] = row
    rows = list(found.values())
    if raw_elements < 1500 or len(rows) < 500:
        raise RuntimeError(
            f"Incomplete OpenStreetMap extraction: {raw_elements} car shops, "
            f"{len(rows)} brand matches"
        )
    return rows

FETCHERS = {
    "Toyota": fetch_toyota, "Renault": lambda: fetch_renault_group("Renault"),
    "Dacia": lambda: fetch_renault_group("Dacia"), "Hyundai": fetch_hyundai,
    "Kia": fetch_kia, "Seat": lambda: fetch_seat_group("Seat"),
    "Cupra": lambda: fetch_seat_group("Cupra"),
    "Lexus": fetch_lexus, "Nissan": fetch_nissan, "Audi": fetch_audi,
    "Mercedes": lambda: fetch_mercedes("Mercedes", "PC"),
    "Mercedes-V": lambda: fetch_mercedes("Mercedes-V", "VAN"),
    "Porsche": fetch_porsche,
    "Volvo": fetch_volvo,
    "Tesla": fetch_tesla,
    "BYD": fetch_byd,
    "Land Rover": fetch_landrover,
    "Jaguar": fetch_jaguar,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brands", default=",".join(SUPPORTED))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--official-only", action="store_true",
        help="Skip the lower-confidence OpenStreetMap fallback",
    )
    args = parser.parse_args()
    canonical_by_upper = {name.upper(): name for name in FETCHERS}
    brands = [
        canonical_by_upper.get(value.strip().upper(), value.strip().title())
        for value in args.brands.split(",") if value.strip()
    ]
    unsupported = sorted(set(brands) - set(FETCHERS))
    if unsupported:
        parser.error("Unsupported brands: " + ", ".join(unsupported))
    rows, summary = [], {}
    for brand in brands:
        current = FETCHERS[brand]()
        minimum = MINIMUM_SALES_POINTS[brand]
        if len(current) < minimum:
            raise RuntimeError(
                f"Incomplete {brand} extraction: {len(current)} sales points; "
                f"expected at least {minimum}"
            )
        rows.extend(current)
        summary[brand] = {"sales_points": len(current), "dealer_names": len({r["dealer_name"] for r in current})}
    if not args.official_only:
        # BMW uses the internal active BUNO master and municipality territories.
        community = fetch_osm_dealers(excluded=set(brands) | {"BMW"})
        rows.extend(community)
        for brand in sorted({row["brand"] for row in community}):
            current = [row for row in community if row["brand"] == brand]
            summary[brand] = {
                "sales_points": len(current),
                "dealer_names": len({row["dealer_name"] for row in current}),
                "source_confidence": "community",
            }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["brand"], r["postcode"], r["point_of_sale"])))
    print(json.dumps({"output": str(output), "rows": len(rows), "brands": summary}, indent=2))


if __name__ == "__main__":
    main()
