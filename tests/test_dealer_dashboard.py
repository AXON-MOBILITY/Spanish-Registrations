"""Tests for the dashboard dealer aggregate and compact dataset."""

import csv
import os
import sys
from collections import Counter
from pathlib import Path


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

def test_dealer_filter_is_a_brand_grouped_select():
    html = (Path(__file__).parent.parent / "public" / "index.html").read_text(
        encoding="utf-8"
    )

    assert '<select id="f-dealer"' in html
    assert "document.createElement('optgroup')" in html
    assert "onDealerChange()" in html
    assert 'f-dealer-list' not in html

def test_historical_rows_use_the_canonical_master_name(tmp_path, monkeypatch):
    source = tmp_path / "dgt_dealer_202606.csv"
    fields = [
        "marca", "modelo", "canal", "fuel_type", "fuel", "segmento",
        "subseg", "hp", "body_type", "provincia", "dealer_estimated",
        "dealer_id", "confidence", "source_confidence", "count",
    ]
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "marca": "TOYOTA",
            "modelo": "YARIS",
            "canal": "Private",
            "fuel_type": "ICE",
            "fuel": "Gasolina",
            "segmento": "UKL1",
            "subseg": "FOCUS SEGMENT",
            "hp": "Standard",
            "body_type": "Hatchback",
            "provincia": "Madrid",
            "dealer_estimated": "TOYOTA Dealer Norte",
            "dealer_id": "dealer-1",
            "confidence": "low",
            "source_confidence": "official",
            "count": "3",
        })
    monkeypatch.setattr(
        dashboard,
        "_DEALER_NAME_BY_ID",
        {("Toyota", "dealer-1"): "dealer norte"},
    )

    rows = dashboard._load_dealer_records_file(source, 2026, 6)

    assert rows[0]["dealer"] == "Toyota | dealer norte"
    assert rows[0]["n"] == 3

def test_historical_rows_with_removed_point_ids_are_dropped(tmp_path, monkeypatch):
    source = tmp_path / "dgt_dealer_202606.csv"
    fields = ["marca", "dealer_estimated", "dealer_id", "count"]
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "marca": "CITROEN",
            "dealer_estimated": "Citroën Garage Foreign",
            "dealer_id": "removed-osm-point",
            "count": "4",
        })
    monkeypatch.setattr(dashboard, "_DEALER_NAME_BY_ID", {})

    assert dashboard._load_dealer_records_file(source, 2026, 6) == []
