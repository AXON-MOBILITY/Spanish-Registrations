#!/usr/bin/env python3
"""Build and audit a BMW postcode-to-POS geographic proxy.

This does not identify the selling dealer. It compresses the existing
municipality-to-territory BMW master into postcode territories observed in DGT
BMW Private registrations.

Examples:
  python scripts/audit_bmw_postcode_proxy.py --yyyymm 202606
  python scripts/audit_bmw_postcode_proxy.py --source C:\data\export_mensual_mat_202606.zip
"""

import argparse
import collections
import csv
import json
import os
import re
import tempfile
import unicodedata
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

import process_month as pm


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_MASTER = REPO_ROOT / "masters" / "master_concesin_bmw.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "analysis"

F_MARCA = (17, 47)
F_MODELO = (47, 69)
F_PROVINCIA_VEH = (152, 154)
F_CODIGO_POSTAL = (165, 170)
F_PERSONA_FJ = (179, 180)
F_SERVICIO = (189, 192)
F_MUNICIPIO_INE = (192, 197)
F_MUNICIPIO = (197, 227)
F_RENTING = (242, 243)

POSTCODE_RE = re.compile(r"^[0-5][0-9]{4}$")

MASTER_PROVINCE_NAMES = {
    "07": "ISLAS BALEARES",
    "20": "GUIPUZCOA",
    "35": "LAS PALMAS",
    "38": "SANTA CRUZ DE TENERIFE",
    "48": "VIZCAYA",
}

# Exact, reviewed aliases for abbreviations and bilingual names used by DGT.
MUNICIPALITY_ALIASES = {
    ("03", "ALICANTE"): "ALICANTE ALACANT",
    ("03", "ALCOY"): "ALCOY ALCOI",
    ("03", "CAMPELLO"): "EL CAMPELLO",
    ("03", "ELCHE"): "ELCHE ELX",
    ("03", "JAVEA"): "JAVEA XABIA",
    ("08", "S CUGAT DEL VALLES"): "SANT CUGAT DEL VALLES",
    ("08", "S JULIA VILATORTA"): "SANT JULIA DE VILATORTA",
    ("11", "EL PUERTO STA MARIA"): "EL PUERTO DE SANTA MARIA",
    ("11", "JEREZ DE LA FTRA"): "JEREZ DE LA FRONTERA",
    ("12", "BENICASIM"): "BENICASIM BENICASSIM",
    ("12", "CASTELLO PLANA"): "CASTELLON DE LA PLANA CASTELLO DE LA PLANA",
    ("15", "SANTIAGO"): "SANTIAGO DE COMPOSTELA",
    ("28", "SAN SEBASTIAN REYES"): "SAN SEBASTIAN DE LOS REYES",
    ("28", "VILLANUEVA DE CANADA"): "VILLANUEVA DE LA CANADA",
    ("35", "LAS PALMAS G C"): "LAS PALMAS DE GRAN CANARIA",
    ("38", "LA LAGUNA"): "SAN CRISTOBAL DE LA LAGUNA",
    ("38", "S C TENERIFE"): "SANTA CRUZ DE TENERIFE",
    ("46", "LA ELIANA"): "ELIANA L",
    ("07", "PALMA"): "PALMA DE MALLORCA",
}


def normalize_text(value):
    value = unicodedata.normalize("NFKD", (value or "").strip().upper())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_municipality(value):
    normalized = normalize_text(value)
    tokens = normalized.split()
    if len(tokens) > 1 and tokens[-1] in {"A", "O", "EL", "LA", "LOS", "LAS"}:
        tokens = [tokens[-1]] + tokens[:-1]
    return " ".join(tokens)


def normalize_header(value):
    return normalize_text(value).replace(" ", "_")


def _row_by_normalized_header(row):
    return {normalize_header(key): (value or "").strip() for key, value in row.items()}


def _first(row, *names):
    for name in names:
        value = row.get(normalize_header(name), "")
        if value:
            return value
    return ""


