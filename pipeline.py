"""
pipeline.py — DGT Matriculaciones Parser + Enrichment
Replica los 29 campos del formato Simmix (BBDD_AAAA_PRODUCTO)
a partir de microdatos DGT (formato fijo 714 chars/línea).

Uso:
    python pipeline.py --file export_mensual_mat_202501.txt --out output_202501.csv
    python pipeline.py --year 2025 --month 1 --out output_202501.csv  # descarga auto
"""

import argparse
import csv
import io
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

# ── Rutas master (relativas al script) ──────────────────────────────────────
BASE = Path(__file__).parent
MASTER_EEA_L1      = BASE / "master_version_lookup_l1.csv"
MASTER_EEA_L2      = BASE / "master_version_lookup_l2.csv"
MASTER_IDAE        = BASE / "master_idae_versiones_wltp.csv"
MASTER_SEGMENTO    = BASE / "master_segmentacion_bmw.csv"
MASTER_CONCESIN    = BASE / "master_concesin_bmw_v2.csv"

# ── Posiciones campo (inicio, fin) — validadas contra export_mensual_mat_202501 ─
FIELDS = {
    "FEC_MATRICULA":               (0,   8),   # DDMMYYYY
    "MARCA_ITV":                   (17,  47),  # 30 chars
    "MODELO_ITV":                  (47,  69),  # 22 chars
    "VIN":                         (69,  91),  # 22 chars (parcialmente enmascarado)
    "COD_TIPO_VEHICULO":           (91,  93),  # tipo vehículo
    "COD_PROPULSION_ITV":          (93,  94),  # 0=gas, 1=diesel, 2=elec, 6=GLP, 7=GNC
    "CILINDRADA_ITV":              (94,  99),  # cc
    "KW_ITV":                      (227, 234), # potencia kW (float, ej: "145.00")
    "SERVICIO":                    (189, 192), # uso: B00=particular, A01=alquiler, A18=empresa
    "COD_MUNICIPIO_INE":           (192, 197), # 5 dígitos INE (PP+MMM), PP=provincia
    "MUNICIPIO":                   (197, 227), # nombre municipio 30 chars (PDF oficial DGT)
    "RENTING":                     (242, 243), # S=vehículo de renting, N/blank=no renting
    "VARIANTE_ITV":                (284, 309), # código variante homologación EU (25 chars)
    "VERSION_ITV":                 (309, 344), # código versión homologación EU (35 chars)
    "CATEGORIA_HOMOLOGACION_ITV":  (426, 430), # M1, N1, M1G, M1*, N1G...
    "CATEGORIA_VEHICULO_ELECTRICO":(453, 457), # BEV, HEV, PHEV, REEV o vacío
    # Campos derivados de la línea cruda (también en parse_line)
    # [178:179] = IND_NUEVO_USADO: N=nuevo, U=usado → filtro principal (excluir U)
    # [179:180] = PERSONA_FISICA_JURIDICA: D=persona física, X=empresa/jurídica
    # Combinados como TITULAR_TIPO: ND=nuevo+físico, NX=nuevo+empresa, UD=usado+físico, UX=usado+empresa
}

# ── Tablas de referencia estáticas ──────────────────────────────────────────

# Provincias INE código → nombre
PROV_INE = {
    "01":"ALAVA","02":"ALBACETE","03":"ALICANTE","04":"ALMERIA","05":"AVILA",
    "06":"BADAJOZ","07":"ISLAS BALEARES","08":"BARCELONA","09":"BURGOS",
    "10":"CACERES","11":"CADIZ","12":"CASTELLON","13":"CIUDAD REAL","14":"CORDOBA",
    "15":"A CORUNA","16":"CUENCA","17":"GIRONA","18":"GRANADA","19":"GUADALAJARA",
    "20":"GUIPUZCOA","21":"HUELVA","22":"HUESCA","23":"JAEN","24":"LEON",
    "25":"LLEIDA","26":"LA RIOJA","27":"LUGO","28":"MADRID","29":"MALAGA",
    "30":"MURCIA","31":"NAVARRA","32":"OURENSE","33":"ASTURIAS","34":"PALENCIA",
    "35":"LAS PALMAS","36":"PONTEVEDRA","37":"SALAMANCA","38":"SANTA CRUZ DE TENERIFE",
    "39":"CANTABRIA","40":"SEGOVIA","41":"SEVILLA","42":"SORIA","43":"TARRAGONA",
    "44":"TERUEL","45":"TOLEDO","46":"VALENCIA","47":"VALLADOLID","48":"VIZCAYA",
    "49":"ZAMORA","50":"ZARAGOZA","51":"CEUTA","52":"MELILLA",
}

