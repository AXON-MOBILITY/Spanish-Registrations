"""
nif_lookup.py - Maestro de NIFs y municipios para clasificacion canal DGT
=========================================================================
Fuentes: infonif.es, datoscif.es, einforma.com, iberinform.es, INE DIRCE
Analisis multi-mes DGT vs Simmix 2025

LIMITACION: DGT publico NO incluye NIF comprador (anonimizado).
Este modulo sirve para:
  1. Documentar quien opera en cada municipio de campa.
  2. Uso directo si se obtiene acceso al fichero completo con NIF.
  3. Cross-reference municipio+marca para nuevas reglas.

METODOLOGIA SIMMIX (inferida):
  - NIF = importador/fabricante -> Corporate (campa pre-registro)
  - NIF = empresa CNAE 7711 (alquiler sin conductor) -> RAC
  - NIF = empresa CNAE 7712 (renting) -> Corporate "E|Renting"
  - NIF = persona fisica -> Private
"""

# -- IMPORTADORES Y FABRICANTES (A01 -> Corporate) ----------------------------
IMPORTADORES = {
    # Toyota
    "B80419922": {"empresa": "Toyota Espana SL",                    "marcas": ["TOYOTA","LEXUS"],  "municipio": "Alcobendas",  "cod_mun": "28006"},
    "B83551267": {"empresa": "Toyota Logistics Services Espana SL", "marcas": ["TOYOTA"],          "municipio": "Alcobendas",  "cod_mun": "28006"},
    # BMW Group
    "A28713642": {"empresa": "BMW Iberica SA",                       "marcas": ["BMW","MINI"],       "municipio": "Madrid",      "cod_mun": "28079"},
    # Mercedes-Benz
    "A79380465": {"empresa": "Mercedes-Benz Espana SA",              "marcas": ["MERCEDES-BENZ"],    "municipio": "Madrid",      "cod_mun": "28079"},
    # Volkswagen Group
    "A60198512": {"empresa": "Volkswagen Group Espana Distribucion SA", "marcas": ["VOLKSWAGEN","AUDI","SKODA","PORSCHE"], "municipio": "Barcelona", "cod_mun": "08019"},
    "B65154700": {"empresa": "Volkswagen Group Retail Spain SL",     "marcas": ["VOLKSWAGEN","AUDI","SKODA"], "municipio": "Madrid", "cod_mun": "28079"},
    # SEAT / CUPRA
    "A28049161": {"empresa": "SEAT SA",                              "marcas": ["SEAT","CUPRA"],     "municipio": "Martorell",   "cod_mun": "08108"},
    "A08924599": {"empresa": "SEAT Motor Espana SA",                 "marcas": ["SEAT","CUPRA"],     "municipio": "Barcelona",   "cod_mun": "08019"},
    # Stellantis
    "A28278026": {"empresa": "Stellantis & You Espana SA",           "marcas": ["PEUGEOT","CITROËN","CITROEN","DS","OPEL","ALFA ROMEO","JEEP","FIAT","LANCIA"], "municipio": "Madrid", "cod_mun": "28079"},
    "B50629187": {"empresa": "Stellantis Espana SL",                 "marcas": ["PEUGEOT","CITROEN","OPEL"], "municipio": "Vigo", "cod_mun": "36057"},
    # Renault Group
    "A47329180": {"empresa": "Renault Espana Comercial SA",          "marcas": ["RENAULT","DACIA"],  "municipio": "Alcobendas",  "cod_mun": "28006"},
    "A47000518": {"empresa": "Renault Espana SA",                    "marcas": ["RENAULT"],          "municipio": "Valladolid",  "cod_mun": "47186"},
    # Nissan
    "A60622743": {"empresa": "Nissan Iberia SA",                     "marcas": ["NISSAN"],           "municipio": "Barcelona",   "cod_mun": "08019"},
    "A08004871": {"empresa": "Nissan Motor Iberica SA",              "marcas": ["NISSAN"],           "municipio": "Barcelona",   "cod_mun": "08019"},
    # Ford
    "B46066361": {"empresa": "Ford Espana SL",                       "marcas": ["FORD"],             "municipio": "Almussafes",  "cod_mun": "46024"},
    # Hyundai / Kia
    "B85754646": {"empresa": "Hyundai Motor Espana SL",              "marcas": ["HYUNDAI"],          "municipio": "Alcobendas",  "cod_mun": "28006"},
    "B83497396": {"empresa": "Kia Iberia SL",                        "marcas": ["KIA"],              "municipio": "Alcobendas",  "cod_mun": "28006"},
    # Honda / Volvo
    "A58528522": {"empresa": "Honda Automoviles Espana SA",          "marcas": ["HONDA"],            "municipio": "Madrid",      "cod_mun": "28079"},
    "B28112142": {"empresa": "Volvo Car Espana SL",                  "marcas": ["VOLVO"],            "municipio": "Madrid",      "cod_mun": "28079"},
}

