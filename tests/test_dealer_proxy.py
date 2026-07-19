"""Pure tests for the official dealer master and geographic proxy."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import audit_multibrand_dealer_proxy as proxy
import build_dealer_points as master


def point(dealer_id, point_id, lat, lon, postcode="28001"):
    return {
        "dealer_id": dealer_id,
        "dealer_name": f"Dealer {dealer_id}",
        "point_of_sale_id": point_id,
        "point_of_sale": f"POS {point_id}",
        "postcode": postcode,
        "city": "Madrid",
        "latitude": lat,
        "longitude": lon,
        "source_url": "https://example.test/official",
    }


def test_master_normalizes_postcode_and_coordinates():
    row = master.make_point(
        "Toyota", "dealer", "Dealer", "Centro", "pos", "Calle Uno",
        "801", "Barcelona", "Barcelona", "41.38", "2.17",
        "official_test", "https://example.test",
    )

    assert row["postcode"] == "00801"
    assert row["latitude"] == "41.3800000"
    assert master.make_point(
        "Toyota", "dealer", "Dealer", "Centro", "pos", "", "28001",
        "Madrid", "Madrid", "95", "2", "test", "https://example.test",
    ) is None


def test_toyota_javascript_payload_decoder():
    decoded = master.decode_js(r"{\x22name\x22:\x22A\u002DB\x22}")

    assert decoded == '{"name":"A-B"}'


def test_nearest_dealer_is_resolved_when_gap_is_clear():
    row = proxy.assign_point(
        "Toyota", "28001", (40.0, -3.0),
        [point("A", "A1", 40.0, -3.0), point("B", "B1", 40.5, -3.0)],
    )

    assert row["territory_status"] == "estimated_nearest"
    assert row["dealer_estimated"] == "Dealer A"
    assert row["point_of_sale_estimated"] == "POS A1"
    assert row["confidence"] == "high"


def test_close_points_from_different_dealers_are_ambiguous():
    row = proxy.assign_point(
        "Kia", "28001", (40.0, -3.0),
        [point("A", "A1", 40.0, -3.0), point("B", "B1", 40.01, -3.0)],
    )

    assert row["territory_status"] == "ambiguous_dealer"
    assert row["dealer_estimated"] == ""
    assert row["point_of_sale_estimated"] == ""


def test_same_dealer_can_be_resolved_without_guessing_sales_point():
    row = proxy.assign_point(
        "Renault", "28001", (40.0, -3.0),
        [
            point("A", "A1", 40.0, -3.0),
            point("A", "A2", 40.01, -3.0),
            point("B", "B1", 40.5, -3.0),
        ],
    )

    assert row["territory_status"] == "dealer_resolved_pos_ambiguous"
    assert row["dealer_estimated"] == "Dealer A"
    assert row["point_of_sale_estimated"] == ""
    assert row["confidence"] == "medium"


def test_excessive_distance_does_not_assign_a_dealer():
    row = proxy.assign_point(
        "Hyundai", "28001", (40.0, -3.0),
        [point("A", "A1", 42.0, -3.0)],
    )

    assert row["territory_status"] == "too_far"
    assert row["dealer_estimated"] == ""
    assert row["confidence"] == "none"