# Zona BMW (11-23) por provincia
ZONA_POR_PROVINCIA = {
    "MADRID":"11-Centro-Extremadura","TOLEDO":"11-Centro-Extremadura",
    "CUENCA":"11-Centro-Extremadura","GUADALAJARA":"11-Centro-Extremadura",
    "SEGOVIA":"11-Centro-Extremadura","AVILA":"11-Centro-Extremadura",
    "SALAMANCA":"11-Centro-Extremadura","ZAMORA":"11-Centro-Extremadura",
    "VALLADOLID":"11-Centro-Extremadura","PALENCIA":"11-Centro-Extremadura",
    "BURGOS":"11-Centro-Extremadura","SORIA":"11-Centro-Extremadura",
    "LA RIOJA":"11-Centro-Extremadura","LEON":"11-Centro-Extremadura",
    "BADAJOZ":"11-Centro-Extremadura","CACERES":"11-Centro-Extremadura",
    "A CORUNA":"12-Noroeste","LUGO":"12-Noroeste","OURENSE":"12-Noroeste",
    "PONTEVEDRA":"12-Noroeste","ASTURIAS":"12-Noroeste","CANTABRIA":"12-Noroeste",
    "HUESCA":"13-Norte-Canarias","ZARAGOZA":"13-Norte-Canarias",
    "SORIA":"13-Norte-Canarias","SANTA CRUZ DE TENERIFE":"13-Norte-Canarias",
    "NAVARRA":"13-Norte-Canarias","LAS PALMAS":"13-Norte-Canarias",
    "VIZCAYA":"13-Norte-Canarias","GUIPUZCOA":"13-Norte-Canarias",
    "TERUEL":"13-Norte-Canarias","ALAVA":"13-Norte-Canarias",
    "BARCELONA":"21-Cataluna-Baleares","GIRONA":"21-Cataluna-Baleares",
    "TARRAGONA":"21-Cataluna-Baleares","LLEIDA":"21-Cataluna-Baleares",
    "ISLAS BALEARES":"21-Cataluna-Baleares",
    "ALICANTE":"22-Levante","CUENCA":"22-Levante","ALBACETE":"22-Levante",
    "CIUDAD REAL":"22-Levante","MURCIA":"22-Levante","VALENCIA":"22-Levante",
    "CASTELLON":"22-Levante",
    "MALAGA":"23-Andalucia","GRANADA":"23-Andalucia","JAEN":"23-Andalucia",
    "CORDOBA":"23-Andalucia","CADIZ":"23-Andalucia","SEVILLA":"23-Andalucia",
    "ALMERIA":"23-Andalucia","HUELVA":"23-Andalucia","CEUTA":"23-Andalucia",
    "MELILLA":"23-Andalucia",
}

# Meses en inglés
MESES_EN = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
            7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

# Canal / SubCanal: lógica combinada SERVICIO × TITULAR_TIPO
# TITULAR_TIPO: ND=persona física, NX=persona jurídica/empresa
# Derivado del campo [178:180] del fichero DGT

# ── Lookup de campas de fabricante → Corporate ──────────────────────────────
# Simmix clasifica A01 como Corporate cuando el NIF registrante es el propio
# fabricante/importador almacenando coches en una campa (no un alquilador real).
# Sin NIF en DGT (GDPR), identificamos campas por:
#   1. MARCA+RENTING='S': fabricantes que marcan RENTING='S' en sus campas
#   2. MUNICIPIO: municipios pequeños con concentración anómala = campa probada
#
# Validación estadística enero-2025:
#   SKODA+RENTING='S' → Corporate: 136 = delta Simmix exacto ✓
#   BOADILLA (28022) all A01 → Corporate: ~336 (PSA, Toyota, Renault campa) ✓
#   VENTURADA (28169) all A01 → Corporate: ~96 (Toyota, Lexus, MB campa) ✓

# Municipios de campa para SKODA (Navacerrada = VW Group Spain campus)
# CLAVE: la regla es por MUNICIPIO, no por RENTING='S'
# Análisis multi-mes mostró que SKODA+RENTING_S aparece en ALCOBENDAS (28006) en feb/mar/oct
# = empresas de renting reales comprando SKODA (esas deben ser RAC).
# Solo Navacerrada (28093) es la campa de fabricante → Corporate.
#   Jan: 136 en 28093 → Simmix Skoda RAC=445=DGT_RN ✓ (validado)
#   Feb: 289 en 28006 (Alcobendas) → Simmix Skoda RAC=1,041 (regla RENTING_S era incorrecta)
CAMPA_SKODA_MUNS = {'28093'}  # Navacerrada (Madrid)

# Municipios de campa (toda marca): municipio <5k hab, >100 A01/mes = imposible alquiler real
# Venturada (~1.000 hab): Toyota/Lexus/MB campa confirmado (Toyota delta ≈ +35, Venturada Toyota=33)
# NOTA: análisis multi-mes muestra picos estacionales (665 en feb vs 96 en ene) pero son
# consistentemente RENTING='S' para Toyota/Lexus/MB → mantener regla todo-marca por ahora.
CAMPA_MUNICIPIOS_TODOS = {
    '28169',  # Venturada (Madrid, ~1.000 hab): Toyota España / Lexus / MB campa
}

# Municipios de campa (marcas confirmadas): Boadilla del Monte = polígono industrial
# con múltiples fabricantes/importadores (Stellantis + Renault + Jeep)
CAMPA_MUNICIPIOS_PSA  = {'28022'}   # Boadilla del Monte
CAMPA_PSA_MARCAS = {'OPEL', 'PEUGEOT', 'CITROËN', 'CITROEN', 'DS', 'ALFA ROMEO', 'RENAULT', 'JEEP'}
#   OPEL:     248 → Corporate ✓ (Stellantis España)
#   RENAULT:   16 → Corporate ✓ (0 RAC en Simmix para Boadilla Renault)
#   JEEP:       9 → Corporate ✓ (análisis multi-mes: avg +24/mes, RS=total, Simmix RAC=0 en Boadilla)
#   PEUGEOT:    3 → Corporate (pequeño, Simmix muestra 7 RAC = scope diff)
#   CITROËN:    8 → Corporate (Simmix muestra 8 RAC → posible over-classify, pero <10)

# Municipios donde PEUGEOT+RENTING='S' = registro de fabricante/importador, NO alquiler real
# Validado por comparación directa DGT×municipio vs Simmix×municipio:
#   38038 (SC Tenerife): DGT=73(RS=31,N=42), Simmix RAC=42(=N), Simmix Corp=31(=RS) → RS=Corporate ✓
#   35025 (Tejeda GC):   DGT=49(RS=24,N=25), Simmix RAC=25(=N), Simmix Corp=24(=RS) → RS=Corporate ✓
# EXCLUIDO Robledo (28125): DGT RS=300, Simmix RAC=300 → todos RAC (gran depot alquiler)
# EXCLUIDO Moralzarzal (28090): DGT RS=205, Simmix RAC=205 → todos RAC (idem)
CAMPA_PEUGEOT_RS_MUNS = {'38038', '35025'}

