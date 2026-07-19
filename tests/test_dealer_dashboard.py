"""Tests for the dashboard dealer aggregate and compact dataset."""

import csv
import os
import sys
from collections import Counter


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import build_dashboard_data as dashboard
import process_month as pm


class FakeProxy:
    calls = 0

    @staticmethod
    def canonical_brand(value):
        return value.title()

    @staticmethod
    def valid_postcode(value):
        return value == "28001"

    @classmethod
    def assign_point(cls, brand, postcode, centroid, points):
        cls.calls += 1
        return {
            "dealer_estimated": "Dealer Norte",
            "dealer_id": "dealer-1",
            "confidence": "low",
            "source_confidence": "community",
        }


def dealer_key():
    return (
        "TOYOTA", "YARIS", "Private", "ICE", "Gasolina", "UKL1",
        "FOCUS SEGMENT", "Standard", "Hatchback", "28",
        "Dealer Norte", "dealer-1", "low", "community",
    )


def test_dealer_assignment_is_cached_by_brand_and_postcode():
    pm._DEALER_ASSIGNMENT_CACHE.clear()
    FakeProxy.calls = 0
    context = (
        FakeProxy,
        {"Toyota": [{"dealer_id": "dealer-1"}]},
        {"28001": (40.4, -3.7)},
    )

    first = pm._assign_dealer_proxy("TOYOTA", "28001", context)
    second = pm._assign_dealer_proxy("TOYOTA", "28001", context)

    assert first["dealer_estimated"] == "Dealer Norte"
    assert second == first
    assert FakeProxy.calls == 1


def test_save_dealer_csv_keeps_traceability_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "OUT_DIR", str(tmp_path))
    path = pm.save_dealer_csv(Counter({dealer_key(): 3}), "202606")

    with open(path, encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["marca"] == "TOYOTA"
    assert row["dealer_estimated"] == "Dealer Norte"
    assert row["confidence"] == "low"
    assert row["source_confidence"] == "community"
    assert row["count"] == "3"


def test_compact_dealer_dataset_preserves_dashboard_dimensions():
    records = [{
        "y": 2026,
        "m": 6,
        "marca": "Toyota",
        "modelo": "YARIS",
        "canal": "Private",
        "fuel": "ICE",
        "fuel_det": "Gasolina",
        "seg": "UKL1",
        "sub": "FOCUS SEGMENT",
        "hp": "Standard",
        "body": "Hatchback",
        "prov": "Madrid",
        "dealer": "Toyota | Dealer Norte",
        "confidence": "low",
        "source_confidence": "community",
        "n": 3,
    }]

    result = dashboard.build_records_dealer_json(records, 2026, 7)

    assert result["cols"][-4:] == [
        "dealer", "confidence", "source_confidence", "n",
    ]
    assert result["enums"]["dealer"] == ["Toyota | Dealer Norte"]
    assert result["rows"][0][-1] == 3
    assert result["total"] == 3