# -- EMPRESAS DE ALQUILER (A01 -> RAC) ----------------------------------------
ALQUILER = {
    "A28364412": {"empresa": "Europcar IB SA",                        "municipio": "Madrid",                      "cod_mun": "28079"},
    "B28121549": {"empresa": "Hertz de Espana SL",                    "municipio": "Las Rozas de Madrid",         "cod_mun": "28089"},
    "A28152767": {"empresa": "Avis Alquile Un Coche SA",              "municipio": "Madrid",                      "cod_mun": "28079"},
    "B03965506": {"empresa": "Centauro Rent-a-car SL",                "municipio": "Finestrat",                   "cod_mun": "03064"},
    "B03403169": {"empresa": "Goldcar Spain SL",                      "municipio": "Sant Joan d'Alacant",         "cod_mun": "03118"},
    "B57653321": {"empresa": "OK GROUP",                              "municipio": "Palma de Mallorca",           "cod_mun": "07040"},
    "B07659725": {"empresa": "Global Rent A Car SL",                  "municipio": "Calvia",                      "cod_mun": "07018"},
    "B07947591": {"empresa": "Sixt Rent A Car SL",                    "municipio": "Palma de Mallorca",           "cod_mun": "07040"},
    "A28047884": {"empresa": "Atesa (Autotransporte Turistico Espanol SA)", "municipio": "Madrid",                "cod_mun": "28051"},
    "B07882574": {"empresa": "Enterprise Rent A Car SL",              "municipio": "Palma de Mallorca",           "cod_mun": "07040"},
    "A12584470": {"empresa": "Record Go Alquiler Vacacional SA",      "municipio": "Castellon",                   "cod_mun": "12040"},
    "B13930375": {"empresa": "Record Go Canarias SL",                 "municipio": "Las Palmas de Gran Canaria",  "cod_mun": "35016"},
    "B35051820": {"empresa": "Canary Islands Car SL (CICAR)",         "municipio": "San Bartolome de Tirajana",   "cod_mun": "35004"},
}

# -- RENTING LARGO PLAZO (B00+empresa+RENTING_S -> Corporate "E|Renting") -----
RENTING = {
    "A80185051": {"empresa": "Volkswagen Renting SA", "municipio": "Madrid", "notas": "VW Group renting LP"},
}

# -- MUNICIPIOS DE CAMPA (A01 -> Corporate) ------------------------------------
CAMPA_MUNICIPIOS = {
    "28093": {
        "municipio": "Navacerrada",
        "tipo": "campa_fabricante",
        "marcas_confirmadas": ["SKODA"],
        "evidencia": "136 SKODA RS ene-2025 = Simmix Corp exacto. VW Group campa.",
        "empresas_ine": 281,
    },
    "28169": {
        "municipio": "Venturada",
        "tipo": "campa_fabricante",
        "marcas_confirmadas": ["TOYOTA", "LEXUS", "MERCEDES-BENZ"],
        "evidencia": "Toyota(33)/Lexus(14)/MB(10) ene-2025 = Simmix Corp.",
        "empresas_ine": 268,
    },
    "28022": {
        "municipio": "Boadilla del Monte",
        "tipo": "campa_fabricante",
        "marcas_confirmadas": ["OPEL","PEUGEOT","CITROEN","CITROËN","DS","ALFA ROMEO","RENAULT","JEEP"],
        "evidencia": "OPEL 248 ene=Corp Simmix. JEEP avg +24/mes RS=total Simmix RAC=0.",
        "empresas_ine": 6811,
    },
    "38038": {
        "municipio": "Santa Cruz de Tenerife",
        "tipo": "campa_fabricante",
        "marcas_confirmadas": ["PEUGEOT"],
        "evidencia": "PEUGEOT RS=31=Corp Simmix exacto.",
    },
    "35025": {
        "municipio": "Tejeda",
        "tipo": "campa_fabricante",
        "marcas_confirmadas": ["PEUGEOT"],
        "evidencia": "PEUGEOT RS=24=Corp Simmix exacto.",
    },
}

# -- MUNICIPIOS DEPOSITO ALQUILER (A01 -> RAC) ---------------------------------
DEPOT_ALQUILER = {
    "28069": {"municipio": "La Hiruela",       "empresas_ine": 9,
              "evidencia": "9 empresas INE. DGT RAC total = Simmix RAC total por marca."},
    "28125": {"municipio": "Robledo de Chavela","empresas_ine": 349,
              "evidencia": "PEUGEOT RS=300 = Simmix RAC=300 exacto."},
    "28090": {"municipio": "Moralzarzal",       "empresas_ine": 976,
              "evidencia": "PEUGEOT RS=205 = Simmix RAC=205 exacto."},
}


def clasificar_nif(nif: str) -> dict:
    """Dado NIF/CIF retorna tipo y canal sugerido."""
    nif = nif.strip().upper()
    if nif in IMPORTADORES:
        return {"tipo": "importador", "canal": "Corporate", **IMPORTADORES[nif]}
    if nif in ALQUILER:
        return {"tipo": "alquiler", "canal": "RAC", **ALQUILER[nif]}
    if nif in RENTING:
        return {"tipo": "renting", "canal": "Corporate", "subcanal": "E | Renting", **RENTING[nif]}
    return {"tipo": "desconocido", "canal": "ambiguo"}


def clasificar_municipio_a01(cod_municipio: str, marca: str = "") -> str | None:
    """Dado codigo INE (5 dig) sugiere canal para A01. Retorna 'Corporate', 'RAC' o None."""
    mun = (cod_municipio or "")[:5]
    if mun in CAMPA_MUNICIPIOS:
        marcas_conf = CAMPA_MUNICIPIOS[mun].get("marcas_confirmadas", [])
        if not marcas_conf or marca.upper() in [m.upper() for m in marcas_conf]:
            return "Corporate"
    if mun in DEPOT_ALQUILER:
        return "RAC"
    return None


if __name__ == "__main__":
    print("=== TEST nif_lookup.py ===")
    for nif in ["B80419922", "A28364412", "B07947591", "B35051820", "A28047884", "A80185051", "B99999999"]:
        r = clasificar_nif(nif)
        print(f"  {nif}: {r['tipo']}/{r['canal']} - {r.get('empresa','?')}")

    print("\n=== TEST municipios A01 ===")
    for mun, marca in [("28093","SKODA"),("28169","TOYOTA"),("28069","SUZUKI"),("28125","PEUGEOT"),("28006","TOYOTA")]:
        print(f"  mun={mun} marca={marca}: {clasificar_municipio_a01(mun, marca)}")