# ── Municipios concesionario por marca (Km.0) → Corporate ───────────────────
# Simmix clasifica B00+D como Corporate cuando el CP de matriculación coincide
# con el CP de un concesionario (Km.0 / automatriculaciones / excedentes).
# Sin CP en DGT usamos el código INE de municipio (PPMMM) como proxy.
# Sincronizado con process_month.py.
_DEALER_MUN_BY_BRAND = {
    'BMW':          {'28151','28128','30040','17093','07019','46092','28173','28090','43034','28036','03111','03112','28069','29083','03119','45203','28093','11008','28002','03030','43043','48902','15058','24142','08178','20063','31088','36024','39016','46102'},
    'VOLVO':        {'28151','28128','20040','50224','45021','37362','28002','31088','08178','48902','15058','24142','08073'},
    'ALFA ROMEO':   {'08002','28069','28125'},
    'AUDI':         {'03119','08002','08027','12103','15058','24142','25007','28002','28125','28128','28151','37362','43059','45122','46102'},
    'CITROEN':      {'03030','03071','03112','07038','08002','08027','08178','12103','25007','28002','28027','28069','28090','28107','28125','28128','28151','29066','29074','43043','45021','45045'},
    'CITROËN':      {'03030','03071','03112','07038','08002','08027','08178','12103','25007','28002','28027','28069','28090','28107','28125','28128','28151','29066','29074','43043','45021','45045'},
    'CUPRA':        {'08002','13029','25007','28002','28036','28046','28121','28151','29074','48036'},
    'DACIA':        {'03030','12103','28090','28107'},
    'DS':           {'28069','28125','45021'},
    'FIAT':         {'03030','08002','08178','12103','28027','28069','28090','28107','28128','28151','28153','29066','29074','35018','41083','45021'},
    'FORD':         {'03030','03119','08002','08178','28046','28069','28090','28107','28125','28128','29066','29074','43059'},
    'HONDA':        {'08002','08178','29074'},
    'HYUNDAI':      {'03030','04052','08178','09434','24142','27049','28093','28107','28125','28128','28151','28173','29066','31109','43059','43163','45122','48902','50224'},
    'IVECO':        {'28125','28151','29074','46102'},
    'JEEP':         {'03030','08178','12103','28069','28125','28151','28153','29074','41083','45021'},
    'KIA':          {'08002','08178','20063','28090','28125','46092','48902'},
    'LEXUS':        {'29074'},
    'MAZDA':        {'08002','08178','25007','28002','28069','28090','28125'},
    'MERCEDES':     {'11003','12103','15058','20058','25007','26084','27049','28069','28090','28093','28099','28151','41083','46092'},
    'MERCEDES-BENZ':{'11003','12103','15058','20058','25007','26084','27049','28069','28090','28093','28099','28151','41083','46092'},
    'MG':           {'03030','08002','28002','28069','46092'},
    'MINI':         {'07019','28026','28128','30040'},
    'MITSUBISHI':   {'45021'},
    'NISSAN':       {'03030','08002','08178','28046','28090','28107','28128','29074','29083'},
    'OPEL':         {'03030','03112','08002','08178','12103','20058','28002','28069','28128','28151','29066','29074','43043','45021'},
    'PEUGEOT':      {'03030','03112','08002','08027','08178','12103','15058','20063','28090','28125','28151','41083','43043','45021'},
    'RENAULT':      {'03030','07019','08178','28107','28128','29074','45021'},
    'SEAT':         {'04052','12103','13029','28002','28046','28107','29074','35018','45122'},
    'SSANGYONG':    {'45021'},
    'SUBARU':       {'45021'},
    'SUZUKI':       {'08178'},
    'TOYOTA':       {'12103','20058','28090','28107','28125','28128','29074','50224'},
    'VOLKSWAGEN':   {'08002','08106','12103','24148','28151','29074','30031','31193'},
}
# Set universal para marcas no listadas (municipios de alta señal multi-marca)
_DEALER_MUN_ALL = {
    '03030','03111','03112','07019','08002','08027','08178','09434','11003',
    '11008','12103','13029','17093','20058','20063','24148','25007','27049',
    '28002','28027','28036','28046','28069','28090','28093','28099','28107',
    '28121','28125','28128','28151','28153','28173','29066','29074','29083',
    '30031','30040','31088','31193','35018','37362','41083','43034','43043',
    '43059','45021','45122','45203','46092','48036','49227','50224',
}
_DEALER_MUN_ALL_EXCL = {'SKODA'}  # SKODA sobreclasifica → excluido de la regla universal

  # SC Tenerife + Tejeda (Gran Canaria)


