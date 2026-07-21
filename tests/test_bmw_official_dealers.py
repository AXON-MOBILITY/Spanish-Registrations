"""BMW internal master, official-source and dealer-filter regression tests."""

import csv
import os
import sys
from pathlib import Path


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import audit_multibrand_dealer_proxy as proxy
import bmw_dealer_territory as bmw
import build_dealer_points as master
import process_month as pm


ROOT = Path(__file__).parent.parent


def test_bmw_master_contains_only_active_normalized_dealer_names():
    with (ROOT / "masters" / "master_bmw_active_dealers.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 54
    assert len({row["dealer_code"] for row in rows}) == 53
    assert all(row["dealer_name"] == row["dealer_name"].lower() for row in rows)
    assert all(row["source_confidence"] == "internal" for row in rows)
    assert not {"1", "2", "4", "100197", "100820"} & {
        row["dealer_id"] for row in rows
    }


def test_ceres_and_mandel_are_separate_active_territories():
    context = bmw.load_context()

    caceres = bmw.resolve("10", "Caceres", context, pm.PROV_NAMES)
    badajoz = bmw.resolve("06", "Badajoz", context, pm.PROV_NAMES)

    assert caceres["dealer_id"] == "100380:ceres-motor"
    assert caceres["dealer_estimated"] == "ceres motor"
    assert badajoz["dealer_id"] == "100380:mandel-motor"
    assert badajoz["dealer_estimated"] == "mandel motor"


def test_old_momentum_code_resolves_to_current_internal_dealer():
    dealer = bmw.resolve("20", "Abaltzisketa", bmw.load_context(), pm.PROV_NAMES)

    assert dealer["dealer_id"] == "100917"
    assert dealer["dealer_estimated"] == "momentumnorte"
    assert dealer["source_confidence"] == "internal"


def test_official_only_loader_drops_community_and_generic_names(tmp_path):
    path = tmp_path / "dealers.csv"
    base = {
        "brand": "Toyota",
        "dealer_id": "official-1",
        "dealer_name": "TOYOTA Dealer Norte",
        "point_of_sale": "Centro",
        "point_of_sale_id": "official-1",
        "address": "",
        "postcode": "28001",
        "city": "Madrid",
        "province": "Madrid",
        "latitude": "40.4",
        "longitude": "-3.7",
        "source_kind": "official_test",
        "source_confidence": "official",
        "source_url": "https://example.test/official",
        "retrieved_date": "2026-07-20",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=master.FIELDS)
        writer.writeheader()
        writer.writerow(base)
        writer.writerow({
            **base,
            "dealer_id": "community-1",
            "dealer_name": "Taller Ejemplo",
            "source_confidence": "community",
        })
        writer.writerow({
            **base,
            "dealer_id": "generic-1",
            "dealer_name": "TOYOTA",
        })

    points = proxy.load_points(path, official_only=True)

    assert [row["dealer_id"] for row in points["Toyota"]] == ["official-1"]
    assert points["Toyota"][0]["dealer_name"] == "dealer norte"


def test_dealer_selection_validates_choice_and_resolves_synchronously():
    # The dealer filter uses its own dropdown (not a native <datalist>, which
    # truncates large lists and renders an uncontrollably tall native popup)
    # so selection must resolve synchronously against DEALER_LABEL_TO_VALUE /
    # DEALER_CHOICES with no async gap where the underlying data could change.
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")

    select_fn = html.split("function selectDealerOption(value){", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "DEALER_CHOICES.has(value)" in select_fn
    assert "F.dealers.add(value)" in select_fn
    assert "await" not in select_fn and ".then(" not in select_fn

    keydown_fn = html.split("function onDealerKeydown(event){", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "DEALER_LABEL_TO_VALUE.get(label)" in keydown_fn
    assert "selectDealerOption(value)" in keydown_fn
