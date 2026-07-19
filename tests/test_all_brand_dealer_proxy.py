"""Coverage and confidence tests for the all-brand dealer proxy."""

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