def derive_canal(servicio, persona_fj, renting='', mun_code='', marca_upper=''):
    """
    Derivar Canal y SubCanal según SERVICIO DGT × PERSONA_FISICA_JURIDICA × RENTING.

    Parámetros:
      servicio    -- código SERVICIO [189:192] (B00, A01, A18…)
      persona_fj  -- PERSONA_FISICA_JURIDICA [179:180]: D=física, X=empresa
      renting     -- campo RENTING [242:243]: S=renting, N/blank=no renting
      mun_code    -- COD_MUNICIPIO_INE [192:197]: para detección de campas
      marca_upper -- MARCA_ITV normalizada en mayúsculas

    Canales de salida (replica Simmix):
      Private   · B00+D, B17, B19, B21, A04, A07, A03
      RAC       · A01 alquiler genuino (sin conductor)
      Corporate · A01-campa-fabricante, B00+X, B18, A18, A05
    SubCanales:
      E | Renting         · B00+X con RENTING='S' (renting largo plazo)
      E | Empresas Detall · B00+X sin renting, B18/A18
      R | Rac Operativo   · A01 genuino alquiler (RAC)
    """
    s   = servicio  or ""
    pfj = persona_fj or "D"
    rent = (renting or "").strip()
    mun  = (mun_code or "")[:5]
    marc = (marca_upper or "").upper()
    is_empresa = (pfj == "X")

    if s == "A01":
        # ── Detección de campas de fabricante → Corporate ──────────────────
        # Regla 1: SKODA en Navacerrada (28093) = VW Group campa
        #   Validado: 136 registros en 28093 = Simmix Corp exacto; A01_N=445 = Simmix RAC Skoda ✓
        #   OJO: SKODA+RENTING='S' en Alcobendas (28006) = empresas renting reales → deben ser RAC
        if marc == 'SKODA' and mun in CAMPA_SKODA_MUNS:
            return "Corporate", "E | Empresas Detall"

        # Regla 2: Venturada (28169) = campa multi-marca (Toyota/Lexus/MB España)
        #   ~1.000 hab → imposible ser alquilador real; RENTING='S' dominante (57-92% según mes)
        if mun in CAMPA_MUNICIPIOS_TODOS:
            return "Corporate", "E | Empresas Detall"

        # Regla 3: Boadilla del Monte (28022) = polígono industrial con fabricantes/importadores
        #   Incluye JEEP (Stellantis): avg +24/mes, RS=total, Simmix RAC=0 en Boadilla → confirmado
        if mun in CAMPA_MUNICIPIOS_PSA and marc in CAMPA_PSA_MARCAS:
            return "Corporate", "E | Empresas Detall"

        # Regla 4: PEUGEOT+RENTING='S' en municipios con NIF fabricante confirmado
        #   Validado: en 38038 y 35025, RS≡Corporate y N≡RAC en Simmix (match exacto)
        #   Distinción clave vs Robledo/Moralzarzal donde RS=RAC (depots de alquiler masivos)
        if marc == 'PEUGEOT' and rent == 'S' and mun in CAMPA_PEUGEOT_RS_MUNS:
            return "Corporate", "E | Empresas Detall"

        # Resto de A01: alquiler sin conductor genuino → RAC
        return "RAC", "R | Rac Operativo"

    if s in ("A04", "A07"):
        return "Private", "P | Particular Uso Publico"

    if s == "A03":
        return "Private", "P | Empleados"

    if s in ("B17", "B19", "B21"):
        return "Private", "P | Particular Uso Privado"

    if s in ("B18", "A18", "A05"):
        return "Corporate", "E | Empresas Detall"

    if s == "B00":
        if is_empresa:
            # Campo RENTING distingue E|Renting de E|Empresas Detall
            if rent == 'S':
                return "Corporate", "E | Renting"
            return "Corporate", "E | Empresas Detall"
        else:
            # B00+D (persona física): puede ser Km.0 si el municipio es un concesionario.
            # Simmix clasifica como Corporate los B00+D cuyo CP coincide con el del dealer.
            brand_set = _DEALER_MUN_BY_BRAND.get(marc)
            if brand_set and mun in brand_set:
                return "Corporate", "E | Km.0"
            if marc not in _DEALER_MUN_ALL_EXCL and mun in _DEALER_MUN_ALL:
                return "Corporate", "E | Km.0"
            return "Private", "P | Particular Uso Privado"

    # Fallback
    if is_empresa:
        return "Corporate", "E | Empresas Detall"
    return "Private", "P | Particular Uso Privado"

# Marcas origen chino (Nation = CN)
MARCAS_CN = {
    "MG","BYD","OMODA","EBRO","JAECOO","LYNK & CO","LEAPMOTOR","MAXUS","EVO",
    "DFSK","SHINERAY","XPENG","SMART","LIVAN","FOTON","FAW","DONGFENG","SERES",
    "BESTUNE","BAIC","FARIZON","YUDO","VOYAH","DENZA","SKYWELL","ZEROID","ICH-X",
    "FIREFLY","AVATR","AIWAYS","DEEPAL","AION","CHERY","GEELY","GAC",
}

# High Performance – marcas y patrones
HP_PURE_BRANDS = {"FERRARI","LAMBORGHINI","MCLAREN","ROLLS-ROYCE","BUGATTI","KOENIGSEGG"}
HP_M_PATTERNS  = re.compile(r'\b(M2|M3|M4|M5|M6|M8|XM)\b')
HP_MP_PATTERNS = re.compile(r'\b(M PERFORMANCE|M SPORT|COMPETITION|M-SPORT)\b|AMG\b|QUATTRO\s*S\b|RS\s*\d|ABARTH|JCW|JOHN COOPER WORKS')
HP_JCW_PATTERNS= re.compile(r'\bJCW\b|JOHN COOPER WORKS\b')

# Homologación DGT → Simmix
def homologacion(cat):
    cat = (cat or "").strip().upper()
    if cat.startswith("M"):
        return cat, "Turismo"
    elif cat.startswith("N"):
        return cat, "Comercial"
    return cat, "Otro"

