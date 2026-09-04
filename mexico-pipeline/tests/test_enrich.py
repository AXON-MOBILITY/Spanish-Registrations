import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from enrich import classify_body_type, classify_fuel_type, enrich_row, normalize_model_name  # noqa: E402


def test_mhev_is_gasolina_not_electric():
    fuel, conf = classify_fuel_type("Crosstrek MHEV")
    assert fuel == "Gasolina"


def test_chevrolet_hev_substring_does_not_misfire():
    # "Chevrolet" contains the letters H-E-V but is not a hybrid signal.
    fuel, _ = classify_fuel_type("Chevrolet Express Cargo Van")
    assert fuel == "Gasolina"


def test_explicit_ev_suffix_is_electric():
    fuel, conf = classify_fuel_type("Blazer EV")
    assert fuel == "Electrico (BEV)"
    assert conf == "alta"


def test_phev_keyword():
    fuel, _ = classify_fuel_type("Outlander PHEV")
    assert fuel == "Hibrido enchufable (PHEV)"


def test_diesel_keyword():
    fuel, _ = classify_fuel_type("RAM 4000 Diesel")
    assert fuel == "Diesel"


def test_accented_electrico_keyword():
    fuel, _ = classify_fuel_type("Master E- Tech eléctrico")
    assert fuel == "Electrico (BEV)"


def test_body_type_from_segmento_suv():
    body, conf = classify_body_type("Xtrail", "Camiones ligeros", "SUV's")
    assert body == "SUV"


def test_body_type_hatchback_keyword():
    body, _ = classify_body_type("Mazda 2 Hatchback", "Automóviles", "Subcompactos")
    assert body == "Hatchback"


def test_override_table_wins_over_rules():
    result = enrich_row("BMW", "iX1", "Automóviles", "De Lujo")
    assert result["fuel_type"] == "Electrico (BEV)"
    assert result["body_type"] == "SUV"
    assert result["confidence"] == "alta"


def test_low_confidence_brand_without_override_downgrades():
    result = enrich_row("MOTORNATION", "STAR TRUCK", "Camiones ligeros", "Pick Ups")
    assert result["confidence"] == "baja"


def test_normalize_strips_trailing_dash_artifact():
    assert normalize_model_name("Toyota", "Tacoma-") == "Tacoma"


def test_normalize_merges_sedan_and_hatchback_suffix():
    assert normalize_model_name("KIA", "KIA K3 Sedán") == "K3"
    assert normalize_model_name("KIA", "KIA K3 Hatchback") == "K3"


def test_normalize_strips_redundant_brand_prefix():
    assert normalize_model_name("Honda", "Honda City") == "City"


def test_normalize_keeps_brand_prefix_when_remainder_is_numeric_only():
    # "Mazda 2" / "Chrysler 300" read as noise without the brand name.
    assert normalize_model_name("Mazda", "Mazda 2 Sedán") == "Mazda 2"
    assert normalize_model_name("Chrysler", "Chrysler 300") == "Chrysler 300"


def test_normalize_keeps_full_name_when_suffix_is_the_whole_model():
    # MINI badges trims as Coupe/Convertible/3 Ptas - the body word IS
    # the model name here, stripping it would leave nothing useful.
    assert normalize_model_name("Mini", "MINI COUPE") == "MINI COUPE"
    assert normalize_model_name("Mini", "MINI 3 PTAS") == "MINI 3 PTAS"


def test_normalize_never_returns_empty():
    assert normalize_model_name("Nissan", "Z") == "Z"
