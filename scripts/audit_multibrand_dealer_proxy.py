#!/usr/bin/env python3
"""Audit every observed DGT brand against the traceable sales-point master."""

import argparse
import collections
import csv
import io
import json
import math
import re
import tempfile
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

import process_month as pm
import build_dealer_points as dealer_master


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MASTER = ROOT / "masters" / "master_dealer_points.csv"
DEFAULT_OUTPUT = ROOT / "data" / "analysis"
GEONAMES_URL = "https://download.geonames.org/export/zip/ES.zip"
USER_AGENT = "AxonMobilityDealerAudit/1.0"

F_MARCA = pm.F_MARCA
F_MODELO = pm.F_MODELO
F_CODIGO_POSTAL = (165, 170)
F_PERSONA_FJ = (179, 180)
F_SERVICIO = (189, 192)
F_MUNICIPIO_INE = (192, 197)
F_RENTING = (242, 243)
POSTCODE_RE = re.compile(r"^[0-5][0-9]{4}$")

# Product lines that are separate brands in the DGT normalization but use the
# same physical sales network. Keep this explicit so no unrelated network is
# inferred merely because a brand has no master coverage.
SHARED_SALES_NETWORKS = {
    "Mercedes-V": "Mercedes",
}

GENERIC_DEALER_WORDS = {
    "CONCESIONARIO", "CONCESSIONARIO", "DEALER", "OFICIAL", "OFFICIAL",
}

OUTPUT_FIELDS = (
    "brand", "postcode", "dealer_method", "territory_status", "confidence",
    "dealer_estimated", "dealer_id", "point_of_sale_estimated", "point_of_sale_id",
    "dealer_postcode", "dealer_city", "distance_km", "next_dealer_distance_km",
    "observed_private", "source_kind", "source_confidence", "source_url",
)


def valid_postcode(value):
    return bool(POSTCODE_RE.fullmatch(value or "")) and value != "00000"


def dealer_name_key(brand, value):
    """Accent/case-insensitive key without redundant brand boilerplate."""
    normalized = dealer_master.normalize_brand_text(value)
    aliases = dealer_master.DGT_BRAND_ALIASES.get(brand, (brand,))
    brand_terms = {
        dealer_master.normalize_brand_text(alias)
        for alias in (brand, *aliases)
        if alias
    }
    for term in sorted(brand_terms, key=len, reverse=True):
        normalized = re.sub(
            r"(?<![A-Z0-9]){}(?![A-Z0-9])".format(re.escape(term)),
            " ",
            normalized,
        )
    words = [
        word for word in normalized.split()
        if word not in GENERIC_DEALER_WORDS
    ]
    return " ".join(words)


def _strip_brand_from_display(brand, value):
    """Remove brand text already supplied by the dashboard optgroup."""
    aliases = dealer_master.DGT_BRAND_ALIASES.get(brand, (brand,))
    patterns = [re.escape(alias) for alias in (brand, *aliases) if alias]
    if brand == "Citroen":
        patterns.append(r"Citr(?:o[eë]|öe)n")
    for pattern in sorted(set(patterns), key=len, reverse=True):
        value = re.sub(
            r"(?<!\w){}(?!\w)".format(pattern),
            " ",
            value,
            flags=re.IGNORECASE,
        )
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,;|-/()")


def _canonical_dealer_name(brand, names):
    """Choose one stable display value for source variants of the same dealer."""
    clean_names = sorted({
        dealer_master.clean(name).strip(" ,;|-/")
        for name in names if dealer_master.clean(name)
    })
    if not clean_names:
        return ""
    key = dealer_name_key(brand, clean_names[0])
    if not key:
        return ""

    def score(name):
        normalized = dealer_master.normalize_brand_text(name)
        aliases = dealer_master.DGT_BRAND_ALIASES.get(brand, (brand,))
        brand_hits = sum(
            normalized.count(dealer_master.normalize_brand_text(alias))
            for alias in (brand, *aliases) if alias
        )
        return brand_hits, len(normalized), normalized

    selected = min(clean_names, key=score)
    return _strip_brand_from_display(brand, selected).lower()