# Fuel / Fuel_Type
def fuel_type(propulsion, cat_electrico, variante_itv, version_itv):
    prop = (propulsion or "").strip()
    electrico = (cat_electrico or "").strip().upper()
    texto = f"{variante_itv or ''} {version_itv or ''}".upper()

    if electrico == "BEV" or prop == "2":
        return "Electrico", "BEV"
    if electrico == "PHEV":
        fuel_base = "Gasolina" if prop in ("0","") else "Diesel"
        return f"{fuel_base}/Electrico Enchufable", "PHEV"
    if electrico == "REEV":
        return "Electrico", "BEV"
    if electrico == "HEV":
        fuel_base = "Gasolina" if prop in ("0","") else "Diesel"
        return f"{fuel_base}/Electrico", "ICE"
    if prop == "0":
        if any(kw in texto for kw in ("MHEV","48V","MILD HYBRID","MICROHYBRID")):
            return "Gasolina Mild Hybrid", "ICE"
        return "Gasolina", "ICE"
    if prop == "1":
        if any(kw in texto for kw in ("MHEV","48V","MILD HYBRID","MICROHYBRID")):
            return "Diesel Mild Hybrid", "ICE"
        return "Diesel", "ICE"
    if prop == "6":
        return "Gas Licuado con petroleo (GLP)", "ICE"
    if prop == "7":
        return "Gas natural comprimido (GNC)", "ICE"
    return "Gasolina", "ICE"

def high_performance(marca, version):
    m = marca.upper()
    v = (version or "").upper()
    if m in HP_PURE_BRANDS:
        return "M"
    if m == "BMW" and HP_M_PATTERNS.search(v):
        return "M"
    if m == "MINI" and HP_JCW_PATTERNS.search(v):
        return "JCW"
    if HP_MP_PATTERNS.search(v):
        return "M Performance"
    return "Standard"


# ── Carga de maestros ────────────────────────────────────────────────────────

def load_masters():
    print("Cargando maestros...", flush=True)

    # L1: EEA Va+Ve → nombre modelo
    eea_l1 = {}
    if MASTER_EEA_L1.exists():
        df = pd.read_csv(MASTER_EEA_L1, dtype=str).fillna("")
        for _, r in df.iterrows():
            eea_l1[(r["Mk"].strip(), r["Va"].strip(), r["Ve"].strip())] = r["Cn"].strip()

    # L2: EEA Va dominante → nombre modelo (fallback)
    eea_l2 = {}
    if MASTER_EEA_L2.exists():
        df = pd.read_csv(MASTER_EEA_L2, dtype=str).fillna("")
        for _, r in df.iterrows():
            eea_l2[(r["Mk"].strip(), r["Va"].strip())] = r["Cn_va"].strip()

    # L3/L4: IDAE → versión completa indexada por (marca_norm, variante_upper)
    idae_va = {}    # clave: variante_code → nombre_idae
    idae_kw = {}    # clave: (marca_norm, modelo_norm, kw_round) → [nombre_idae, ...]
    if MASTER_IDAE.exists():
        df_idae = pd.read_csv(MASTER_IDAE, dtype=str).fillna("")
        for _, r in df_idae.iterrows():
            nombre = r["nombre_idae"].strip()
            # Extraer código variante al final (no MY+año)
            m = re.search(r'\s([A-Z0-9]{4,8})\s*$', nombre)
            if m:
                code = m.group(1)
                if not re.match(r'^MY\d{2}$', code) and not re.match(r'^(DSG\d?|SG\d|CVT|DCT)$', code):
                    idae_va[code] = nombre
            # Index kW
            kw_m = re.search(r'(\d+(?:\.\d+)?)\s*[kK][wW]', nombre)
            if kw_m:
                kw_val = round(float(kw_m.group(1)))
            else:
                cv_m = re.search(r'(\d+)\s*[cC][vV]', nombre)
                kw_val = round(float(cv_m.group(1)) / 1.3596) if cv_m else None
            if kw_val:
                marca_n = nombre.split()[0].upper()
                modelo_n = nombre.split()[1].upper() if len(nombre.split()) > 1 else ""
                key = (marca_n, modelo_n, kw_val)
                idae_kw.setdefault(key, []).append(nombre)

    # Segmentación BMW Group
    seg_map = {}  # (brand_upper, model_upper) → {Zona, Segmento, Concepto, Clasif}
    if MASTER_SEGMENTO.exists():
        df_seg = pd.read_csv(MASTER_SEGMENTO, dtype=str).fillna("")
        for _, r in df_seg.iterrows():
            key = (r["BRAND"].strip().upper(), r["SUB_MODEL_SHORT"].strip().upper())
            seg_map[key] = {
                "BMW_SEGMENT": r.get("BMW_SEGMENT","").strip(),
                "BMW_CONCEPT": r.get("BMW_CONCEPT","").strip(),
                "BMW_CLASSIFICATION": r.get("BMW_CLASSIFICATION","").strip(),
            }

    # Concesionarios BMW
    concesin_map = {}  # (provincia_upper, municipio_upper) → {Zona, Id, Concesin, Grupo}
    if MASTER_CONCESIN.exists():
        df_con = pd.read_csv(MASTER_CONCESIN, dtype=str).fillna("")
        for _, r in df_con.iterrows():
            key = (r["Provincia"].strip().upper(), r["Municipio"].strip().upper())
            concesin_map[key] = {
                "Zona_D":    r.get("Zona","").strip(),
                "Id_Con":    r.get("Id_Concesin","").strip(),
                "Concesin":  r.get("Concesin","").strip(),
                "Grupo":     r.get("Grupo","").strip(),
            }

    print(f"  L1 EEA: {len(eea_l1):,} | L2 EEA: {len(eea_l2):,} | IDAE-Va: {len(idae_va):,} | IDAE-kW keys: {len(idae_kw):,}")
    print(f"  Segmentación: {len(seg_map):,} | Concesionarios: {len(concesin_map):,}")
    return eea_l1, eea_l2, idae_va, idae_kw, seg_map, concesin_map


