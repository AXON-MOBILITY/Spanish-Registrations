#!/usr/bin/env python3
"""Build a normalized sales-point master from official brand locators."""

import argparse
import csv
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "masters" / "master_dealer_points.csv"
USER_AGENT = "AxonMobilityDealerMaster/1.0"
SUPPORTED = ("Toyota", "Renault", "Dacia", "Hyundai", "Kia", "Seat", "Cupra")
MINIMUM_SALES_POINTS = {
    "Toyota": 140, "Renault": 300, "Dacia": 300,
    "Hyundai": 140, "Kia": 180, "Seat": 170, "Cupra": 85,
}
GRID = (
    (43.36, -8.41), (43.26, -2.94), (42.82, -1.64), (41.65, -0.89),
    (41.39, 2.17), (39.47, -0.38), (38.35, -0.48), (37.98, -1.13),
    (37.18, -3.60), (36.72, -4.42), (37.39, -5.99), (38.88, -6.97),
    (40.42, -3.70), (41.65, -4.72), (43.53, -5.66), (28.12, -15.44),
    (28.46, -16.25), (39.57, 2.65),
)
FIELDS = (
    "brand", "dealer_id", "dealer_name", "point_of_sale", "point_of_sale_id",
    "address", "postcode", "city", "province", "latitude", "longitude",
    "source_kind", "source_url", "retrieved_date",
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
               province, lat, lon, source_kind, source_url):
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
    if not all((dealer_id, dealer_name, pos_id, pos, cp)):
        return None
    return {
        "brand": brand, "dealer_id": dealer_id,
        "dealer_name": dealer_name, "point_of_sale": pos,
        "point_of_sale_id": pos_id, "address": clean(address),
        "postcode": cp, "city": clean(city), "province": clean(province),
        "latitude": f"{lat:.7f}", "longitude": f"{lon:.7f}",
        "source_kind": source_kind, "source_url": source_url,
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

FETCHERS = {
    "Toyota": fetch_toyota, "Renault": lambda: fetch_renault_group("Renault"),
    "Dacia": lambda: fetch_renault_group("Dacia"), "Hyundai": fetch_hyundai,
    "Kia": fetch_kia, "Seat": lambda: fetch_seat_group("Seat"),
    "Cupra": lambda: fetch_seat_group("Cupra"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brands", default=",".join(SUPPORTED))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    brands = [value.strip().title() for value in args.brands.split(",") if value.strip()]
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
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["brand"], r["postcode"], r["point_of_sale"])))
    print(json.dumps({"output": str(output), "rows": len(rows), "brands": summary}, indent=2))


if __name__ == "__main__":
    main()