def normalize_point_names(points_by_brand):
    """Collapse spelling/case and shared-ID variants into stable dealer labels."""
    for brand, points in points_by_brand.items():
        grouped = collections.defaultdict(list)
        for point in points:
            grouped[dealer_name_key(brand, point.get("dealer_name", ""))].append(
                point.get("dealer_name", "")
            )
        canonical = {
            key: _canonical_dealer_name(brand, names)
            for key, names in grouped.items()
        }
        for point in points:
            key = dealer_name_key(brand, point.get("dealer_name", ""))
            point["dealer_name"] = canonical[key]

        by_dealer_id = collections.defaultdict(list)
        for point in points:
            by_dealer_id[point.get("dealer_id", "")].append(
                point.get("dealer_name", "")
            )
        dealer_canonical = {
            key: _canonical_dealer_name(brand, names)
            for key, names in by_dealer_id.items()
        }
        for point in points:
            point["dealer_name"] = dealer_canonical[point.get("dealer_id", "")]
    return points_by_brand

def load_points(path, official_only=False):
    result = collections.defaultdict(list)
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row.setdefault("source_confidence", "official")
            if official_only and row["source_confidence"] != "official":
                continue
            try:
                row["latitude"] = float(row["latitude"])
                row["longitude"] = float(row["longitude"])
            except (TypeError, ValueError):
                continue
            result[row["brand"]].append(row)
    normalize_point_names(result)
    for brand in list(result):
        result[brand] = [
            row for row in result[brand] if row.get("dealer_name")
        ]
    for target_brand, source_brand in SHARED_SALES_NETWORKS.items():
        if result.get(source_brand) and not result.get(target_brand):
            result[target_brand] = [
                {**row, "brand": target_brand}
                for row in result[source_brand]
            ]
    return result