# ── Normalización de marcas ──────────────────────────────────────────────────

MARCA_ALIAS = {
    "MERCEDES": "MERCEDES-BENZ",
    "MERCEDES BENZ": "MERCEDES-BENZ",
    "VW": "VOLKSWAGEN",
    "CITROEN": "CITROËN",
    "CITROËN": "CITROËN",
    "ALFA": "ALFA ROMEO",
    "LAND ROVER": "LAND ROVER",
    "ROLLS ROYCE": "ROLLS-ROYCE",
}

def norm_marca(marca):
    m = marca.strip().upper()
    return MARCA_ALIAS.get(m, m)

def title_marca(marca):
    """BMW Group segmentation usa Title Case para algunas marcas."""
    aliases_tc = {
        "VOLKSWAGEN": "Volkswagen", "TOYOTA": "Toyota", "HYUNDAI": "Hyundai",
        "KIA": "Kia", "RENAULT": "Renault", "PEUGEOT": "Peugeot",
        "CITROËN": "Citroën", "SKODA": "Skoda", "DACIA": "Dacia",
        "FORD": "Ford", "FIAT": "Fiat", "HONDA": "Honda", "MAZDA": "Mazda",
        "NISSAN": "Nissan", "VOLVO": "Volvo", "AUDI": "Audi",
        "MERCEDES-BENZ": "Mercedes-Benz",
    }
    return aliases_tc.get(marca.upper(), marca)

# Marcas que se mantienen en MAYÚSCULAS en los outputs
_UPPER_BRANDS = {"BMW","MINI","BYD","MG","KIA","VW","JMB","CUPRA","GWM","FAW","GAC","BAIC"}

def fmt_brand(marca):
    """Formatea marca para mostrar: mayúsculas para acrónimos, title case para el resto."""
    m = marca.upper()
    if m in _UPPER_BRANDS:
        return m
    # Title case con respeto a guiones
    return "-".join(w.capitalize() for w in marca.replace("_"," ").split("-"))


# ── Parser de una línea DGT ──────────────────────────────────────────────────

def parse_line(line):
    if len(line) < 460:
        return None
    f = FIELDS
    def get(key):
        s, e = f[key]
        return line[s:e].strip()

    # [178:179] = IND_NUEVO_USADO: N=nuevo (incluir), U=usado (excluir)
    # [179:180] = PERSONA_FISICA_JURIDICA: D=persona física, X=empresa/jurídica
    ind_nuevo  = line[178:179] if len(line) > 179 else "?"
    persona_fj = line[179:180] if len(line) > 180 else "D"

    return {
        "FEC_MATRICULA":               get("FEC_MATRICULA"),
        "MARCA_ITV":                   get("MARCA_ITV"),
        "MODELO_ITV":                  get("MODELO_ITV"),
        "COD_TIPO_VEHICULO":           get("COD_TIPO_VEHICULO"),
        "COD_PROPULSION_ITV":          get("COD_PROPULSION_ITV"),
        "CILINDRADA_ITV":              get("CILINDRADA_ITV"),
        "KW_ITV":                      get("KW_ITV"),
        "SERVICIO":                    get("SERVICIO"),
        "COD_MUNICIPIO_INE":           get("COD_MUNICIPIO_INE"),
        "MUNICIPIO_RAW":               get("MUNICIPIO"),
        "RENTING":                     get("RENTING"),
        "VARIANTE_ITV":                get("VARIANTE_ITV"),
        "VERSION_ITV":                 get("VERSION_ITV"),
        "CATEGORIA_HOMOLOGACION_ITV":  get("CATEGORIA_HOMOLOGACION_ITV"),
        "CATEGORIA_VEHICULO_ELECTRICO":get("CATEGORIA_VEHICULO_ELECTRICO"),
        "IND_NUEVO_USADO":             ind_nuevo,   # N=nuevo, U=usado
        "PERSONA_FJ":                  persona_fj,  # D=física, X=empresa
    }


def is_passenger_or_lcv(cat):
    """
    Incluye M1/M1G (Turismo) y N1/N1G (Comercial ligero).
    Replica el filtro de Simmix: ambas categorías, excluye M2/M3/N2/N3/L/O/T.
    """
    c = (cat or "").strip().upper()
    return c.startswith("M1") or c.startswith("N1")

# Alias para compatibilidad
is_turismo = is_passenger_or_lcv


# ── Enriquecimiento de un registro ──────────────────────────────────────────

