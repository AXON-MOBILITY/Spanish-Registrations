"""Tests for official, new-vehicle dealer network ingestion."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import audit_multibrand_dealer_proxy as proxy
import bmw_dealer_territory as bmw_dealer
import build_dashboard_data as dashboard
import build_dealer_points as master


def test_nissan_parser_keeps_sales_and_drops_service_only():
    page = '''
    <script>var mijsontodas={"todas":[
      {"id":"sales-1","latitud":"40.4","longitud":"-3.7",
       "nombre":"Grupo Norte","direccion":"Calle Uno","cp":"28001",
       "poblacion":"Madrid","provincia":"Madrid",
       "link":"https://red.nissan.es/gruponorte",
       "ventasyservicios":"Ventas y servicio"},
      {"id":"service-1","latitud":"40.5","longitud":"-3.6",
       "nombre":"Taller Sur","direccion":"Calle Dos","cp":"28002",
       "poblacion":"Madrid","provincia":"Madrid","link":"",
       "ventasyservicios":"Servicio"}
    ]};</script>
    '''

    rows = master.parse_nissan_sales_points(page)

    assert [row["point_of_sale_id"] for row in rows] == ["sales-1"]
    assert rows[0]["dealer_id"] == "gruponorte"
    assert rows[0]["source_confidence"] == "official"


def test_lexus_parser_keeps_showrooms_and_drops_repairers():
    page = '''
    <div class="retailer-details">
      <h2>Premium Cars (Lexus Madrid) - Exposicion y Taller</h2>
      <li class="address">Calle Uno</li>
      <a data-gt-action="view-dealer" data-gt-dealerid="sales-1"
         data-gt-dealercity="Madrid" data-gt-dealerzipcode="28001"
         data-gt-dealerregion="Madrid" href="https://www.lexusauto.es/sales">
      </a>
    </div>
    <div class="retailer-details">
      <h2>Repair Cars (Lexus Madrid) - Reparador Autorizado</h2>
      <li class="address">Calle Dos</li>
      <a data-gt-action="view-dealer" data-gt-dealerid="repair-1"
         data-gt-dealercity="Madrid" data-gt-dealerzipcode="28002"
         data-gt-dealerregion="Madrid" href="https://www.lexusauto.es/repair">
      </a>
    </div>
    '''

    rows = master.parse_lexus_sales_points(
        page, {"28001": (40.4, -3.7), "28002": (40.5, -3.6)}
    )

    assert [row["point_of_sale_id"] for row in rows] == ["sales-1"]
    assert rows[0]["dealer_name"] == "Premium Cars"
    assert rows[0]["source_confidence"] == "official"


def test_same_official_dealer_id_uses_one_canonical_name():
    points = {
        "Nissan": [
            {"dealer_id": "group-1", "dealer_name": "Grupo Norte"},
            {"dealer_id": "group-1", "dealer_name": "Norte Motor"},
        ]
    }

    proxy.normalize_point_names(points)

    assert {row["dealer_name"] for row in points["Nissan"]} == {"grupo norte"}


def test_dashboard_normalizes_master_brand_keys(monkeypatch):
    monkeypatch.setattr(
        proxy,
        "load_points",
        lambda *args, **kwargs: {
            "Seat": [{"dealer_id": "seat-1", "dealer_name": "motor centro"}]
        },
    )
    monkeypatch.setattr(bmw_dealer, "load_active_dealers", lambda: {})
    monkeypatch.setattr(dashboard, "_DEALER_NAME_BY_ID", None)

    names = dashboard._dealer_name_by_id()

    assert names[("SEAT", "seat-1")] == "motor centro"