def load_master(path):
    """Return unambiguous municipality territories and master diagnostics."""
    by_municipality = collections.defaultdict(dict)
    dealers = set()
    points_of_sale = set()
    rows = 0

    with open(path, encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = _row_by_normalized_header(raw)
            province = _first(row, "Provincia")
            municipality = _first(row, "Municipio")
            dealer = _first(row, "Concesin", "Concesion")
            dealer_id = _first(row, "Id_Concesin", "Id_Concesion")
            pos = _first(row, "Puntos_de_Venta", "Punto_de_Venta")
            pos_id = _first(row, "Id_Punto_de_Venta")

            key = (normalize_text(province), normalize_municipality(municipality))
            if not all(key) or not pos_id:
                continue

            territory = {
                "dealer": dealer,
                "dealer_id": dealer_id,
                "pos": pos,
                "pos_id": pos_id,
            }
            by_municipality[key][pos_id] = territory
            dealers.add(dealer_id)
            points_of_sale.add(pos_id)
            rows += 1

    ambiguous = {key: values for key, values in by_municipality.items() if len(values) > 1}
    unambiguous = {
        key: next(iter(values.values()))
        for key, values in by_municipality.items()
        if len(values) == 1
    }
    by_name_keys = collections.defaultdict(list)
    for key, territory in unambiguous.items():
        by_name_keys[key[1]].append((key, territory))
    unique_name_master = {
        name: values[0][1]
        for name, values in by_name_keys.items()
        if len(values) == 1
    }

    diagnostics = {
        "master_rows": rows,
        "master_municipalities": len(by_municipality),
        "master_dealers": len(dealers),
        "master_points_of_sale": len(points_of_sale),
        "master_ambiguous_municipalities": len(ambiguous),
        "master_unique_municipality_names": len(unique_name_master),
    }
    return unambiguous, ambiguous, unique_name_master, diagnostics


def valid_postcode(value):
    return bool(POSTCODE_RE.fullmatch((value or "").strip())) and value != "00000"


def is_bmw_private(line):
    """Apply the production scope/channel rules, then retain BMW Private."""
    if len(line) < 714:
        return False
    if not pm.passes_dgt_scope_filters(line):
        return False

    marca_raw = line[F_MARCA[0] : F_MARCA[1]]
    modelo = line[F_MODELO[0] : F_MODELO[1]].strip().upper()
    marca = pm.normalize_marca(marca_raw, modelo)
    if marca != "BMW":
        return False
    if not pm.es_turismo_o_furgoneta(line):
        return False

    servicio = line[F_SERVICIO[0] : F_SERVICIO[1]]
    persona = line[F_PERSONA_FJ[0] : F_PERSONA_FJ[1]]
    renting = line[F_RENTING[0] : F_RENTING[1]]
    municipality_code = line[F_MUNICIPIO_INE[0] : F_MUNICIPIO_INE[1]]
    return pm.classify(
        servicio, persona, renting, municipality_code, marca
    ) == "Private"


def decode_line(raw):
    if isinstance(raw, str):
        return raw.rstrip("\r\n")
    return raw.rstrip(b"\r\n").decode("latin-1", errors="replace")


def audit_lines(
    lines,
    master,
    ambiguous_master,
    master_by_unique_name,
    dominance_threshold=1.0,
):
    """Return postcode proxy rows, audit metrics and unmatched municipalities."""
    metrics = collections.Counter()
    postcode_evidence = collections.defaultdict(
        lambda: {
            "pos_counts": collections.Counter(),
            "territories": {},
            "municipalities": collections.defaultdict(set),
        }
    )
    unmatched = collections.Counter()

    for raw in lines:
        metrics["raw_rows"] += 1
        line = decode_line(raw)
        if len(line) < 714:
            metrics["short_or_header_rows"] += 1
            continue
        if not is_bmw_private(line):
            continue

        metrics["bmw_private_rows"] += 1
        postcode = line[F_CODIGO_POSTAL[0] : F_CODIGO_POSTAL[1]].strip()
        if not valid_postcode(postcode):
            metrics["invalid_postcode_rows"] += 1
            continue
        metrics["valid_postcode_rows"] += 1

        municipality_code = line[F_MUNICIPIO_INE[0] : F_MUNICIPIO_INE[1]].strip()
        province_code = (
            municipality_code[:2]
            if len(municipality_code) == 5 and municipality_code.isdigit()
            else ""
        )
        province = MASTER_PROVINCE_NAMES.get(
            province_code, pm.PROV_NAMES.get(province_code, "")
        )
        municipality = line[F_MUNICIPIO[0] : F_MUNICIPIO[1]].strip()
        if not municipality:
            metrics["blank_municipality_name_rows"] += 1
        raw_municipality_key = normalize_text(municipality)
        municipality_key = MUNICIPALITY_ALIASES.get(
            (province_code, raw_municipality_key),
            normalize_municipality(municipality),
        )
        master_key = (normalize_text(province), municipality_key)

        if master_key in ambiguous_master:
            metrics["ambiguous_master_rows"] += 1
            continue
        territory = master.get(master_key)
        if territory is None:
            territory = master_by_unique_name.get(municipality_key)
            if territory is not None:
                metrics["unique_name_fallback_rows"] += 1
        if territory is None:
            metrics["unmatched_municipality_rows"] += 1
            unmatched[(province_code, province, municipality)] += 1
            continue

        metrics["municipality_matched_rows"] += 1
        postcode_key = (province_code, postcode)
        evidence = postcode_evidence[postcode_key]
        pos_id = territory["pos_id"]
        evidence["pos_counts"][pos_id] += 1
        evidence["territories"][pos_id] = territory
        evidence["municipalities"][pos_id].add(municipality)

    proxy_rows = []
    ambiguous_postcodes = 0
    resolved_observations = 0

    for (province_code, postcode), evidence in sorted(postcode_evidence.items()):
        counts = evidence["pos_counts"]
        total = sum(counts.values())
        pos_id, support = counts.most_common(1)[0]
        dominance = support / total
        alternatives = len(counts)

        if alternatives == 1:
            status = "territory_exact"
        elif dominance >= dominance_threshold:
            status = "territory_dominant"
        else:
            status = "ambiguous"
            ambiguous_postcodes += 1

        territory = evidence["territories"][pos_id]
        if status != "ambiguous":
            resolved_observations += total

        proxy_rows.append(
            {
                "province_code": province_code,
                "postcode": postcode,
                "dealer_method": "geo_territory_proxy",
                "territory_status": status,
                "dealer": territory["dealer"] if status != "ambiguous" else "",
                "dealer_id_proxy": territory["dealer_id"] if status != "ambiguous" else "",
                "point_of_sale": territory["pos"] if status != "ambiguous" else "",
                "pos_id_proxy": pos_id if status != "ambiguous" else "",
                "observed_bmw_private": total,
                "winning_support": support,
                "dominance": round(dominance, 6),
                "candidate_points_of_sale": alternatives,
                "municipalities": " | ".join(
                    sorted(
                        municipality
                        for values in evidence["municipalities"].values()
                        for municipality in values
                    )
                ),
            }
        )

    valid = metrics["valid_postcode_rows"]
    matched = metrics["municipality_matched_rows"]
    metrics.update(
        {
            "postcode_territories": len(proxy_rows),
            "ambiguous_postcodes": ambiguous_postcodes,
            "resolved_observations": resolved_observations,
        }
    )
    summary = dict(metrics)
    summary["municipality_match_coverage"] = round(matched / valid, 6) if valid else 0.0
    summary["resolved_postcode_coverage"] = (
        round(resolved_observations / valid, 6) if valid else 0.0
    )
    summary["dominance_threshold"] = dominance_threshold
    summary["method"] = "geo_territory_proxy"
    summary["warning"] = (
        "This is a domicile-territory proxy, not the observed selling dealer."
    )

    unmatched_rows = [
        {
            "province_code": key[0],
            "province": key[1],
            "municipality": key[2],
            "bmw_private_rows": count,
        }
        for key, count in unmatched.most_common()
    ]
    summary["unmatched_examples"] = unmatched_rows[:20]
    return proxy_rows, summary, unmatched_rows


@contextmanager
def source_path(source=None, yyyymm=None):
    if source:
        yield Path(source)
        return

    if not yyyymm or not re.fullmatch(r"20[0-9]{4}", yyyymm):
        raise ValueError("Provide --source or a YYYYMM value with --yyyymm")

    url = pm.get_url(yyyymm)
    with tempfile.TemporaryDirectory(prefix="dgt_bmw_cp_") as temp_dir:
        path = Path(temp_dir) / ("export_mensual_mat_" + yyyymm + ".zip")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=180) as response, open(path, "wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        yield path


@contextmanager
def open_lines(path):
    path = Path(path)
    if path.suffix.lower() != ".zip":
        with open(path, "rb") as handle:
            yield handle
        return

    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if not names:
            raise ValueError("ZIP without a TXT registration file")
        with archive.open(names[0]) as handle:
            yield handle


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Audit BMW Private postcode-to-POS geographic proxy"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="Local DGT monthly TXT or ZIP")
    group.add_argument("--yyyymm", help="Download a DGT monthly ZIP, format YYYYMM")
    parser.add_argument("--master", default=str(DEFAULT_MASTER))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument(
        "--dominance-threshold",
        type=float,
        default=1.0,
        help="Resolve multi-POS postcodes only above this share; default 1.0",
    )
    args = parser.parse_args()

    if not 0.5 <= args.dominance_threshold <= 1.0:
        parser.error("--dominance-threshold must be between 0.5 and 1.0")

    master, ambiguous_master, master_by_unique_name, master_metrics = load_master(
        args.master
    )
    with source_path(args.source, args.yyyymm) as input_path:
        with open_lines(input_path) as lines:
            proxy_rows, audit, unmatched = audit_lines(
                lines,
                master,
                ambiguous_master,
                master_by_unique_name,
                args.dominance_threshold,
            )

    period = args.yyyymm or Path(args.source).stem
    output_dir = Path(args.out_dir)
    proxy_path = output_dir / ("bmw_postcode_proxy_" + period + ".csv")
    unmatched_path = output_dir / ("bmw_postcode_unmatched_" + period + ".csv")
    audit_path = output_dir / ("bmw_postcode_audit_" + period + ".json")

    proxy_fields = [
        "province_code",
        "postcode",
        "dealer_method",
        "territory_status",
        "dealer",
        "dealer_id_proxy",
        "point_of_sale",
        "pos_id_proxy",
        "observed_bmw_private",
        "winning_support",
        "dominance",
        "candidate_points_of_sale",
        "municipalities",
    ]
    unmatched_fields = [
        "province_code",
        "province",
        "municipality",
        "bmw_private_rows",
    ]
    write_csv(proxy_path, proxy_rows, proxy_fields)
    write_csv(unmatched_path, unmatched, unmatched_fields)

    payload = {
        "period": period,
        "source": str(args.source or pm.get_url(args.yyyymm)),
        "master": str(args.master),
        "master_metrics": master_metrics,
        "audit": audit,
        "outputs": {
            "postcode_proxy": str(proxy_path),
            "unmatched_municipalities": str(unmatched_path),
        },
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