def enrich(rec, eea_l1, eea_l2, idae_va, idae_kw, seg_map, concesin_map):
    marca_raw  = rec["MARCA_ITV"]
    modelo_raw = rec["MODELO_ITV"]
    marca_norm = norm_marca(marca_raw)
    variante   = rec["VARIANTE_ITV"]
    version_raw= rec["VERSION_ITV"]
    kw_str     = rec["KW_ITV"]
    fecha      = rec["FEC_MATRICULA"]   # DDMMYYYY

    # ── Fecha ────────────────────────────────────────────────────────────────
    try:
        dd, mm, yyyy = int(fecha[0:2]), int(fecha[2:4]), int(fecha[4:8])
    except:
        dd, mm, yyyy = 1, 1, 2025
    month_name = MESES_EN.get(mm, "")
    sort_month = f"01/{mm:02d}/{yyyy}"

    # ── kW / HP ──────────────────────────────────────────────────────────────
    try:
        kw = float(kw_str)
    except:
        kw = 0.0
    hp = round(kw * 1.341) if kw else 0

    # ── Combustible ──────────────────────────────────────────────────────────
    fuel_label, fuel_type_code = fuel_type(
        rec["COD_PROPULSION_ITV"],
        rec["CATEGORIA_VEHICULO_ELECTRICO"],
        variante, version_raw
    )

    # ── Homologación ────────────────────────────────────────────────────────
    cat_homol = rec["CATEGORIA_HOMOLOGACION_ITV"]
    homol_origin, homol = homologacion(cat_homol)

    # ── Municipio / Provincia / Zona ────────────────────────────────────────
    municipio = rec["MUNICIPIO_RAW"].title()
    cod_ine = rec["COD_MUNICIPIO_INE"]
    prov_code = cod_ine[:2] if len(cod_ine) >= 2 else ""
    provincia = PROV_INE.get(prov_code, "DESCONOCIDA")
    zona_comercial = ZONA_POR_PROVINCIA.get(provincia, "")

    # ── Canal / SubCanal ────────────────────────────────────────────────────
    servicio   = rec["SERVICIO"]
    persona_fj = rec.get("PERSONA_FJ", "D")
    renting    = rec.get("RENTING", "")
    canal, subcanal = derive_canal(
        servicio, persona_fj,
        renting=renting,
        mun_code=rec.get("COD_MUNICIPIO_INE", ""),
        marca_upper=norm_marca(marca_raw).upper(),
    )

    # ── Nation ───────────────────────────────────────────────────────────────
    nation = "CN" if marca_norm in MARCAS_CN else "Otros"

    # ── Versión (5 capas) ────────────────────────────────────────────────────
    version_final = ""
    version_source = ""

    # L3: IDAE exact VARIANTE_ITV (BMW, BYD)
    if variante and variante in idae_va:
        version_final = idae_va[variante]
        version_source = "L3-IDAE-VA"

    # L1: EEA Va+Ve → nombre modelo
    if not version_final and variante and version_raw:
        key_l1 = (marca_norm, variante, version_raw)
        if key_l1 in eea_l1:
            version_final = eea_l1[key_l1]
            version_source = "L1-EEA"

    # L4: IDAE kW match (único)
    if not version_final and kw:
        marca_idae = title_marca(marca_norm)
        modelo_short = modelo_raw.split()[0].upper() if modelo_raw else ""
        key_kw = (marca_idae.upper(), modelo_short, round(kw))
        candidates = idae_kw.get(key_kw, [])
        if len(candidates) == 1:
            version_final = candidates[0]
            version_source = "L4-IDAE-KW"
        elif len(candidates) > 1:
            # Spec motor sin trim (ambiguo) — usar versión parcial
            version_final = candidates[0]  # fallback al primero
            version_source = "L4-IDAE-KW-AMB"

    # L2: EEA Va dominante
    if not version_final and variante:
        key_l2 = (marca_norm, variante)
        if key_l2 in eea_l2:
            version_final = eea_l2[key_l2]
            version_source = "L2-EEA"

    # L5: MODELO_ITV fallback
    if not version_final:
        version_final = modelo_raw
        version_source = "L5-MODELO"

    brand_display = fmt_brand(marca_norm)
    brand_model = f"{brand_display} {version_final.split()[0] if version_final else modelo_raw.title()}".strip()

    # ── Segmentación BMW Group ───────────────────────────────────────────────
    marca_seg = title_marca(marca_norm)
    modelo_seg = modelo_raw.split()[0].upper() if modelo_raw else ""
    seg_key = (marca_seg.upper(), modelo_seg)
    seg = seg_map.get(seg_key, {})
    bmw_segment = seg.get("BMW_SEGMENT", "")
    bmw_concept  = seg.get("BMW_CONCEPT", "")
    # Fallback por marca sola
    if not bmw_segment:
        for key2, val2 in seg_map.items():
            if key2[0] == marca_seg.upper():
                bmw_segment = val2.get("BMW_SEGMENT", "")
                bmw_concept  = val2.get("BMW_CONCEPT", "")
                break

    segment_origin = f"{_seg_sort(bmw_segment)}.{bmw_segment}" if bmw_segment else ""
    subsegmento = _subseg(marca_norm)
    body_type = _body_type(bmw_concept)

    # High Performance
    hp_class = high_performance(marca_norm, version_final)

    # ── Concesionario BMW (solo si marca=BMW) ─────────────────────────────
    con_data = {}
    if marca_norm == "BMW":
        muni_up = municipio.upper()
        prov_up = provincia.upper()
        key_con = (prov_up, muni_up)
        if key_con in concesin_map:
            con_data = concesin_map[key_con]
        else:
            # Fallback por provincia
            for (p, m), v in concesin_map.items():
                if p == prov_up:
                    con_data = v
                    break

    concesin_name  = con_data.get("Concesin",  "") if con_data else ""
    concesin_id    = con_data.get("Id_Con",     "") if con_data else ""
    zona_dealer_d  = con_data.get("Zona_D",     "") if con_data else ""

    return {
        "Brand":             brand_display,
        "Model":             modelo_raw.title(),
        "Fuel":              fuel_label,
        "Channel":           canal,
        "SubCanales":        subcanal,
        "Provincia":         provincia,
        "Zona":              zona_comercial,
        "Year":              yyyy,
        "Month":             month_name,
        "Segment_Origin":    segment_origin,
        "SubSegmento":       subsegmento,
        "High Performance":  hp_class,
        "Version":           version_final,
        "Body Type":         body_type,
        "Brand & Model":     brand_model,
        "Homologation_Origin": homol_origin,
        "Concesin":          concesin_name,
        "Id Concesin":       concesin_id,
        "Puntos de Venta":   concesin_name,   # mismo nivel por ahora
        "Id Punto de Venta": concesin_id,
        "Municipio":         municipio,
        "Registrations":     1,
        "HP":                hp,
        "Sort_Month":        sort_month,
        "Homologation":      homol,
        "Nation":            nation,
        "Fuel_Type":         fuel_type_code,
        "Segment":           bmw_segment,
        "Sort_Segment":      _seg_sort(bmw_segment),
        # Extra (no en Simmix pero útil para debug)
        "_version_source":   version_source,
        "_zona_dealer":      zona_dealer_d,
        "_prov_ine":         prov_code,
        "_variante":         variante,
        "_kw":               kw,
    }