def load_postcode_centroids(source=None):
    if source:
        raw = Path(source).read_bytes()
    else:
        request = urllib.request.Request(GEONAMES_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
    grouped = collections.defaultdict(list)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = next(name for name in archive.namelist() if name.upper().endswith("ES.TXT"))
        with archive.open(name) as handle:
            for raw_line in handle:
                fields = raw_line.decode("utf-8").rstrip("\n").split("\t")
                if len(fields) < 11 or not valid_postcode(fields[1]):
                    continue
                try:
                    grouped[fields[1]].append((float(fields[9]), float(fields[10])))
                except ValueError:
                    continue
    return {
        cp: (
            sum(lat for lat, _ in values) / len(values),
            sum(lon for _, lon in values) / len(values),
        )
        for cp, values in grouped.items()
    }


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def assign_point(brand, cp, centroid, points, max_distance=120.0, ambiguity_gap=8.0):
    lat, lon = centroid
    candidates = points
    ranked = sorted(
        [
            (haversine_km(lat, lon, point["latitude"], point["longitude"]), point)
            for point in candidates
        ],
        key=lambda item: (item[0], item[1]["point_of_sale_id"]),
    )
    distance, nearest = ranked[0]
    other_pos = next(
        ((value, point) for value, point in ranked[1:] if point["point_of_sale_id"] != nearest["point_of_sale_id"]),
        None,
    )
    other_dealer = next(
        ((value, point) for value, point in ranked[1:] if point["dealer_id"] != nearest["dealer_id"]),
        None,
    )
    competitor_distance = other_dealer[0] if other_dealer else None
    same_dealer_pos_close = bool(
        other_pos
        and other_pos[1]["dealer_id"] == nearest["dealer_id"]
        and other_pos[0] - distance < ambiguity_gap
    )

    if distance > max_distance:
        status, confidence, include_dealer, include_pos = "too_far", "none", False, False
    elif other_dealer and competitor_distance - distance < ambiguity_gap:
        status, confidence, include_dealer, include_pos = "ambiguous_dealer", "low", False, False
    elif same_dealer_pos_close:
        status, confidence, include_dealer, include_pos = "dealer_resolved_pos_ambiguous", "medium", True, False
    else:
        ratio = competitor_distance / max(distance, 0.5) if competitor_distance else 99.0
        confidence = "high" if ratio >= 1.75 and distance <= 35 else "medium"
        status, include_dealer, include_pos = "estimated_nearest", True, True

    source_confidence = nearest.get("source_confidence", "official")
    if source_confidence == "community" and include_dealer:
        confidence = "low"
    method = (
        "geo_nearest_community_sales_point_proxy"
        if source_confidence == "community"
        else "geo_nearest_official_sales_point_proxy"
    )

    return {
        "brand": brand,
        "postcode": cp,
        "dealer_method": method,
        "territory_status": status,
        "confidence": confidence,
        "dealer_estimated": nearest["dealer_name"] if include_dealer else "",
        "dealer_id": nearest["dealer_id"] if include_dealer else "",
        "point_of_sale_estimated": nearest["point_of_sale"] if include_pos else "",
        "point_of_sale_id": nearest["point_of_sale_id"] if include_pos else "",
        "dealer_postcode": nearest["postcode"] if include_dealer else "",
        "dealer_city": nearest["city"] if include_dealer else "",
        "distance_km": round(distance, 2),
        "next_dealer_distance_km": round(competitor_distance, 2) if competitor_distance is not None else "",
        "source_kind": nearest.get("source_kind", ""),
        "source_confidence": source_confidence,
        "source_url": nearest["source_url"],
    }


def canonical_brand(value):
    normalized = dealer_master.normalize_brand_text(value)
    index = {
        dealer_master.normalize_brand_text(alias): brand
        for brand, aliases in dealer_master.DGT_BRAND_ALIASES.items()
        for alias in (brand, *aliases)
    }
    return index.get(normalized) or value.strip().title()


def private_brand(line):
    if len(line) < 714 or not pm.passes_dgt_scope_filters(line):
        return None
    model = line[F_MODELO[0]:F_MODELO[1]].strip().upper()
    normalized = pm.normalize_marca(line[F_MARCA[0]:F_MARCA[1]], model)
    brand = canonical_brand(normalized)
    if not brand or not pm.es_turismo_o_furgoneta(line):
        return None
    channel = pm.classify(
        line[F_SERVICIO[0]:F_SERVICIO[1]],
        line[F_PERSONA_FJ[0]:F_PERSONA_FJ[1]],
        line[F_RENTING[0]:F_RENTING[1]],
        line[F_MUNICIPIO_INE[0]:F_MUNICIPIO_INE[1]],
        brand,
    )
    return brand if channel == "Private" else None


@contextmanager
def source_path(source=None, yyyymm=None):
    if source:
        yield Path(source)
        return
    if not yyyymm or not re.fullmatch(r"20[0-9]{4}", yyyymm):
        raise ValueError("Provide --source or --yyyymm YYYYMM")
    request = urllib.request.Request(pm.get_url(yyyymm), headers={"User-Agent": USER_AGENT})
    with tempfile.TemporaryDirectory(prefix="dgt_dealer_proxy_") as directory:
        path = Path(directory) / f"export_mensual_mat_{yyyymm}.zip"
        with urllib.request.urlopen(request, timeout=180) as response, open(path, "wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
        yield path


@contextmanager
def open_lines(path):
    path = Path(path)
    if path.suffix.lower() != ".zip":
        with open(path, "rb") as handle:
            yield handle
        return
    with zipfile.ZipFile(path) as archive:
        name = next(name for name in archive.namelist() if name.lower().endswith(".txt"))
        with archive.open(name) as handle:
            yield handle


def unresolved_row(brand, cp, status):
    return {
        "brand": brand,
        "postcode": cp,
        "dealer_method": "unavailable",
        "territory_status": status,
        "confidence": "none",
        "dealer_estimated": "",
        "dealer_id": "",
        "point_of_sale_estimated": "",
        "point_of_sale_id": "",
        "dealer_postcode": "",
        "dealer_city": "",
        "distance_km": "",
        "next_dealer_distance_km": "",
        "source_kind": "",
        "source_confidence": "",
        "source_url": "",
    }


def audit(lines, points, centroids):
    counts = collections.Counter()
    metrics = collections.Counter()
    for raw in lines:
        metrics["raw_rows"] += 1
        line = raw.rstrip(b"\r\n").decode("latin-1", errors="replace")
        brand = private_brand(line)
        if not brand:
            continue
        metrics["eligible_private_rows"] += 1
        cp = line[F_CODIGO_POSTAL[0]:F_CODIGO_POSTAL[1]].strip()
        if not valid_postcode(cp):
            cp = ""
        counts[(brand, cp)] += 1

    rows = []
    for (brand, cp), observed in sorted(counts.items()):
        if not cp:
            row = unresolved_row(brand, cp, "invalid_postcode")
        elif not points.get(brand):
            row = unresolved_row(brand, cp, "unmapped_brand")
        else:
            centroid = centroids.get(cp)
            if centroid is None:
                row = unresolved_row(brand, cp, "missing_centroid")
            else:
                row = assign_point(brand, cp, centroid, points[brand])
        row["observed_private"] = observed
        rows.append(row)
        metrics[row["territory_status"] + "_rows"] += observed

    resolved = sum(row["observed_private"] for row in rows if row["dealer_estimated"])
    eligible = metrics["eligible_private_rows"]
    observed_brands = sorted({brand for brand, _ in counts})
    per_brand = {}
    for brand in observed_brands:
        brand_rows = [row for row in rows if row["brand"] == brand]
        brand_eligible = sum(row["observed_private"] for row in brand_rows)
        brand_resolved = sum(
            row["observed_private"] for row in brand_rows if row["dealer_estimated"]
        )
        statuses = collections.Counter()
        for row in brand_rows:
            statuses[row["territory_status"]] += row["observed_private"]
        per_brand[brand] = {
            "eligible_private_rows": brand_eligible,
            "resolved_dealer_rows": brand_resolved,
            "dealer_coverage": round(brand_resolved / brand_eligible, 6) if brand_eligible else 0,
            "master_sales_points": len(points.get(brand) or []),
            "statuses": dict(statuses),
        }
    summary = dict(metrics)
    summary.update({
        "observed_brands": observed_brands,
        "brands_with_master": [brand for brand in observed_brands if points.get(brand)],
        "brands_without_master": [brand for brand in observed_brands if not points.get(brand)],
        "per_brand": per_brand,
        "postcode_rows": len(rows),
        "resolved_dealer_rows": resolved,
        "dealer_coverage": round(resolved / eligible, 6) if eligible else 0,
        "method": "geo_nearest_sales_point_proxy",
        "warning": "Estimated from domicile postcode; not the observed selling dealer.",
    })
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source")
    source.add_argument("--yyyymm")
    parser.add_argument("--master", default=str(DEFAULT_MASTER))
    parser.add_argument("--postcodes", help="Optional local GeoNames ES.zip")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    points = load_points(args.master)
    centroids = load_postcode_centroids(args.postcodes)
    with source_path(args.source, args.yyyymm) as path:
        with open_lines(path) as lines:
            rows, summary = audit(lines, points, centroids)
    period = args.yyyymm or Path(args.source).stem
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"dealer_postcode_proxy_{period}.csv"
    json_path = output_dir / f"dealer_postcode_audit_{period}.json"
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"audit": summary, "csv": str(csv_path)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
