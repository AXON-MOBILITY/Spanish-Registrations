"""Coverage and confidence tests for the all-brand dealer proxy."""

import csv
import inspect
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import audit_multibrand_dealer_proxy as proxy
import build_dealer_points as master


def community_point(dealer_id, latitude, longitude):
    return {
        "dealer_id": dealer_id,
        "dealer_name": dealer_id,
        "point_of_sale_id": dealer_id,
        "point_of_sale": dealer_id,
        "postcode": "28001",
        "city": "Madrid",
        "latitude": latitude,
        "longitude": longitude,
        "source_kind": "openstreetmap_brand_tag",
        "source_confidence": "community",
        "source_url": "https://www.openstreetmap.org/node/1",
    }


def test_registry_contains_every_brand_observed_in_june_2026():
    assert len(master.DGT_BRANDS) == 74
    assert {"Toyota", "Volkswagen", "Lynk & Co", "Mercedes-V", "Sin marca"} <= set(
        master.DGT_BRANDS
    )


def test_osm_explicit_brand_tag_has_priority_over_name():
    matches = master.match_osm_brands({
        "brand:sales": "Citroen;Peugeot",
        "name": "Automoviles Ejemplo",
    })

    assert matches == {
        "Citroen": "openstreetmap_brand_tag",
        "Peugeot": "openstreetmap_brand_tag",
    }


def test_osm_name_match_is_labelled_separately():
    matches = master.match_osm_brands({"name": "Talleres Volkswagen Norte"})

    assert matches == {"Volkswagen": "openstreetmap_name_match"}


def test_community_assignment_is_always_low_confidence():
    row = proxy.assign_point(
        "Volkswagen",
        "28001",
        (40.0, -3.0),
        [
            community_point("Community A", 40.0, -3.0),
            community_point("Community B", 41.0, -3.0),
        ],
    )

    assert row["territory_status"] == "estimated_nearest"
    assert row["confidence"] == "low"
    assert row["source_confidence"] == "community"
    assert row["dealer_method"] == "geo_nearest_community_sales_point_proxy"


def test_unmapped_brand_is_preserved_without_an_invented_name():
    row = proxy.unresolved_row("Zeekr", "28001", "unmapped_brand")

    assert row["territory_status"] == "unmapped_brand"
    assert row["dealer_estimated"] == ""
    assert row["confidence"] == "none"


def test_brand_aliases_are_canonicalized():
    assert proxy.canonical_brand("CITROEN") == "Citroen"
    assert proxy.canonical_brand("MERCEDES-BENZ VANS") == "Mercedes-V"
    assert proxy.canonical_brand("SSANGYONG") == "KG Mobility"

def test_mercedes_vans_share_the_documented_mercedes_sales_network(tmp_path):
    master_path = tmp_path / "dealers.csv"
    row = community_point("mercedes-madrid", 40.4, -3.7)
    row.update({
        "brand": "Mercedes",
        "address": "",
        "province": "Madrid",
        "retrieved_date": "2026-07-19",
    })
    with master_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=master.FIELDS)
        writer.writeheader()
        writer.writerow(row)

    points = proxy.load_points(master_path)

    assert points["Mercedes-V"][0]["dealer_id"] == "mercedes-madrid"
    assert points["Mercedes-V"][0]["brand"] == "Mercedes-V"

def test_dealer_name_variants_collapse_to_one_canonical_label():
    points = {
        "Citroen": [
            community_point("generic-upper", 40.0, -3.0),
            community_point("generic-accent", 40.1, -3.0),
            community_point("filinto-short", 40.2, -3.0),
            community_point("filinto-brand", 40.3, -3.0),
        ]
    }
    points["Citroen"][0]["dealer_name"] = "CITROEN"
    points["Citroen"][1]["dealer_name"] = "Citröen"
    points["Citroen"][2]["dealer_name"] = "Filinto Mota"
    points["Citroen"][3]["dealer_name"] = "Filinto Mota - Citroën"

    proxy.normalize_point_names(points)

    assert [point["dealer_id"] for point in points["Citroen"]] == [
        "generic-upper", "generic-accent", "filinto-short", "filinto-brand",
    ]
    assert [point["dealer_name"] for point in points["Citroen"]] == [
        "Punto de venta sin nombre", "Punto de venta sin nombre",
        "Filinto Mota", "Filinto Mota",
    ]


def test_osm_extraction_uses_the_spain_administrative_area():
    source = inspect.getsource(master.fetch_osm_dealers)

    assert '"ISO3166-1"="ES"' in source
    assert "area.spain" in source
    assert "OSM_BBOXES" not in source

def test_brand_is_removed_from_the_dealer_display_name():
    assert proxy._canonical_dealer_name(
        "Citroen", ["Citroën - Cormotor"]
    ) == "Cormotor"
    assert proxy._canonical_dealer_name(
        "Citroen", ["Citröen Automotor"]
    ) == "Automotor"