# ── Helpers segmentación ────────────────────────────────────────────────────

SEG_SORT = {"UKL0":1,"SKL":2,"UKL1":3,"UKL2":4,"KKL":5,"MKL":6,"GKL":7,"GKL+":8,"GKL++1":9}
def _seg_sort(seg): return SEG_SORT.get(seg, 0)

FOCUS_BRANDS = {
    "ASTON MARTIN","AUDI","BENTLEY","BMW","CADILLAC","FERRARI","JAGUAR","LAMBORGHINI",
    "LAND ROVER","LEXUS","MASERATI","MCLAREN","MERCEDES-BENZ","MINI","PORSCHE",
    "ROLLS-ROYCE","VOLVO","ALPINA","TESLA","POLESTAR","XPENG","LOTUS","SMART",
}
def _subseg(marca):
    return "FOCUS SEGMENT" if marca.upper() in FOCUS_BRANDS else "REST"

CONCEPT_BODY = {
    "SAV":"SAV","HATCH":"HACH 5P","SEDAN":"SEDAN","ESTATE":"ESTATE",
    "TRANSPORTER":"TRANSPORTER","CABRIO":"CABRIO","COUPE":"COUPE",
    "MPV":"MPV","SAT":"SAT","PICK-UP":"PICKUP","ROADSTER":"ROADSTER",
    "SUV":"SAV",
}
def _body_type(concept): return CONCEPT_BODY.get(concept, "")


# ── Descarga automática DGT ─────────────────────────────────────────────────

DGT_URL = "https://www.dgt.es/microdatos/salida/{year}/{month}/vehiculos/matriculaciones/export_mensual_mat_{yyyymm}.zip"

def download_dgt(year, month):
    url = DGT_URL.format(year=year, month=month, yyyymm=f"{year}{month:02d}")
    print(f"Descargando {url} ...", flush=True)
    r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = z.namelist()[0]
    return io.TextIOWrapper(z.open(name), encoding="latin-1")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pipeline DGT → formato Simmix")
    parser.add_argument("--file",  help="Fichero TXT DGT descomprimido")
    parser.add_argument("--year",  type=int, help="Año (descarga auto)")
    parser.add_argument("--month", type=int, help="Mes (descarga auto)")
    parser.add_argument("--out",   required=True, help="CSV de salida")
    parser.add_argument("--brand", help="Filtrar por marca (ej: BMW)")
    args = parser.parse_args()

    # Cargar maestros
    masters = load_masters()

    # Abrir fuente de datos
    if args.file:
        fh = open(args.file, encoding="latin-1", errors="replace")
    elif args.year and args.month:
        fh = download_dgt(args.year, args.month)
    else:
        print("ERROR: especifica --file o --year + --month", file=sys.stderr)
        sys.exit(1)

    # Columnas de salida (orden Simmix)
    COLS_SIMMIX = [
        "Brand","Model","Fuel","Channel","SubCanales","Provincia","Zona",
        "Year","Month","Segment_Origin","SubSegmento","High Performance",
        "Version","Body Type","Brand & Model","Homologation_Origin",
        "Concesin","Id Concesin","Puntos de Venta","Id Punto de Venta",
        "Municipio","Registrations","HP","Sort_Month","Homologation",
        "Nation","Fuel_Type","Segment","Sort_Segment",
    ]

    out_path = Path(args.out)
    total = skipped = enriched = 0
    brand_filter = args.brand.upper() if args.brand else None

    with open(out_path, "w", newline="", encoding="utf-8-sig") as fout:
        writer = csv.DictWriter(fout, fieldnames=COLS_SIMMIX + ["_version_source","_variante","_kw"])
        writer.writeheader()

        for i, raw_line in enumerate(fh):
            line = raw_line.rstrip("\n")
            if i == 0 and not line[:8].isdigit():
                continue  # saltar cabecera

            rec = parse_line(line)
            if rec is None:
                skipped += 1
                continue

            # Filtro categoría: M1/M1G (Turismo) + N1/N1G (Comercial ligero)
            if not is_passenger_or_lcv(rec["CATEGORIA_HOMOLOGACION_ITV"]):
                skipped += 1
                continue

            # Filtro IND_NUEVO_USADO: solo vehículos nuevos (N), excluir usados (U)
            # [178:179] = IND_NUEVO_USADO: N=nuevo, U=usado/transferencia
            # Simmix solo cuenta matriculaciones de coches nuevos
            if rec.get("IND_NUEVO_USADO", "N") != "N":
                skipped += 1
                continue

            # Filtro por marca (opcional)
            if brand_filter and norm_marca(rec["MARCA_ITV"]) != brand_filter:
                skipped += 1
                continue

            total += 1
            row = enrich(rec, *masters)
            out_row = {k: row.get(k, "") for k in writer.fieldnames}
            writer.writerow(out_row)
            enriched += 1

            if enriched % 5000 == 0:
                print(f"  {enriched:,} turismos procesados...", flush=True)

    fh.close()
    print(f"\n✅ Completado: {enriched:,} turismos → {out_path}")
    print(f"   Descartados: {skipped:,} (no M1 / filtro marca)")


if __name__ == "__main__":
    main()
