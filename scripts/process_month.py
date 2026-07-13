"""
process_month.py - Descarga un mes DGT (ZIP), extrae agregados de canal, borra el raw.

URL patron (todos los anyos):
  https://www.dgt.es/microdatos/salida/{year}/{mes_sin_cero}/vehiculos/matriculaciones/export_mensual_mat_YYYYMM.zip

Filtro vehiculo: turismos (plazas>=4) + furgonetas ligeras N1 (plazas=2-3, MMA 700-3500 kg)
  Excluye motos (MMA<700), camiones pesados (MMA>3500) y trailers (plazas=0)

Uso:
  python process_month.py YYYYMM [--keep] [--force]
  python process_month.py all    [--keep] [--force]   # 2023-01 a 2025-12
  python process_month.py monthly-2026 [--keep] [--force]
  python process_month.py daily-current [--keep] [--force]
  python process_month.py auto [--keep] [--force]

Tambien genera dgt_alerts_YYYYMM.csv con avisos no bloqueantes de drift.
"""


import sys, os, zipfile, urllib.request, collections, tempfile, re, csv, unicodedata, json
from datetime import datetime


TMP_DIR = tempfile.gettempdir()
# Estructura del repo: el script vive en scripts/, los outputs en data/processed/
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.environ.get('SPANISH_REG_ROOT') or (
    os.path.dirname(_SCRIPT_DIR) if os.path.basename(_SCRIPT_DIR) == 'scripts' else _SCRIPT_DIR
)
DATA_DIR       = os.path.join(REPO_ROOT, 'data', 'processed')
MASTERS_DIR    = os.path.join(REPO_ROOT, 'masters')
VALIDATION_DIR = os.path.join(REPO_ROOT, 'validation')
os.makedirs(DATA_DIR, exist_ok=True)
OUT_DIR = DATA_DIR  # dgt_canal_*, dgt_prov_*, dgt_alerts_*
MODEL_LOOKUP_FALLBACK = os.path.join(REPO_ROOT, 'public', 'data', 'simmix_model_lookup.json')
LAST_PROCESS_ALERTS = []
DGT_MONTHLY_PAGE = 'https://www.dgt.es/menusecundario/dgt-en-cifras/matraba-listados/matriculaciones-automoviles-mensual.html'
DGT_DAILY_PAGE = 'https://www.dgt.es/menusecundario/dgt-en-cifras/matraba-listados/matriculaciones-automoviles-diario.html'


def get_url(yyyymm):
    year = yyyymm[:4]
    month = str(int(yyyymm[4:]))   # sin cero inicial
    return "https://www.dgt.es/microdatos/salida/{}/{}/vehiculos/matriculaciones/export_mensual_mat_{}.zip".format(year, month, yyyymm)


def fetch_text(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or 'utf-8'
    return raw.decode(charset, errors='replace')


def discover_monthly_links(start='202601', end=None):
    html = fetch_text(DGT_MONTHLY_PAGE)
    pattern = re.compile(r'(https://www\.dgt\.es)?(/microdatos/salida/\d{4}/\d{1,2}/vehiculos/matriculaciones/export_mensual_mat_(\d{6})\.zip)')
    links = {}
    for match in pattern.finditer(html):
        yyyymm = match.group(3)
        if yyyymm < start:
            continue
        if end is not None and yyyymm > end:
            continue
        links[yyyymm] = (match.group(1) or 'https://www.dgt.es') + match.group(2)
    return sorted(links.items())


def discover_daily_links(start=None, end=None):
    html = fetch_text(DGT_DAILY_PAGE)
    pattern = re.compile(r'(https://www\.dgt\.es)?(/microdatos/salida/\d{4}/\d{1,2}/vehiculos/matriculaciones/export_mat_(\d{8})\.zip)')
    links = {}
    for match in pattern.finditer(html):
        yyyymmdd = match.group(3)
        if start is not None and yyyymmdd < start:
            continue
        if end is not None and yyyymmdd > end:
            continue
        links[yyyymmdd] = (match.group(1) or 'https://www.dgt.es') + match.group(2)
    return sorted(links.items())


def download_zip(url, zip_path):
    if os.path.exists(zip_path):
        print("  -> ZIP ya existe en temporal")
        return True
    print("  Descargando {} ...".format(url))
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as resp, open(zip_path, 'wb') as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        size_mb = os.path.getsize(zip_path) / 1024.0 / 1024.0
        print("  -> {:.1f} MB descargados".format(size_mb))
        return True
    except Exception as e:
        print("  ERROR descarga: {}".format(e))
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return False


# Posiciones campos (0-indexed)
F_CLAVE_TRAMITE = (156, 157)   # 1=matriculación ordinaria, 2=transferencia, 5=rematriculación...
F_CLASE_MAT = (8, 9)          # COD_CLASE_MAT: 0=ordinaria
F_FEC_MATRICULA = (0, 8)
F_COD_TIPO  = (91, 93)        # COD_TIPO / COD_TIPO_VEHICULO
F_FEC_PRIM_MATRICULACION = (170, 178)
F_NUEVO_USADO = (178, 179)
F_PERSONA_FJ  = (179, 180)
F_SERVICIO    = (189, 192)
F_MUNICIPIO   = (192, 197)
F_RENTING     = (242, 243)
F_MARCA       = (17,   47)
F_MODELO      = (47,   77)   # modelo del vehiculo
F_PLAZAS      = (119, 120)   # numero de plazas (asientos)
F_MMA         = (111, 117)   # Masa Maxima Autorizada en kg  ej: "  1615" = 1615 kg
                              # motos: <700, turismos: 700-3500, camiones: >3500
F_HOMOLOGACION = (426, 430)   # M1/M1G/N1/N1G/M2/M3/N2/N3...
F_PROPULSION    = (93,   94)   # 0=gasolina, 1=diesel, 2=electrico, 6=GLP, 7=GNC
F_CAT_ELECTRICO = (453, 457)   # BEV, HEV, PHEV, REEV o vacio
F_VARIANTE_ITV  = (284, 309)   # EU type approval variant code (homologacion)
F_VERSION_ITV   = (309, 344)   # EU type approval version code

DGT_SCOPE_COD_TIPO = {'25', '40'}
MERCEDES_REST_SCOPE_MPV_MODELS = (
    'CITAN TOURER', 'CLASE T', 'T 180', 'T180', 'EQV',
    'CLASE V', 'V 220', 'V 250', 'V 300',
)
MERCEDES_REST_SCOPE_SPRINTER_VARIANTS = {
    ('0G', '3W1V3HGF'),
    ('0G', '3W1V3FBF'),
    ('20', '3W1V3FBF'),
}
TOYOTA_REST_SCOPE_CITY_VERSO_PREFIX = 'PROACE CITY VERSO'
PEUGEOT_REST_SCOPE_PARTNER_VERSIONS = {
    'YHT2-42E4AJ',
    'YHT2-42E4BJ',
}
RECENT_TEMP_TO_FINAL_MAX_DAYS = 60        # legacy constant kept for reference
TRAM_B_MAX_PROVISIONAL_DAYS = 60         # gate for is_recent_temp_to_final_used (no VIN check)
TRAM_B_VIN_DEDUP_MAX_DAYS   = 60         # disabled: set equal to TRAM_B_MAX_PROVISIONAL_DAYS
TRAM_B_EXTENDED_ALLOWLIST = {
    # Present in Simmix July 2026, but DGT has no prior N/U=N record to index.
    # Keep this exact: opening the generic 61-730 day window overcounts GLCs.
    ('W1NKM8HB5R', '08072026', '01072025'),
}
VIN10_INDEX_FILE = os.path.join(DATA_DIR, 'dgt_vin10_index.txt')
RETRO_CORRECTIONS_FILE = os.path.join(DATA_DIR, 'dgt_retro_corrections.csv')
RETRO_CORRECTIONS_HEADER = [
    'processed_date', 'target_yyyymm', 'marca', 'modelo', 'canal',
    'fuel_type', 'fuel', 'segmento', 'subseg', 'hp', 'body_type', 'delta',
]


# Mapa código INE provincia (2 dígitos) → nombre
PROV_NAMES = {
    '01':'Álava','02':'Albacete','03':'Alicante','04':'Almería','05':'Ávila',
    '06':'Badajoz','07':'Baleares','08':'Barcelona','09':'Burgos','10':'Cáceres',
    '11':'Cádiz','12':'Castellón','13':'Ciudad Real','14':'Córdoba','15':'A Coruña',
    '16':'Cuenca','17':'Girona','18':'Granada','19':'Guadalajara','20':'Gipuzkoa',
    '21':'Huelva','22':'Huesca','23':'Jaén','24':'León','25':'Lleida',
    '26':'La Rioja','27':'Lugo','28':'Madrid','29':'Málaga','30':'Murcia',
    '31':'Navarra','32':'Ourense','33':'Asturias','34':'Palencia','35':'Las Palmas',
    '36':'Pontevedra','37':'Salamanca','38':'S.C. Tenerife','39':'Cantabria','40':'Segovia',
    '41':'Sevilla','42':'Soria','43':'Tarragona','44':'Teruel','45':'Toledo',
    '46':'Valencia','47':'Valladolid','48':'Bizkaia','49':'Zamora','50':'Zaragoza',
    '51':'Ceuta','52':'Melilla',
}


# Modelos excluidos del scope (no estan en Simmix)
EXCLUIR_MARCA_MODELO = {}
EXCLUIR_MARCA_RAW = {
    'MERCEDES BENZ AG',
    'MERCEDES IDILIS',
    'MERCEDES-BENZ MINIBUS',
}
MERCEDES_EXCLUDED_MODEL_PREFIXES = (
    'MB E ', 'ECITARO', 'CITARO', 'ECONIC', 'I6 EFF', '16 12.37',
    'T21', 'RE5', 'QG5', 'CEDAH', 'ML-T', 'GRAND CANYON',
    'SPICA', 'TATOO', 'CLASSE GLA', 'CLASE C,220', 'C300', 'C220D',
    '280 SL', '250 CE', '190 SL', 'SLK 230', 'MAYBACH GLS', 'MAYBACH EQS',
)


def is_excluded_scope(marca_raw, marca, modelo):
    raw = marca_raw.strip().upper()
    m = marca.strip().upper()
    mo = modelo.strip().upper()
    if raw in EXCLUIR_MARCA_RAW:
        return True
    if m.endswith(' AG'):  # Marcas con sufijo AG (BMW AG, Audi AG, Mercedes-Benz AG…) - excluidas por Simmix
        return True
    if m == 'MERCEDES' and mo.startswith(MERCEDES_EXCLUDED_MODEL_PREFIXES):
        return True
    excl = EXCLUIR_MARCA_MODELO.get(m)
    return bool(excl and any(token in mo for token in excl))

def is_mercedes_rest_scope_cod_tipo_exception(line_s):
    """Mercedes REST vans/MPVs that provider scope includes outside 25/40."""
    cod_tipo = line_s[F_COD_TIPO[0]:F_COD_TIPO[1]].strip()
    marca_raw = line_s[F_MARCA[0]:F_MARCA[1]].strip().upper()
    if marca_raw not in ('MERCEDES', 'MERCEDES BENZ', 'MERCEDES-BENZ'):
        return False
    modelo = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
    if cod_tipo == '0G':
        if modelo.startswith(MERCEDES_REST_SCOPE_MPV_MODELS):
            return True
        if modelo.startswith('SPRINTER'):
            variante = line_s[F_VARIANTE_ITV[0]:F_VARIANTE_ITV[1]].strip().upper()
            return (cod_tipo, variante) in MERCEDES_REST_SCOPE_SPRINTER_VARIANTS
        return False
    if cod_tipo == '20':
        if modelo.startswith('SPRINTER'):
            variante = line_s[F_VARIANTE_ITV[0]:F_VARIANTE_ITV[1]].strip().upper()
            return (cod_tipo, variante) in MERCEDES_REST_SCOPE_SPRINTER_VARIANTS
        return False
    return False

def is_toyota_rest_scope_cod_tipo_exception(line_s):
    """Toyota REST MPVs/off-road variants that provider scope includes outside 25/40."""
    cod_tipo = line_s[F_COD_TIPO[0]:F_COD_TIPO[1]].strip()
    marca_raw = line_s[F_MARCA[0]:F_MARCA[1]].strip().upper()
    if marca_raw != 'TOYOTA':
        return False
    modelo = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
    homologacion = line_s[F_HOMOLOGACION[0]:F_HOMOLOGACION[1]].strip().upper()
    if cod_tipo == '0G':
        return modelo.startswith(TOYOTA_REST_SCOPE_CITY_VERSO_PREFIX) and homologacion.startswith('M1')
    if cod_tipo == '02' and modelo.startswith('LAND CRUISER') and homologacion == 'N1G':
        plazas = line_s[F_PLAZAS[0]:F_PLAZAS[1]].strip()
        mma = line_s[F_MMA[0]:F_MMA[1]].strip()
        return plazas == '2' and mma == '3500'
    return False

def is_peugeot_rest_scope_cod_tipo_exception(line_s):
    """Peugeot Partner REST vans that provider scope includes outside 25/40."""
    cod_tipo = line_s[F_COD_TIPO[0]:F_COD_TIPO[1]].strip()
    marca_raw = line_s[F_MARCA[0]:F_MARCA[1]].strip().upper()
    if marca_raw != 'PEUGEOT' or cod_tipo != '20':
        return False
    modelo = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
    modelo_norm = modelo.replace('Ó', 'O')
    if not modelo_norm.startswith('PARTNER - FURGON M DIE'):
        return False
    homologacion = line_s[F_HOMOLOGACION[0]:F_HOMOLOGACION[1]].strip().upper()
    variante = line_s[F_VARIANTE_ITV[0]:F_VARIANTE_ITV[1]].strip().upper()
    version = line_s[F_VERSION_ITV[0]:F_VERSION_ITV[1]].strip().upper()
    return homologacion == 'N1' and variante == 'D' and version in PEUGEOT_REST_SCOPE_PARTNER_VERSIONS

def _parse_dgt_date(raw):
    raw = (raw or '').strip()
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return datetime.strptime(raw, '%d%m%Y').date()
    except ValueError:
        return None

def is_recent_temp_to_final_used(line_s, max_days=RECENT_TEMP_TO_FINAL_MAX_DAYS):
    """Simmix counts some recent temporary-to-final registrations marked U by DGT.

    BMW is excluded: BMW always issues an initial N/U=N registration in the prior
    month before finalising with tram=B N/U=U.  Simmix deduplicates by VIN and
    counts the vehicle in the first-registration month, so including the tram=B
    record would double-count it.

    For all other brands the old 60-day window is replaced by a 2-year window
    (TRAM_B_MAX_PROVISIONAL_DAYS = 730).  This passes all legitimate same-year
    and prior-year provisionals while still blocking DGT data anomalies such as
    8-year-old provisional dates.  process_lines() generates a retroactive
    correction (−1) for the provisional month whenever fec_prim falls in a
    different month, mirroring Simmix's VIN-deduplication logic.
    """
    if line_s[F_CLAVE_TRAMITE[0]:F_CLAVE_TRAMITE[1]].strip() != 'B':
        return False
    if line_s[F_NUEVO_USADO[0]:F_NUEVO_USADO[1]].strip() != 'U':
        return False
    # BMW: tram=B finalisation is always preceded by an N/U=N record counted in
    # the prior month — exclude entirely (no retroactive correction needed).
    _marca_raw = line_s[F_MARCA[0]:F_MARCA[1]]
    _modelo_raw = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
    if normalize_marca(_marca_raw, _modelo_raw) == 'BMW':
        return False
    fec_mat = _parse_dgt_date(line_s[F_FEC_MATRICULA[0]:F_FEC_MATRICULA[1]])
    fec_prim = _parse_dgt_date(
        line_s[F_FEC_PRIM_MATRICULACION[0]:F_FEC_PRIM_MATRICULACION[1]]
    )
    if not fec_mat or not fec_prim:
        return False
    days = (fec_mat - fec_prim).days
    return 0 <= days <= TRAM_B_MAX_PROVISIONAL_DAYS


def _tram_b_retro_yyyymm(line_s, current_yyyymm):
    """Retroactive cross-month correction — disabled.

    The correction mechanism moved tram=B counts from the provisional month to
    the finalisation month, but Simmix assigns vehicles to the *first*
    registration month, not the finalisation month.  Applying the correction
    therefore creates a monthly mismatch vs Simmix even though the yearly total
    stays the same.  Keeping the function signature so callers don't need to
    change; it always returns None so no corrections are ever generated.
    """
    return None  # disabled — see comment above

def visible_dgt_vin10(line_s):
    """Prefijo de bastidor visible en DGT: WBA15GR000, WBAUX11060, etc."""
    m = re.search(r'([0-9][A-Z0-9*]{9,24})', line_s[47:110])
    if not m:
        return ''
    token = m.group(1)
    if len(token) < 11 or not token[0].isdigit():
        return ''
    return token[1:11].replace('*', '').upper()

_TECH_CODE_NOISE = {
    'BMW', 'GMBH', 'BAYERISCHE', 'MOTOREN', 'WERKE', 'AG', 'ND',
    'SA', 'SAS', 'SL', 'AUTO', 'AUTOMOBILES', 'AUTOMOBILI',
}

def _has_useful_itv_tech_code(line_s):
    """True si el area tipo/variante/version contiene codigos homologados utiles."""
    tech_area = line_s[250:330].upper()
    tokens = re.findall(r'[A-Z0-9]{3,}', tech_area)
    for token in tokens:
        if token in _TECH_CODE_NOISE:
            continue
        if len(token) >= 4 and re.search(r'[A-Z]', token) and re.search(r'\d', token):
            return True
    return False

def _has_known_itv_variant(line_s, marca):
    sbrand = _BRAND_NORM.get(marca, marca)
    va = line_s[F_VARIANTE_ITV[0]:F_VARIANTE_ITV[1]].strip().upper()
    return bool(va and _EEA_LOOKUP.get((sbrand, va)))

def invalid_itv_scope_reason(line_s, marca, canal, servicio, persona, renting):
    """Devuelve motivo si un registro DGT tiene ficha ITV no explotable."""
    if _has_useful_itv_tech_code(line_s):
        return ''
    plazas_s = line_s[F_PLAZAS[0]:F_PLAZAS[1]].strip()
    if plazas_s not in ('', '0'):
        return ''
    # Furgonetas eléctricas Mercedes (e-Sprinter, eVito, eCitan, EQT): DGT no rellena
    # siempre los campos ITV para eléctricos pero son N1 válidas en scope Simmix.
    _MERCEDES_ELEC_VANS = {'E-SPRINTER', 'EVITO', 'ECITAN', 'EQT'}
    _modelo_first = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
    _modelo_first = _modelo_first.split()[0] if _modelo_first else ''
    if marca.upper() == 'MERCEDES' and _modelo_first in _MERCEDES_ELEC_VANS:
        return ''  # No excluir — furgoneta eléctrica N1 válida en scope Simmix
    # Furgonetas N1 de marcas comerciales: algunas tienen plazas=0 en DGT
    # pero homologación N1 explícita → deben incluirse (ISUZU N-series, DFSK C35/Glory)
    homol = line_s[F_HOMOLOGACION[0]:F_HOMOLOGACION[1]].strip().upper()
    _FURGONETA_N1_BRANDS = {'ISUZU', 'DFSK'}
    if homol.startswith('N1') and marca.upper() in _FURGONETA_N1_BRANDS:
        return ''  # No excluir — N1 válido con plazas=0 (cabina carga)
    fabricante = line_s[330:390].strip().upper()
    details = ['plazas={}'.format(plazas_s or 'vacio')]
    if fabricante in ('', '-', 'ND'):
        details.append('fabricante={}'.format(fabricante or 'vacio'))
    return 'ficha ITV sin codigos tipo/variante/version utiles ({})'.format(', '.join(details))

def itv_quality_warning_reason(line_s, marca):
    """Devuelve motivo no bloqueante para registros tecnicamente sospechosos."""
    mma_s = line_s[F_MMA[0]:F_MMA[1]].strip()
    homol = line_s[F_HOMOLOGACION[0]:F_HOMOLOGACION[1]].strip().upper()
    if not homol.startswith(('M1', 'N1')):
        return ''
    if mma_s and mma_s.isdigit() and int(mma_s) > 0:
        return ''
    if _has_known_itv_variant(line_s, marca):
        return ''
    return 'ficha ITV con MMA invalida pendiente de revision (homologacion={}, mma={})'.format(
        homol or 'vacio',
        mma_s or 'vacio',
    )

# ── Regla carroceros/camperizadores → marca del chasis (metodología Simmix) ──
# Simmix atribuye los vehículos carrozados/camperizados a la marca y modelo del
# chasis base. En DGT aparecen con la marca del carrocero. Detectamos el chasis
# por palabras clave en el MODELO_ITV; si no se detecta, se mantiene la marca
# original y se emite alerta CARROCERO_UNMAPPED para ampliar el mapeo.
CARROCERO_BRANDS = {
    '3 CARROCEROS', 'A.A. AIRBUS', 'ADRIA', 'BENIMAR', 'BERGADANA', 'C.I.', 'CAPRON',
    'CARROCERIAS SANCA, S.A.', 'CARROCERIAS SEVILLA', 'CARROZADOS TECAI',
    'CHALLENGER', 'CHT', 'CODETRANS', 'COINPOL', 'DETHLEFFS', 'ERKE',
    'EUROCARROCERA', 'EUROGAZA', 'GIOTTILINE', 'GRAU', 'IGLUVAN', 'INDUSAUTO',
    'JEANJE', 'MC LOUIS', 'MCLOUIS', 'MEBAUTO', 'RECAPOL', 'RODRIGUEZ LOPEZ AUTO',
    'ROLLER TEAM', 'ROMU', 'SEMICARFRAN,S.L', 'SOCAGE', 'SORIBERICA', 'SORTIMO',
    'STIL CONVERSION', 'SUBIELA', 'TECNOVE', 'TECNOVE FIBERGLASS', 'TSD', 'ULTRAND',
    'VSVE', 'ZAGO AUTOMOTIVE',
    'MULTITEL', 'WEINSBERG',
}
_CHASSIS_RULES = [
    (re.compile(r'\bDUCATO'),                      'FIAT',            'DUCATO'),
    (re.compile(r'\bBOXER'),                       'PEUGEOT',         'BOXER'),
    (re.compile(r'\bJUMPER'),                      'CITROEN',         'JUMPER'),
    (re.compile(r'\bJUMPY'),                       'CITROEN',         'JUMPY'),
    (re.compile(r'\bBERLINGO'),                    'CITROEN',         'BERLINGO'),
    (re.compile(r'\bPARTNER'),                     'PEUGEOT',         'PARTNER'),
    (re.compile(r'\bTRANSIT\s*CUSTOM'),            'FORD',            'TRANSIT CUSTOM'),
    (re.compile(r'\bTRANSIT\s*COURIER'),           'FORD',            'TRANSIT COURIER'),
    (re.compile(r'\bTRANSIT|\bTOURNEO'),           'FORD',            'TRANSIT'),
    (re.compile(r'\bMASTER'),                      'RENAULT TRUCKS',  'MASTER'),
    (re.compile(r'\bTRAFIC'),                      'RENAULT TRUCKS',  'TRAFIC'),
    (re.compile(r'\bTGE\b'),                       'MAN',             'TGE'),
    (re.compile(r'\bCANTER|\bFUSO'),               'MITSUBISHI-FUSO', 'CANTER'),
    (re.compile(r'\bSPRINTER'),                    'MERCEDES',        'SPRINTER'),
    (re.compile(r'\bCRAFTER'),                     'VOLKSWAGEN',      'CRAFTER'),
    (re.compile(r'\bAMAROK'),                      'VOLKSWAGEN',      'AMAROK'),
    (re.compile(r'\bDAILY'),                       'IVECO',           'DAILY'),
    (re.compile(r'\b(?:35|50|70)[CS]\d*|\b120E\b'), 'IVECO',          'DAILY'),
    (re.compile(r'\bMOVANO'),                      'OPEL',            'MOVANO'),
    (re.compile(r'\bVIVARO'),                      'OPEL',            'VIVARO'),
    (re.compile(r'\bCORSA'),                       'OPEL',            'CORSA'),
    (re.compile(r'\bINTERSTAR|\bNV400'),           'NISSAN',          'INTERSTAR'),
    (re.compile(r'\bPROACE'),                      'TOYOTA',          'PROACE'),
    (re.compile(r'\bHILUX|\bHI\s*LUX'),            'TOYOTA',          'HI LUX'),
    (re.compile(r'\bEXPERT'),                      'PEUGEOT',         'EXPERT'),
    (re.compile(r'\bSCUDO'),                       'FIAT',            'SCUDO'),
    (re.compile(r'\bSANDERO'),                     'DACIA',           'SANDERO'),
    (re.compile(r'\bCADDY'),                       'VOLKSWAGEN',      'CADDY'),
    (re.compile(r'\bREXTON|\bKG\s+MOBILITY'),      'SSANGYONG',       'REXTON'),
    (re.compile(r'\b[0-9]?ZFA'),                    'FIAT',            'DUCATO'),
    (re.compile(r'\b[0-9]?WF0'),                    'FORD',            'TRANSIT'),
    (re.compile(r'\b[0-9]?VF7'),                    'CITROEN',         'JUMPER'),
    (re.compile(r'\b[0-9]?VF3'),                    'PEUGEOT',         'BOXER'),
    (re.compile(r'\b[0-9]?VF1'),                    'RENAULT',         'MASTER'),
    (re.compile(r'\b[0-9]?W1V'),                    'MERCEDES',        'SPRINTER'),
    (re.compile(r'\bN[LMPQN]R|\bN-?SERIE'),        'ISUZU',           'N-SERIES'),
]


def reassign_carrocero(marca, modelo):
    """(marca, modelo, unmapped) — reasigna carrozados a la marca del chasis."""
    if marca.strip().upper() not in CARROCERO_BRANDS:
        return marca, modelo, False
    texto = (modelo or '').upper()
    for pat, m2, mo2 in _CHASSIS_RULES:
        if pat.search(texto):
            return m2, mo2, False
    return marca, modelo, True


# ── Rescate N2 de derivados de furgoneta (scope Simmix) ─────────────────────
# Simmix incluye variantes N2 (>3.500 kg) de furgonetas grandes que el filtro
# M1/N1 excluiría: Renault Trucks Master 4.5t, MAN TGE, Fuso Canter, Isuzu
# serie N, Iveco Daily. Devuelve la marca destino o None si no aplica.
def n2_van_target(marca, modelo):
    m = marca.strip().upper()
    mo = (modelo or '').upper()
    if m == 'RENAULT TRUCKS':
        return 'RENAULT TRUCKS'
    if m == 'RENAULT' and 'MASTER' in mo:
        return 'RENAULT TRUCKS'
    if m == 'MAN' and 'TGE' in mo:
        return 'MAN'
    if m in ('MITSUBISHI-FUSO', 'FUSO'):
        return 'MITSUBISHI-FUSO'  # Canter y variantes con código numérico (35F15, FE…)
    if m == 'ISUZU':
        return 'ISUZU'
    if m == 'IVECO':
        return 'IVECO'  # Daily y variantes (35C17, 40C15, 50C18, 70C17…)
    return None


# ── Enriquecimiento modelo → segmento/body_type (desde Simmix) ────────────
_APPROVAL_RE   = re.compile(r'\s+[A-Z0-9]{6,}\s*$')
_BMW_SERIE_RE  = re.compile(r'^([1-9])\d{2}[A-Z]')
_LEXUS_PFX_RE  = re.compile(r'^([A-Z]{2,3})\d')
# BMW electric/PHEV models use lowercase 'i' prefix — restore after upper() normalization
_BMW_IMODEL_FIX = {
    'I3': 'i3', 'I4': 'i4', 'I5': 'i5', 'I7': 'i7', 'I8': 'i8',
    'IX': 'iX', 'IX1': 'iX1', 'IX2': 'iX2', 'IX3': 'iX3',
}


_BRAND_NORM = {
    'MERCEDES-BENZ': 'MERCEDES', 'MERCEDES BENZ': 'MERCEDES',
    'MERCEDES-AMG': 'MERCEDES',   # AMG cars map to Mercedes scope brand
    'LYNK&CO': 'LYNK & CO',
    "ALKE'": 'ALKE',
    '212': 'BAW',
    'AUTOMOBILI LAMBORGHINI S.P.A.': 'LAMBORGHINI',
    'DEEPAL': 'CHANGAN',
    'DS AUTOMOBILES': 'DS',
    'FOTON': 'FOTON MOTORS',
    'FUSO': 'MITSUBISHI-FUSO',
    'GREAT WALL MOTOR COMPANY LIMIT': 'GWM',
    'MITSUBISHI FUSO': 'MITSUBISHI-FUSO',
    'RENAULT TRUCKS SAS': 'RENAULT TRUCKS',
    'SWM': 'SHINERAY',
}
_MERC_CLASS = {
    'A':'CLASE A','B':'CLASE B','C':'CLASE C','E':'CLASE E','G':'CLASE G',
    'S':'CLASE S','T':'CLASE T','V':'CLASE V','SL':'CLASE SL',
    'GLA':'CLASE GLA','GLB':'CLASE GLB','GLC':'CLASE GLC','GLE':'CLASE GLE',
    'GLS':'CLASE GLS','CLA':'CLASE CLA','CLE':'CLASE CLE','CLS':'CLASE CLS',
    'GLC COUPE':'CLASE GLC COUPE','GLE COUPE':'CLASE GLE COUPE',
    'EQA':'EQA','EQB':'EQB','EQC':'EQC','EQE':'EQE',
    'EQS':'EQS','EQT':'EQT','EQV':'EQV','AMG GT':'AMG GT',
}


def _strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def _model_candidates(sbrand, s):
    """Genera lista de candidatos (sbrand, model_name) para buscar en el lookup."""
    # Quitar código de homologación (6+ alfanum al final) y acentos
    s = s.replace('\xa0', ' ')
    s = _strip_accents(s)
    s_probe = s
    s = _APPROVAL_RE.sub('', s).strip()
    # Quitar prefijo marca si está repetido en el modelo
    bwords = sbrand.split(); swords = s.split()
    if swords[:len(bwords)] == bwords:
        swords = swords[len(bwords):]
        s = ' '.join(swords)
    for pfx in ('NUEVO ', 'NEW '):
        if s.startswith(pfx): s = s[len(pfx):].strip()
    s_nd = re.sub(r'([A-Z]+)-([\d])', r'\1\2', s)  # CX-5→CX5
    cands = []
    if sbrand == 'MERCEDES':
        if s.startswith('VITO'):
            cands.append(('MERCEDES-V', 'VITO'))
        if s.startswith('SPRINTER'):
            cands.append((sbrand, 'SPRINTER 300'))
        if s.startswith('ESPRINTER') or s.startswith('E-SPRINTER'):
            cands.append((sbrand, 'E-SPRINTER'))
        if s.startswith('CITAN'):
            cands.append((sbrand, 'CITAN'))
        if s.startswith('ECITAN') or s.startswith('E-CITAN'):
            cands.append((sbrand, 'ECITAN'))
        if s.startswith('MARCO POLO'):
            cands.append((sbrand, 'MARCO POLO'))
        if s.startswith('EVITO') or s.startswith('E-VITO'):
            cands.append((sbrand, 'EVITO'))
        if s.startswith('V-KLASSE') or s.startswith('CLASE V'):
            cands.append((sbrand, 'CLASE V'))
        if re.search(r'\bGLC\b', s_probe) and 'COUP' in s_probe:
            cands.append((sbrand, 'CLASE GLC COUPE'))
        if re.search(r'\bGLE\b', s_probe) and 'COUP' in s_probe:
            cands.append((sbrand, 'CLASE GLE COUPE'))
        if re.search(r'\bMAYBACH\s+SL\b', s_probe):
            cands.append((sbrand, 'CLASE SL'))
        for code, name in sorted(_MERC_CLASS.items(), key=lambda x: -len(x[0])):
            if s == code or s.startswith(code + ' '):
                cands.append((sbrand, name)); break
    if sbrand == 'BMW':
        m = _BMW_SERIE_RE.match(s)
        if m: cands.append((sbrand, f'SERIE {m.group(1)}'))
        if re.match(r'^1ER\s+REIHE', s): cands.append((sbrand, 'SERIE 1'))
        if re.match(r'^3ER\s+REIHE', s): cands.append((sbrand, 'SERIE 3'))
        if re.match(r'^X\s+REIHE', s): cands.append((sbrand, 'X1'))
        if re.match(r'^(?:116|118|120|128|M135)', s): cands.append((sbrand, 'SERIE 1'))
        if re.match(r'^(?:216|218|220|225|230|M2|M235|M240)', s): cands.append((sbrand, 'SERIE 2'))
        if re.match(r'^(?:320|330|M3|M340)', s): cands.append((sbrand, 'SERIE 3'))
        if re.match(r'^(?:M4|M440)', s): cands.append((sbrand, 'SERIE 4'))
        if re.match(r'^(?:520|530|M5|M550)', s): cands.append((sbrand, 'SERIE 5'))
        if re.match(r'^(?:M760)', s): cands.append((sbrand, 'SERIE 7'))
        if re.match(r'^(?:M8|840|850)', s): cands.append((sbrand, 'SERIE 8'))
    if sbrand == 'LEXUS':
        m = _LEXUS_PFX_RE.match(s_nd)
        if m: cands.append((sbrand, m.group(1)))
    if sbrand == 'MG':
        first = s_nd.split()[0] if s_nd.split() else s_nd
        cands += [(sbrand, 'MG ' + first), (sbrand, re.sub(r'([A-Z]+)(\d)', r'\1 \2', first))]
    if sbrand == 'AUDI':
        sx = s.replace(' ', '')
        sx_no_dash = sx.replace('-', '')
        if sx.startswith('Q3SPORTBACK') or sx.startswith('Q3SB'):
            cands.append((sbrand, 'Q3 SPORTBACK'))
        if sx.startswith('Q5SPORTBACK'): cands.append((sbrand, 'Q5 SPORTBACK'))
        if sx.startswith('Q5SB'): cands.append((sbrand, 'Q5 SPORTBACK'))
        if sx.startswith('SQ5SB'): cands.append((sbrand, 'Q5 SPORTBACK'))
        if sx.startswith('Q4SPORTBACK'): cands.append((sbrand, 'Q4 SPORTBACK E-TRON'))
        elif sx.startswith('Q4'): cands.append((sbrand, 'Q4 E-TRON'))
        if sx.startswith('Q6SBE') or sx.startswith('Q6SPORTBACKE') or sx.startswith('SQ6SBE') or sx.startswith('SQ6SPORTBACKE'):
            cands.append((sbrand, 'Q6 E-TRON SPORTBACK'))
        if sx.startswith('Q6') or sx.startswith('SQ6'): cands.append((sbrand, 'Q6 E-TRON'))
        if sx.startswith('A6ALLROAD'): cands.append((sbrand, 'A6 ALLROAD'))
        if sx.startswith('A6SBE') or sx.startswith('A6AVE') or sx.startswith('A6LIME'):
            cands.append((sbrand, 'A6'))
        if sx_no_dash.startswith('ETRONGT') or sx_no_dash.startswith('RSETRONGT') or sx_no_dash.startswith('SETRONGT'):
            cands.append((sbrand, 'E-TRON GT'))
        if sx.startswith('Q8ETRON') or sx.startswith('Q8E-TRON'): cands.append((sbrand, 'Q8 E-TRON'))
        if sx.startswith('A8L') or sx.startswith('S8') or sx.startswith('LIMOUSINE'):
            cands.append((sbrand, 'A8'))
        for prefix, model in (
            ('RSQ3SPORTBACK', 'Q3 SPORTBACK'), ('RSQ3', 'Q3'), ('SQ5SPORTBACK', 'Q5 SPORTBACK'),
            ('SQ2', 'Q2'), ('SQ5', 'Q5'), ('SQ7', 'Q7'), ('RSQ8', 'Q8'), ('SQ8', 'Q8'), ('RS3', 'A3'), ('S3', 'A3'),
            ('RS4', 'A4'), ('RS5', 'A5'), ('RS6', 'A6'), ('S6', 'A6'), ('S5', 'A5'),
        ):
            if sx.startswith(prefix):
                cands.append((sbrand, model)); break
        if sx.startswith('CRAFTER'):
            cands.append((sbrand, 'CRAFTER'))
    if sbrand == 'DS':
        if re.match(r'^(?:DS\s*)?7\s*CROSSBACK\b', s):
            cands.append((sbrand, 'DS7 CROSSBACK'))
        m = re.match(r'^(?:DS\s*)?([3479])\b', s)
        if m:
            cands.append((sbrand, {'3':'DS3 CROSSBACK','4':'DS4','7':'DS7 CROSSBACK','9':'DS9'}[m.group(1)]))
    if sbrand == 'IVECO':
        if re.match(r'^(?:IVECO\s*)?(?:\d{2}[SC]|DAILY|50C|70C|SOCAGE|MULTITEL|WING)', s):
            cands.append((sbrand, 'DAILY'))
    if sbrand == 'PEUGEOT':
        sp = s.replace(' ', '')
        for code in ('2008','208','3008','308','408','5008','508'):
            if sp.startswith('N' + code) or sp.startswith(code):
                cands.append((sbrand, code)); break
        for code in ('BOXER','EXPERT','PARTNER','RIFTER','TRAVELLER'):
            if code in s:
                cands.append((sbrand, code)); break
    if sbrand == 'CITROEN':
        s3 = s.replace('CITROEN ', '')
        if re.match(r'^(?:NUEVO\s+)?C5\s*X\b', s3):
            cands.append((sbrand, 'C5X'))
        for code in ('C3 AIRCROSS','C5 AIRCROSS','BERLINGO','JUMPER','JUMPY','SPACETOURER','C4X','C3','C4'):
            if code in s3:
                cands.append((sbrand, code)); break
    if sbrand == 'FIAT':
        if re.match(r'^(?:FIAT\s*)?DOBLO\b|^E-DOBLO\b', s): cands.append((sbrand, 'DOBLO CARGO'))
        if re.match(r'^(?:FIAT\s*)?DUCATO\b', s): cands.append((sbrand, 'DUCATO'))
        if re.match(r'^(?:FIAT\s*)?SCUDO\b', s): cands.append((sbrand, 'SCUDO'))
        if re.match(r'^(?:FIAT\s*)?FIORINO\b', s): cands.append((sbrand, 'FIORINO'))
        if re.match(r'^(?:FIAT\s*)?PANDA\b', s): cands.append((sbrand, 'PANDA'))
        if re.match(r'^(?:FIAT\s*)?TIPO\b', s): cands.append((sbrand, 'TIPO'))
        if re.match(r'^(?:FIAT\s*)?600\b', s): cands.append((sbrand, '600'))
        if re.match(r'^(?:FIAT\s*)?500\b', s): cands.append((sbrand, '500'))
        if 'ULYSSE' in s: cands.append((sbrand, 'E-ULYSSE'))
    if sbrand == 'OPEL':
        for code, model in (
            ('GRANDLAND', 'GRANDLAND X'), ('CORSA', 'CORSA'), ('MOKKA', 'MOKKA'),
            ('COMBO', 'COMBO'), ('VIVARO', 'VIVARO'), ('MOVANO', 'MOVANO'),
            ('ZAFIRA', 'ZAFIRA LIFE'), ('ASTRA', 'ASTRA'), ('CROSSLAND', 'CROSSLAND'),
        ):
            if code in s:
                cands.append((sbrand, model)); break
    if sbrand == 'MINI':
        if 'ACEMAN' in s:
            cands.append((sbrand, 'ACEMAN'))
        if 'CABRIO' in s or 'CONVERTIBLE' in s or '3WMW41GD' in s_probe:
            cands.append((sbrand, 'CABRIO'))
        elif 'COUNTRYMAN' in s: cands.append((sbrand, 'COUNTRYMAN'))
        elif 'CLUBMAN' in s: cands.append((sbrand, 'CLUBMAN'))
        else: cands.append((sbrand, 'HATCHBACK'))
    if sbrand == 'CUPRA':
        first1 = s.split()[0] if s.split() else s
        cands += [(sbrand, 'CUPRA ' + first1)]
    if sbrand == 'TOYOTA':
        s2 = re.sub(r'([A-Z]{2,})(\d)', r'\1 \2', s)
        if 'HILUX' in s2: cands.append((sbrand, 'HI LUX'))
        if 'GR 86' in s2 or 'GR86' in s2: cands.append((sbrand, 'GR86'))
        if 'YARIS CROSS' in s2: cands.append((sbrand, 'YARIS CROSS'))
        if 'C-HR' in s2 or 'CHR' in s2: cands.append((sbrand, 'C-HR'))
        if 'RAV4' in s2: cands.append((sbrand, 'RAV 4'))
        if 'AYGO X' in s2: cands.append((sbrand, 'AYGO X'))
        if 'PROACE CITY VERSO' in s2: cands.append((sbrand, 'PROACE VERSO'))
        elif 'PROACE CITY' in s2: cands.append((sbrand, 'PROACE CITY'))
        elif 'PROACE VERSO' in s2: cands.append((sbrand, 'PROACE VERSO'))
        elif 'PROACE' in s2: cands.append((sbrand, 'PROACE'))
        cands += [(sbrand, s2), (sbrand, s2.split()[0] if s2.split() else s2)]
    if sbrand == 'OMODA':
        sx = s.replace(' ', '')
        for n in ('5', '7', '9'):
            if sx.startswith('OMODA' + n):
                cands.append((sbrand, 'OMODA ' + n)); break
        # También el string original sin strip de marca (por si DGT pone "OMODA 7 PHEV")
        cands.append((sbrand, s_probe.strip()))
    if sbrand == 'JAECOO':
        sx = s.replace(' ', '')
        for n in ('5', '7', '8'):
            if sx.startswith('JAECOO' + n):
                cands.append((sbrand, 'JAECOO ' + n)); break
        cands.append((sbrand, s_probe.strip()))
    if sbrand == 'EBRO':
        for code in ('S400', 'S700', 'S800', 'S900'):
            if s.startswith(code) or s_probe.strip().upper().startswith(code):
                cands.append((sbrand, code)); break
    if sbrand == 'EVO':
        sx = s.replace(' ', '')
        if sx.startswith('EVOCROSS4') or sx.startswith('CROSS4'): cands.append((sbrand, 'CROSS 4'))
        for n in ('3','4','5','6','7'):
            if sx.startswith('EVO' + n):
                cands.append((sbrand, 'EVO ' + n)); break
    if sbrand == 'MERCEDES':
        if s.startswith('SPRINTER'): cands.append((sbrand, 'SPRINTER 300'))
        if 'GLC COUPE' in s: cands.append((sbrand, 'CLASE GLC COUPE'))
        if 'GLE COUPE' in s: cands.append((sbrand, 'CLASE GLE COUPE'))
        if s.startswith('AMG '):
            amg = s[4:]
            for code, name in sorted(_MERC_CLASS.items(), key=lambda x: -len(x[0])):
                if amg == code or amg.startswith(code + ' '):
                    if 'COUPE' in amg and code in ('GLC', 'GLE'):
                        cands.append((sbrand, name + ' COUPE'))
                    cands.append((sbrand, name)); break
    if sbrand == 'VOLVO':
        if s.startswith('YV1XZK7'):
            cands.append((sbrand, 'EX30'))
        for code in ('EX40', 'EC40', 'EX90', 'ES90', 'EX30', 'XC40', 'XC60', 'XC90', 'V60', 'V90', 'S60'):
            if s.startswith(code):
                cands.append((sbrand, code)); break
    if sbrand == 'LAND ROVER':
        if s.startswith('A5C2') or s.startswith('LM'):
            cands.append((sbrand, 'DEFENDER'))
    if sbrand == 'PORSCHE':
        if s.startswith('CAYENNE E-HYBRID') or s == 'CAYENNE S':
            cands.append((sbrand, 'CAYENNE COUPE'))
    if sbrand == 'MAZDA':
        if s.startswith('MAZDA2 HYBRID'): cands.append((sbrand, 'MAZDA 2'))
        cands += [(sbrand, re.sub(r'([A-Z]+)(\d)', r'\1 \2', s)), (sbrand, s_nd)]
    if sbrand == 'VOLKSWAGEN':
        sx = s.replace(' ', '')
        if sx.startswith('ID.BUZZ') or sx.startswith('IDBUZZ'): cands.append((sbrand, 'ID.BUZZ'))
        if sx.startswith('KOMBI'): cands.append((sbrand, 'CARAVELLE'))
    if sbrand == 'SUZUKI':
        if s.startswith('S-CROSS'): cands.append((sbrand, 'SX4'))
    if sbrand == 'HYUNDAI':
        sx = s.replace(' ', '')
        if s.startswith('TUCSON') or s.startswith('TUCSON,IX35'): cands.append((sbrand, 'TUCSON'))
        if s.startswith('KONA') or s.startswith('KONA, KAUAI'): cands.append((sbrand, 'KONA'))
        if sx.startswith('IONIQ5'): cands.append((sbrand, 'IONIQ 5'))
        if sx.startswith('IONIQ6'): cands.append((sbrand, 'IONIQ 6'))
        if sx.startswith('I30') or sx.startswith('I30N'): cands.append((sbrand, 'I30'))
    if sbrand == 'SSANGYONG':
        if s.startswith('KORANDO'): cands.append((sbrand, 'KORANDO K4'))
    if sbrand == 'SUBARU':
        if s.startswith('CROSSTREK'): cands.append((sbrand, 'XV'))
    if sbrand == 'LYNK & CO':
        cands.append((sbrand, 'LYNK&CO ' + s))
    if sbrand == 'DR':
        nm = re.search(r'^(\d+)', s)
        if nm: cands.append((sbrand, f'DR{nm.group(1)}'))
    words = s.split()
    cands += [(sbrand, s), (sbrand, s_nd),
              (sbrand, re.sub(r'\bI (\d)', r'I\1', s))]
    if len(words) >= 2: cands.append((sbrand, ' '.join(words[:2])))
    if words: cands.append((sbrand, words[0]))
    return cands


# Cargado una vez al inicio del proceso
_ENRICHMENT = {}   # (simmix_brand, simmix_model) → {modelo, seg, sub, hp, body}


def _load_enrichment():
    global _ENRICHMENT
    fname = os.path.join(MASTERS_DIR, 'master_version_enrichment.csv')
    if not os.path.exists(fname):
        return
    with open(fname, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            key = (row['brand'].strip().upper(), row['version_dgt'].strip().upper())
            if key not in _ENRICHMENT:
                _ENRICHMENT[key] = {
                    'modelo': row.get('model','').strip().upper(),
                    'seg'   : _canon_seg(row.get('segment','')),
                    'sub'   : row.get('subsegment','').strip(),
                    'hp'    : row.get('high_perf','').strip(),
                    'body'  : row.get('body_type','').strip(),
                }
    print(f'  -> Enrichment: {len(_ENRICHMENT):,} combos cargados')

# EEA type approval lookup: (brand, variante_code) → modelo canónico
_EEA_LOOKUP = {}  # (brand, variante_itv_stripped) → modelo

def _load_eea_lookup():
    global _EEA_LOOKUP
    fname = os.path.join(MASTERS_DIR, 'master_eea_model_lookup.csv')
    if not os.path.exists(fname):
        return
    with open(fname, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            brand  = row['brand'].strip().upper()
            va     = row['variante'].strip().upper()
            modelo = row['modelo'].strip().upper()
            if brand and va and modelo:
                key = (brand, va)
                if key not in _EEA_LOOKUP:
                    _EEA_LOOKUP[key] = modelo
    print(f'  -> EEA lookup: {len(_EEA_LOOKUP):,} variante codes cargados')

# Carga lookup brand+model desde Simmix BBDD directamente
_MODEL_LOOKUP = {}  # (simmix_brand, simmix_model) → {seg, sub, hp, body}
_MODEL_LOOKUP_PATCHES = {
    ('MINI', 'ACEMAN'): {
        'modelo': 'ACEMAN', 'seg': '2.UKL1', 'sub': 'FOCUS SEGMENT',
        'hp': 'Standard', 'body': 'SAV', 'fuel_detail': 'Electrico',
    },
    ('VOLVO', 'EC40'): {
        'modelo': 'EC40', 'seg': '3.UKL2', 'sub': 'FOCUS SEGMENT',
        'hp': 'Standard', 'body': 'SAV', 'fuel_detail': 'Electrico',
    },
    ('VOLVO', 'ES90'): {
        'modelo': 'ES90', 'seg': '5.MKL', 'sub': 'FOCUS SEGMENT',
        'hp': 'Standard', 'body': 'SEDAN', 'fuel_detail': 'Electrico',
    },
    ('VOLVO', 'EX40'): {
        'modelo': 'EX40', 'seg': '3.UKL2', 'sub': 'FOCUS SEGMENT',
        'hp': 'Standard', 'body': 'SAV', 'fuel_detail': 'Electrico',
    },
    ('VOLVO', 'EX90'): {
        'modelo': 'EX90', 'seg': '5.MKL', 'sub': 'FOCUS SEGMENT',
        'hp': 'Standard', 'body': 'SAV', 'fuel_detail': 'Electrico',
    },
    ('AUDI', 'CRAFTER'): {
        'modelo': 'CRAFTER', 'seg': '', 'sub': 'FOCUS SEGMENT',
        'hp': 'Standard', 'body': '', 'fuel_detail': 'Diesel',
    },
}


_FOCUS_SUBSEGMENTS = {
    'FOCUS SEGMENT',
    'TRADITIONAL COMPETITION',
    'NEW PLAYERS & TESLA',
}


def _focus_bucket(value):
    return 'FOCUS SEGMENT' if (value or '').strip().upper() in _FOCUS_SUBSEGMENTS else 'REST'


_SEG_PREFIX_RE = re.compile(r'^\d+\.')


def _canon_seg(value):
    """Canoniza el segmento: '3.UKL2'→'UKL2', '7.GKL++1'→'GKL+', 'MKL'→'MKL'.

    Simmix mezcla Segment ('UKL2') y Segment_Origin ('3.UKL2') según el export;
    sin canonizar, el dashboard duplica segmentos y sus filtros pierden filas.
    """
    s = _SEG_PREFIX_RE.sub('', (value or '').strip())
    if s.startswith('GKL+'):
        s = 'GKL+'
    return s


def _apply_model_lookup_patches():
    for key, row in _MODEL_LOOKUP_PATCHES.items():
        patched = row.copy()
        patched['seg'] = _canon_seg(patched.get('seg', ''))
        _MODEL_LOOKUP[key] = patched


def _load_manual_master():
    """masters/master_clasificacion_manual.csv — decisiones propias de clasificacion.

    Maxima prioridad: se carga el ULTIMO y sobreescribe cualquier otra fuente.
    Es el mecanismo para clasificar marcas/modelos nuevos sin depender de
    Simmix ni tocar codigo: una fila por (brand, model).
    Columnas: brand,model,seg,sub,hp,body,fuel_detail
    """
    fname = os.path.join(MASTERS_DIR, 'master_clasificacion_manual.csv')
    if not os.path.exists(fname):
        return 0
    n = 0
    try:
        with open(fname, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                brand = (row.get('brand') or '').strip().upper()
                model = (row.get('model') or '').strip().upper()
                if not brand or not model or brand.startswith('#'):
                    continue
                _MODEL_LOOKUP[(brand, model)] = {
                    'modelo'      : model,
                    'seg'         : _canon_seg(row.get('seg') or ''),
                    'sub'         : _focus_bucket(row.get('sub') or ''),
                    'hp'          : (row.get('hp') or 'Standard').strip(),
                    'body'        : (row.get('body') or '').strip(),
                    'fuel_detail' : (row.get('fuel_detail') or '').strip(),
                }
                n += 1
        if n:
            print(f'  -> Maestro manual: {n} clasificaciones propias aplicadas')
    except Exception as exc:
        print(f'  WARN: no se pudo cargar maestro manual: {exc}')
    return n


def _load_model_lookup_fallback():
    if not os.path.exists(MODEL_LOOKUP_FALLBACK):
        return False
    try:
        with open(MODEL_LOOKUP_FALLBACK, encoding='utf-8') as f:
            payload = json.load(f)
        for row in payload.get('rows', []):
            brand = (row.get('brand') or '').strip().upper()
            model = (row.get('model') or '').strip().upper()
            if not brand or not model:
                continue
            _MODEL_LOOKUP[(brand, model)] = {
                'modelo'      : model,
                'seg'         : _canon_seg(row.get('seg') or ''),
                'sub'         : _focus_bucket(row.get('sub') or ''),
                'hp'          : (row.get('hp') or '').strip(),
                'body'        : (row.get('body') or '').strip(),
                'fuel_detail' : (row.get('fuel_detail') or '').strip(),
            }
        return bool(_MODEL_LOOKUP)
    except Exception as exc:
        print(f'  WARN: no se pudo cargar fallback de modelos Simmix: {exc}')
        return False


def _candidate_simmix_2026_product_paths():
    paths = [os.path.join(VALIDATION_DIR, 'BBDD_2026_PRODUCTO_06_30.csv'),
             os.path.join(REPO_ROOT, 'BBDD_2026_PRODUCTO_06_30.csv')]
    downloads = os.path.join(os.path.expanduser('~'), 'Downloads')
    try:
        names = [
            n for n in os.listdir(downloads)
            if n.upper().startswith('BBDD_2026_PRODUCTO') and n.lower().endswith('.csv')
        ]
        paths.extend(os.path.join(downloads, n) for n in sorted(names, reverse=True))
    except OSError:
        pass
    return paths


def _load_simmix_2026_product_lookup():
    for fname in _candidate_simmix_2026_product_paths():
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, encoding='utf-8-sig', newline='') as f:
                reader = csv.reader(f)
                header = next(reader)
                idx = {name: header.index(name) for name in (
                    'Brand_2026', 'Model_2026', 'Fuel_2026', 'Segment_Origin_2026',
                    'SubSegmento_2026', 'High Performance_2026', 'Body Type_2026'
                )}
                loaded = False
                for raw in reader:
                    if len(raw) <= max(idx.values()):
                        continue
                    brand = raw[idx['Brand_2026']].strip().upper()
                    model = raw[idx['Model_2026']].strip().upper()
                    if not brand or not model:
                        continue
                    _MODEL_LOOKUP[(brand, model)] = {
                        'modelo': model,
                        'seg': _canon_seg(raw[idx['Segment_Origin_2026']]),
                        'sub': _focus_bucket(raw[idx['SubSegmento_2026']]),
                        'hp': 'Standard',
                        'body': raw[idx['Body Type_2026']].strip(),
                        'fuel_detail': raw[idx['Fuel_2026']].strip(),
                    }
                    loaded = True
            return loaded
        except Exception as exc:
            print(f'  WARN: no se pudo cargar BBDD 2026 producto {fname}: {exc}')
    return False


def _save_model_lookup_fallback():
    if not _MODEL_LOOKUP:
        return
    rows = []
    for (brand, model), data in sorted(_MODEL_LOOKUP.items()):
        rows.append({
            'brand': brand,
            'model': model,
            'seg': data.get('seg', ''),
            'sub': data.get('sub', ''),
            'hp': data.get('hp', ''),
            'body': data.get('body', ''),
            'fuel_detail': data.get('fuel_detail', ''),
        })
    os.makedirs(os.path.dirname(MODEL_LOOKUP_FALLBACK), exist_ok=True)
    with open(MODEL_LOOKUP_FALLBACK, 'w', encoding='utf-8') as f:
        json.dump({
            'source': 'Derived from local Simmix BBDD exports; used by GitHub Actions when BBDD files are absent.',
            'rows': rows,
        }, f, ensure_ascii=False, indent=2)


def _load_simmix_bbdd():
    global _MODEL_LOOKUP
    loaded_from_bbdd = False
    for yr in (2023, 2024, 2025):
        fname = os.path.join(VALIDATION_DIR, f'BBDD_{yr}_PRODUCTO.csv')
        if not os.path.exists(fname):
            fname = os.path.join(REPO_ROOT, f'BBDD_{yr}_PRODUCTO.csv')
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, encoding='latin-1', newline='') as f:
                reader = csv.reader(f)
                header = [h.replace(f'_{yr}','').strip() for h in next(reader)]
                for raw in reader:
                    if len(raw) < len(header): continue
                    row = dict(zip(header, raw))
                    brand = (row.get('Brand') or '').strip().upper()
                    model = (row.get('Model') or '').strip().upper()
                    if not brand or not model: continue
                    loaded_from_bbdd = True
                    key = (brand, model)
                    if key not in _MODEL_LOOKUP:
                        _MODEL_LOOKUP[key] = {
                            'modelo'      : model,
                            'seg'         : _canon_seg(row.get('Segment') or ''),
                            'sub'         : _focus_bucket(row.get('SubSegmento') or ''),
                            'hp'          : (row.get('High Performance') or '').strip(),
                            'body'        : (row.get('Body Type') or '').strip(),
                            'fuel_detail' : (row.get('Fuel') or '').strip(),
                        }
        except Exception:
            pass
    if loaded_from_bbdd:
        _load_simmix_2026_product_lookup()
        _apply_model_lookup_patches()
        _load_manual_master()
        _save_model_lookup_fallback()
    elif not _MODEL_LOOKUP:
        _load_model_lookup_fallback()
        _load_simmix_2026_product_lookup()
        _apply_model_lookup_patches()
        _load_manual_master()


_PROP_FUEL_NAME = {
    '0': 'Gasolina', '1': 'Diesel', '2': 'Electrico',
    '3': 'Hidrogeno', '4': 'Hidrogeno',
    '6': 'Gas Licuado con petroleo (GLP)',
    '7': 'Gas natural comprimido (GNC)',
}


def get_fuel_detail_from_dgt(line_s):
    prop = line_s[F_PROPULSION[0]:F_PROPULSION[1]].strip()
    cat  = line_s[F_CAT_ELECTRICO[0]:F_CAT_ELECTRICO[1]].strip().upper()
    if cat in ('BEV', 'REEV') or prop == '2':
        return 'Electrico'
    if cat == 'PHEV':
        return 'Diesel/Electrico Enchufable' if prop == '1' else 'Gasolina/Electrico Enchufable'
    return _PROP_FUEL_NAME.get(prop, 'Gasolina')

def lookup_enrichment(marca_raw, raw_modelo_field, raw_line=None):
    """Devuelve (modelo_canon, seg, sub, hp, body, fuel_detail) o 6x ''."""
    sbrand = _BRAND_NORM.get(marca_raw, marca_raw)
    # L1: exact match en _ENRICHMENT (version_dgt exacto → modelo)
    enr_key = (sbrand, raw_modelo_field.strip().upper())
    if enr_key in _ENRICHMENT:
        enr = _ENRICHMENT[enr_key]
        return enr['modelo'], enr['seg'], enr['sub'], enr['hp'], enr['body'], enr.get('fuel_detail', '')
    # L2: candidates por patrones sobre F_MODELO
    for cand in _model_candidates(sbrand, raw_modelo_field):
        r = _MODEL_LOOKUP.get(cand)
        if r:
            return r['modelo'], r['seg'], r['sub'], r['hp'], r['body'], r.get('fuel_detail','')
    # Variante EEA como ultimo recurso. La variante tecnica no siempre
    # identifica el modelo comercial, asi que no debe pisar el texto DGT.
    if raw_line is not None and _EEA_LOOKUP:
        va = raw_line[F_VARIANTE_ITV[0]:F_VARIANTE_ITV[1]].strip().upper()
        if va:
            eea_modelo = _EEA_LOOKUP.get((sbrand, va))
            if eea_modelo:
                meta = _MODEL_LOOKUP.get((sbrand, eea_modelo), {})
                if not meta:
                    for cand_brand, cand_model in _model_candidates(sbrand, eea_modelo):
                        meta = _MODEL_LOOKUP.get((cand_brand, cand_model), {})
                        if meta:
                            eea_modelo = cand_model
                            break
                return (eea_modelo,
                        meta.get('seg', ''), meta.get('sub', ''),
                        meta.get('hp', ''),  meta.get('body', ''),
                        meta.get('fuel_detail', ''))
    return '', '', 'REST', '', '', ''


def classify_high_performance(marca, modelo_raw, lookup_hp=''):
    m = marca.strip().upper()
    mo = re.sub(r'\s+', ' ', modelo_raw.strip().upper())


    if m == 'BMW':
        # Full M cars. "M Sport" is a trim package and must remain Standard.
        if (re.match(r'^M[23458]\b', mo) or mo.startswith('XM') or
                re.match(r'^X[3456]\s+M(?:\s+COMPETITION|\s*$)', mo) or
                mo.startswith('M COMPETICION')):
            return 'M'


        # M Performance Automobiles: Mxxi/Mxxd, i M50/M60/M70, X M35/M40/M50/M60, Z4 M40.
        if (re.match(r'^M(?:135|140|235|240|340|440|550|760|850)[A-Z]*\b', mo) or
                re.match(r'^I[457X]\s+M(50|60|70)\b', mo) or
                re.match(r'^X[12]\s+M35', mo) or
                re.match(r'^X[34]\s+M(40|50)', mo) or
                re.match(r'^X[567]\s+M(50|60)', mo) or
                re.match(r'^Z4\s+M40', mo)):
            return 'M Performance'
        return 'Standard'


    if m == 'MINI':
        return 'JCW' if ('JCW' in mo or 'JOHN COOPER WORKS' in mo or 'JHON COOPER WORKS' in mo) else 'Standard'


    if m in ('MERCEDES-BENZ','MERCEDES','MERCEDES BENZ','MERCEDES-AMG'):
        if 'AMG' not in mo:
            return 'Standard'
        if (re.search(r'AMG\s+(?:A|C|CLA|GLA)\s*45', mo) or
                re.search(r'AMG\s+(?:C|G|GLC|GLE|GLS|GT)\s*63', mo) or
                re.search(r'AMG\s+SL\s*55', mo)):
            return 'M'
        return 'M Performance'


    if m == 'AUDI':
        audi = re.sub(r'^AUDI\s+', '', mo)
        if audi.startswith('RS') or audi.startswith('R8'):
            return 'M'
        if re.match(r'^(?:S[0-9]|SQ[0-9]|S\s+E-TRON)', audi):
            return 'M Performance'
        return lookup_hp or 'Standard'


    if m == 'PORSCHE':
        if ('TURBO' in mo or 'GT3' in mo or 'GT4 RS' in mo or
                'SPYDER RS' in mo or 'TURBO GT' in mo):
            return 'M'
        if ('GTS' in mo or re.search(r'\b4S\b', mo) or
                re.search(r'\bCARRERA\s+(?:4)?S\b', mo) or
                re.search(r'\bTARGA\s+4S\b', mo) or
                re.search(r'\b(?:CAYENNE|MACAN)\s+S\b', mo) or
                'E-HYBRID S' in mo or 'S E-HYBRID' in mo):
            return 'M Performance'
        return 'Standard'


    if not lookup_hp or lookup_hp == 'Standard':
        return lookup_hp or 'Standard'
    return lookup_hp




# Reglas de campa
# 28169 Venturada = campa fabricante (Corporate) excepto Toyota/Lexus que van a alquiler (RAC)
# 28093 Navacerrada = deposito RAC (Skoda ya no va como Corporate)
# 28022 Boadilla = campa fabricante PSA (Corporate)
CAMPA_MUNICIPIOS_ALL = {'28169'}    # Venturada
CAMPA_VENTURADA_RAC  = {'TOYOTA', 'LEXUS', 'AUDI', 'BMW'}   # estas marcas en Venturada = RAC
CAMPA_MUNICIPIOS_PSA = {'28022'}    # Boadilla
CAMPA_PSA_MARCAS     = {'OPEL','PEUGEOT','CITROEN','DS','ALFA ROMEO','RENAULT','JEEP'}
CAMPA_PEUGEOT_RS_MUN = {'38038','35025'}


# Municipios concesionario BMW/Volvo: registros B00+D aquí = Km.0 → Corporate
# Simmix clasifica como Corporate los B00+D cuyo CP coincide con el de un concesionario.
# Al no tener CP en DGT usamos el municipio INE (PPMMM).
# Solo incluimos poblaciones pequeñas/medianas (<50k hab) donde toda la actividad es dealer.
# Las grandes ciudades (Madrid, Barcelona, Valencia…) se excluyen: hay compradores privados reales.
# Códigos verificados via Wikipedia (INE PPMMM).
DEALER_MUN_BMW = {
    # Pequeñas (<5k) — prácticamente 100% Km.0
    '28151',  # Torrelaguna (343 BMW Km.0/36m en Simmix)
    '28128',  # Rozas de Puerto Real (145)
    '30040',  # Ulea (481)
    '17093',  # Llers (249)
    '07019',  # Escorca (176)
    '46092',  # Castielfabib (172)
    '28173',  # Villamanrique de Tajo (129)
    '28090',  # Moralzarzal (113)
    '43034',  # Bráfim (93)
    '28036',  # Casarrubuelos (77)
    '03111',  # Redován (64)
    '03112',  # Relleu (61)
    '28069',  # La Hiruela (61)
    '29083',  # Riogordo (51)
    '03119',  # Sant Joan d'Alacant (49)
    '45203',  # Yuncler (46)
    '28093',  # Navacerrada (46)
    '11008',  # Los Barrios (44)
    '28002',  # Ajalvir (43) — también Volvo dealer
    '03030',  # Benidoleig (40)
    '43043',  # El Catllar (31)
    # Medianas (<50k) — zona industrial/dealer conocida
    '48902',  # Erandio ~25k (429)
    '15058',  # Oleiros ~35k (127)
    '24142',  # San Andrés del Rabanedo ~31k (42)
    '08178',  # Rajadell ~600 (13 BMW, mayormente Volvo pero incluir)
    '20063',  # Oiartzun ~9k (134)
    '31088',  # Noain-Valle de Elorz ~3k (12 BMW)
    '36024',  # Lalín ~20k (101)
    '39016',  # Camargo ~32k (100)
    '46102',  # Quart de Poblet ~25k (59)
}


DEALER_MUN_VOLVO = {
    # Pequeñas
    '28151',  # Torrelaguna (883 Volvo Km.0/36m)
    '28128',  # Rozas de Puerto Real (689)
    '20040',  # Hernani ~20k (124)
    '50224',  # Retascón ~50 hab (100)
    '45021',  # Borox ~2k (77)
    '37362',  # Villares de la Reina ~6k (43)
    '28002',  # Ajalvir ~3k (43)
    '31088',  # Noain-Valle de Elorz (90)
    '08178',  # Rajadell (195)
    # Medianas
    '48902',  # Erandio ~25k (306)
    '15058',  # Oleiros ~35k (138)
    '24142',  # San Andrés del Rabanedo (178)
    '08073',  # Cornellà de Llobregat ~87k (143) — zona industrial Volvo
}


# Dealer municipalities by brand for B00+D Km.0 classification.
# Built from Simmix Corporate Km.0 / Automatr / Excedentes by brand and municipality.
# Large or ambiguous cities are intentionally excluded.
DEALER_MUN = {
    'BMW': DEALER_MUN_BMW,
    'VOLVO': DEALER_MUN_VOLVO,
    'ALFA ROMEO': {'08002', '28069', '28125'},
    'AUDI': {'03119', '08002', '08027', '12103', '15058', '24142', '25007', '28002', '28125', '28128', '28151', '37362', '43059', '45122', '46102'},
    'CITROEN': {'03030', '03071', '03112', '07038', '08002', '08027', '08178', '12103', '25007', '28002', '28027', '28069', '28090', '28107', '28125', '28128', '28151', '29066', '29074', '43043', '45021', '45045'},
    'CUPRA': {'08002', '13029', '25007', '28002', '28036', '28046', '28121', '28151', '29074', '48036'},
    'DACIA': {'03030', '12103', '28090', '28107'},
    'DS': {'28069', '28125', '45021'},
    'FIAT': {'03030', '08002', '08178', '12103', '28027', '28069', '28090', '28107', '28128', '28151', '28153', '29066', '29074', '35018', '41083', '45021'},
    'FORD': {'03030', '03119', '08002', '08178', '28046', '28069', '28090', '28107', '28125', '28128', '29066', '29074', '43059'},
    'HONDA': {'08002', '08178', '29074'},
    'HYUNDAI': {'03030', '04052', '08178', '09434', '24142', '27049', '28093', '28107', '28125', '28128', '28151', '28173', '29066', '31109', '43059', '43163', '45122', '48902', '50224'},
    'IVECO': {'28125', '28151', '29074', '46102'},
    'JEEP': {'03030', '08178', '12103', '28069', '28125', '28151', '28153', '29074', '41083', '45021'},
    'KIA': {'08002', '08178', '20063', '28090', '28125', '46092', '48902'},
    'LEXUS': {'29074'},
    'MAZDA': {'08002', '08178', '25007', '28002', '28069', '28090', '28125'},
    'MERCEDES': {'11003', '12103', '15058', '20058', '25007', '26084', '27049', '28069', '28090', '28093', '28099', '28151', '41083', '46092'},
    'MERCEDES-BENZ': {'11003', '12103', '15058', '20058', '25007', '26084', '27049', '28069', '28090', '28093', '28099', '28151', '41083', '46092'},
    'MG': {'03030', '08002', '28002', '28069', '46092'},
    'MINI': {'07019', '28026', '28128', '30040'},
    'MITSUBISHI': {'45021'},
    'NISSAN': {'03030', '08002', '08178', '28046', '28090', '28107', '28128', '29074', '29083'},
    'OPEL': {'03030', '03112', '08002', '08178', '12103', '20058', '28002', '28069', '28128', '28151', '29066', '29074', '43043', '45021'},
    'PEUGEOT': {'03030', '03112', '08002', '08027', '08178', '12103', '15058', '20063', '28090', '28125', '28151', '41083', '43043', '45021'},
    'RENAULT': {'03030', '07019', '08178', '28107', '28128', '29074', '45021'},
    'SEAT': {'04052', '12103', '13029', '28002', '28046', '28107', '29074', '35018', '45122'},
    # Skoda already overclassifies Corporate in the current delta, so do not add Km.0 dealer rules.
    'SSANGYONG': {'45021'},
    'SUBARU': {'45021'},
    'SUZUKI': {'08178'},
    'TOYOTA': {'12103', '20058', '28090', '28107', '28125', '28128', '29074', '50224'},
    'VOLKSWAGEN': {'08002', '08106', '12103', '24148', '28151', '29074', '30031', '31193'},
    'VOLKSWAGEN AG': {'08002', '08106', '12103', '24148', '28151', '29074', '30031', '31193'},
    'VOLKSWAGEN V W': {'08002', '08106', '12103', '24148', '28151', '29074', '30031', '31193'},
}


# High-signal small dealer municipalities applied across brands.
# Excludes campas and larger ambiguous cities.
DEALER_MUN_ALL = {
    '03030',  # Benidoleig
    '03111',  # Redovan
    '03112',  # Relleu
    '07019',  # Escorca
    '08002',  # Aguilar de Segarra
    '08027',  # Les Cabanyes
    '08178',  # Rajadell
    '09434',  # Villagonzalo Pedernales
    '11003',  # Algar
    '11008',  # Los Barrios
    '12103',  # Sarratella
    '13029',  # Canada de Calatrava
    '17093',  # Llers
    '20058',  # Olaberria
    '20063',  # Oiartzun
    '24148',  # San Justo de la Vega
    '25007',  # Albatarrec
    '27049',  # Portomarin
    '28002',  # Ajalvir
    '28027',  # Buitrago del Lozoya
    '28036',  # Casarrubuelos
    '28046',  # Collado Mediano
    '28069',  # La Hiruela
    '28090',  # Moralzarzal
    '28093',  # Navacerrada
    '28099',  # Navas del Rey
    '28107',  # Patones
    '28121',  # Reduena
    '28125',  # Robledo de Chavela
    '28128',  # Rozas de Puerto Real
    '28151',  # Torrelaguna
    '28153',  # Torremocha de Jarama
    '28173',  # Villamanrique de Tajo
    '29066',  # Macharaviaya
    '29074',  # Montejaque
    '29083',  # Riogordo
    '30031',  # Ojos
    '30040',  # Ulea
    '31088',  # Noain-Valle de Elorz
    '31193',  # Cendea de Olza
    '35018',  # San Bartolome
    '37362',  # Villares de la Reina
    '41083',  # El Ronquillo
    '43034',  # Brafim
    '43043',  # El Catllar
    '43059',  # Figuerola del Camp
    '45021',  # Borox
    '45122',  # Olias del Rey
    '45203',  # Yuncler
    '46092',  # Castielfabib
    '48036',  # Galdakao
    '49227',  # Valcabado
    '50224',  # Retascon
}
DEALER_MUN_ALL_EXCLUDED_BRANDS = {'SKODA'}
NO_DEALER_MUN = set()


# Statistical Km.0 fallback for B00+D records that are still Private after the
# municipality dealer rules. Rates are calibrated on 2023-2025 residual
# Corporate shortfall divided by remaining B00+D pool by brand.
# Brands with scope/alias gaps that cannot be explained by B00+D are excluded.
KM0_BRAND_FALLBACK_RATE = {
    'ALFA ROMEO': 0.21581197,
    'AUDI': 0.02340209,
    'CITROEN': 0.08022648,
    'CUPRA': 0.00163557,
    'DACIA': 0.00467283,
    'DFSK': 0.14683153,
    'EVO': 0.16622691,
    'FIAT': 0.25975855,
    'FORD': 0.09385113,
    'JEEP': 0.05224577,
    'MERCEDES-BENZ': 0.02743966,
    'MINI': 0.00594943,
    'MITSUBISHI': 0.07677709,
    'NISSAN': 0.01341773,
    'OPEL': 0.14842819,
    'PEUGEOT': 0.05527399,
    'RENAULT': 0.05734340,
    'SEAT': 0.02909499,
    'SMART': 0.05047049,
    'SSANGYONG': 0.07281879,
    'TOYOTA': 0.00904969,
    'VOLVO': 0.01861878,
}


# Residual scope calibration by brand/channel, learned from Simmix exports
# after deterministic brand/model/channel rules and Km.0 fallback.
# This handles small remaining scope differences between the DGT microdata and
# Simmix business rules while keeping the adjustment tied to source exports.
CHANNEL_SCOPE_FACTOR = {
    ('AUDI', 'Corporate'): 1.0303030303,  # recalibrado jul-2026: S=306, D=297 → 306/297
    ('AUDI', 'Private'): 0.9536082474,    # recalibrado jul-2026: S=185, D=194 → 185/194
    ('AUDI', 'RAC'): 1.0000000000,        # RAC cuadra exacto
    ('BMW', 'Corporate'): 0.9971098267,
    ('BMW', 'Private'): 0.9895104896,
    ('BMW', 'RAC'): 1.0012953369,
    ('MINI', 'Corporate'): 0.9930362118,
    ('MINI', 'Private'): 1.0011111112,
    ('MINI', 'RAC'): 0.9973118281,
    ('MERCEDES', 'Corporate'): 1.0216586450,
    ('MERCEDES', 'Private'): 1.0005296611,
    ('MERCEDES', 'RAC'): 1.0173891130,
    ('BYD', 'Corporate'): 0.96574882,
    # CITROEN/FIAT/FORD/OPEL/RENAULT Private, IVECO, MAN e ISUZU eliminados
    # 2026-07-02: compensaban estadísticamente los carrozados/camperizados y
    # los N2 derivados de furgoneta; ahora lo cubren las reglas deterministas
    # reassign_carrocero() y n2_van_target(). Mantenerlos duplicaría.
    ('CITROEN', 'RAC'): 0.99078595,
    ('DACIA', 'Private'): 1.00758472,
    # DS eliminado 2026-07-02: el gap 2023-25 era de alias (DS AUTOMOBILES),
    # ya resuelto. Con factor, H1 2026 sobreestimaba +843 uds; sin factor,
    # delta -4/-2/-2 por canal vs Simmix.
    ('EVO', 'Private'): 2.17007874,
    ('FIAT', 'RAC'): 1.01984023,
    ('FORD', 'RAC'): 0.90588365,
    ('HYUNDAI', 'RAC'): 0.99352733,
    ('KIA', 'Corporate'): 0.99571533,
    ('LAND ROVER', 'Corporate'): 0.9970238096,
    ('LAND ROVER', 'Private'): 0.9659090910,
    ('LAND ROVER', 'RAC'): 1.0106382980,
    # LEAPMOTOR eliminado 2026-07-02: el factor 2023-25 borraba ~1.050 uds
    # reales en H1 2026; sin factor, delta -29/+42/+1 por canal vs Simmix.
    ('LEXUS', 'Corporate'): 0.9924924926,
    ('LEXUS', 'Private'): 1.0009041592,
    ('LEXUS', 'RAC'): 0.9875000001,
    ('MERCEDES-V', 'Corporate'): 1.0138121548,
    ('MERCEDES-V', 'Private'): 1.1363636365,
    ('MERCEDES-V', 'RAC'): 0.9901574804,
    ('MG', 'Corporate'): 0.94479441,
    ('MG', 'Private'): 1.00496327,
    ('NISSAN', 'Private'): 1.01034865,
    ('NISSAN', 'RAC'): 0.92680608,
    ('OPEL', 'RAC'): 0.95423341,
    ('PEUGEOT', 'Private'): 1.07181872,
    ('PEUGEOT', 'RAC'): 1.01310178,
    ('PORSCHE', 'Corporate'): 0.9779874215,
    ('PORSCHE', 'Private'): 1.0035211269,
    ('PORSCHE', 'RAC'): 1.1170212767,
    ('RENAULT', 'RAC'): 0.97824095,
    ('SEAT', 'Private'): 1.03028465,
    ('SEAT', 'RAC'): 0.94677806,
    ('SKODA', 'Corporate'): 0.97607462,
    ('SKODA', 'RAC'): 1.05566792,
    ('SSANGYONG', 'Private'): 1.07851385,
    ('SUZUKI', 'Corporate'): 0.91580977,
    ('SUZUKI', 'RAC'): 1.14340263,
    ('TESLA', 'Corporate'): 0.8838383839,
    ('TESLA', 'Private'): 1.0255102042,
    ('TESLA', 'RAC'): 0.9500000001,
    ('TOYOTA', 'Private'): 1.01480633,
    ('TOYOTA', 'RAC'): 0.98402966,
    ('VOLKSWAGEN', 'Corporate'): 0.99806854,
    ('VOLKSWAGEN', 'Private'): 1.00295073,
    ('VOLKSWAGEN', 'RAC'): 1.06340502,
    ('VOLVO', 'Corporate'): 0.9877250410,
    ('VOLVO', 'Private'): 1.0079365080,
    ('VOLVO', 'RAC'): 0.9989247313,
}


# 2026 Simmix residuals are not always distributed evenly across Focus/Rest.
# Mercedes is the relevant case: most residual scope appears in commercial Rest
# models, so a brand+channel factor incorrectly inflates passenger Focus.
CHANNEL_SUBSEG_SCOPE_FACTOR = {
    ('MERCEDES', 'Corporate', 'FOCUS SEGMENT'): 1.0180512627,
    ('MERCEDES', 'Corporate', 'REST'): 1.1226966292,
    ('MERCEDES', 'Private', 'FOCUS SEGMENT'): 0.9532303901,
    ('MERCEDES', 'Private', 'REST'): 1.2984870968,
    ('MERCEDES', 'RAC', 'FOCUS SEGMENT'): 1.0035294118,
    ('MERCEDES', 'RAC', 'REST'): 1.0987903226,
    ('LEXUS', 'Corporate', 'FOCUS SEGMENT'): 0.9927686217,
    ('LEXUS', 'Corporate', 'REST'): 0.7501000000,
    ('LEXUS', 'Private', 'FOCUS SEGMENT'): 1.0012468174,
    ('LEXUS', 'Private', 'REST'): 0.2500000000,
    ('LEXUS', 'RAC', 'FOCUS SEGMENT'): 1.0000000000,
    ('VOLVO', 'Corporate', 'FOCUS SEGMENT'): 1.0015505367,
    ('VOLVO', 'Private', 'FOCUS SEGMENT'): 0.9864429752,
    ('VOLVO', 'Private', 'REST'): 0.0000000000,
    ('VOLVO', 'RAC', 'FOCUS SEGMENT'): 1.0000000000,
}


ALERT_DRIFT_START_YEAR = 2026
ALERT_MIN_BASELINE_COUNT = 50
ALERT_DRIFT_ABS = 250
ALERT_DRIFT_REL = 0.25
ALERT_DRIFT_CRITICAL_REL = 0.50
ALERT_NEW_BRAND_COUNT = 250
ALERT_KM0_FALLBACK_MOVED = 100
ALERT_CARROCERO_UNMAPPED = 25


def km0_rate_brand(marca):
    m = marca.strip().upper()
    if m in ('MERCEDES', 'MERCEDES BENZ', 'MERCEDES-BENZ', 'MERCEDES-AMG'):
        return 'MERCEDES-BENZ'
    if m in ('VOLKSWAGEN', 'VOLKSWAGEN AG', 'VOLKSWAGEN V W'):
        return 'VOLKSWAGEN'
    if m in ('LYNK&CO', 'LYNK & CO'):
        return 'LYNK & CO'
    return m


def apply_scope_calibration(counts):
    calibrated = collections.Counter()
    for (marca, canal), n in counts.items():
        factor = CHANNEL_SCOPE_FACTOR.get((marca, canal))
        if factor is None:
            calibrated[(marca, canal)] += n
        else:
            calibrated[(marca, canal)] += max(0, int(round(n * factor)))
    return calibrated


def scope_group_for_fuel_key(key):
    if len(key) == 9:
        marca, canal, sub = key[0], key[2], key[6]
    elif len(key) == 8:
        marca, canal, sub = key[0], key[2], key[5]
    else:
        marca = key[0]
        canal = key[1]
        sub = ''
    bucket = _focus_bucket(sub)
    detailed = (marca, canal, bucket)
    if detailed in CHANNEL_SUBSEG_SCOPE_FACTOR:
        return detailed
    return (marca, canal)


def allocate_calibrated_fuel(fuel_counts, calibrated, raw_totals):
    grouped = collections.defaultdict(list)
    for key, n in fuel_counts.items():
        grouped[scope_group_for_fuel_key(key)].append((key, n))


    out = collections.Counter()
    for group, rows in grouped.items():
        raw = sum(n for _, n in rows)
        factor = CHANNEL_SUBSEG_SCOPE_FACTOR.get(group)
        if factor is None:
            target = calibrated.get(group, raw)
        else:
            target = max(0, int(round(raw * factor)))
        if raw <= 0 or target <= 0:
            continue


        allocations = []
        assigned = 0
        for key, n in rows:
            ideal = n * target / raw
            base = int(ideal)
            assigned += base
            allocations.append((ideal - base, repr(key), key, base))


        remaining = target - assigned
        allocations.sort(key=lambda item: (-item[0], item[1]))
        bonus_keys = {key for _, _, key, _ in allocations[:remaining]} if remaining > 0 else set()


        for _, _, key, base in allocations:
            out[key] += base + (1 if key in bonus_keys else 0)
    return out


def make_alert(severity, kind, marca='', canal='', metric='', value='', threshold='', detail=''):
    return {
        'severity': severity,
        'kind': kind,
        'marca': marca,
        'canal': canal,
        'metric': metric,
        'value': value,
        'threshold': threshold,
        'detail': detail,
    }


def iter_output_rows(before_year=None, same_month=None, exclude_yyyymm=None):
    import csv as csv_mod
    prefix = 'dgt_canal_'
    suffix = '.csv'
    for name in os.listdir(OUT_DIR):
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        yyyymm = name[len(prefix):-len(suffix)]
        if len(yyyymm) != 6 or not yyyymm.isdigit():
            continue
        if exclude_yyyymm and yyyymm == exclude_yyyymm:
            continue
        if before_year is not None and int(yyyymm[:4]) >= before_year:
            continue
        if same_month is not None and yyyymm[4:] != same_month:
            continue
        path = os.path.join(OUT_DIR, name)
        try:
            agg = collections.Counter()
            with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                for row in csv_mod.DictReader(f):
                    try:
                        n = int(float(row.get('count', 0)))
                    except (TypeError, ValueError):
                        continue
                    agg[(row.get('marca','').strip().upper(), row.get('canal','').strip())] += n
            for (marca, canal), n in agg.items():
                yield yyyymm, marca, canal, n
        except OSError:
            continue


def add_unknown_brand_alerts(yyyymm, counts, alerts):
    year = int(yyyymm[:4])
    if year < ALERT_DRIFT_START_YEAR:
        return
    known = set()
    for _, marca, _, _ in iter_output_rows(before_year=year, exclude_yyyymm=yyyymm):
        if marca:
            known.add(marca)
    brand_counts = collections.Counter()
    for (marca, _), n in counts.items():
        brand_counts[marca] += n
    for marca, n in sorted(brand_counts.items()):
        if n >= ALERT_NEW_BRAND_COUNT and marca not in known:
            alerts.append(make_alert(
                'WARN',
                'NEW_BRAND',
                marca=marca,
                metric='monthly_count',
                value=n,
                threshold=ALERT_NEW_BRAND_COUNT,
                detail='Marca con volumen relevante no vista en outputs historicos previos',
            ))


def add_drift_alerts(yyyymm, counts, alerts):
    year = int(yyyymm[:4])
    if year < ALERT_DRIFT_START_YEAR:
        return
    baseline = collections.defaultdict(list)
    for _, marca, canal, n in iter_output_rows(before_year=year, same_month=yyyymm[4:], exclude_yyyymm=yyyymm):
        if marca and canal:
            baseline[(marca, canal)].append(n)
    if not baseline:
        return
    keys = set(baseline) | set(counts)
    for key in sorted(keys):
        values = baseline.get(key, [])
        if len(values) < 2:
            continue
        marca, canal = key
        current = counts.get(key, 0)
        avg = sum(values) / float(len(values))
        if avg < ALERT_MIN_BASELINE_COUNT:
            continue
        delta = current - avg
        rel = delta / avg
        if abs(delta) < ALERT_DRIFT_ABS or abs(rel) < ALERT_DRIFT_REL:
            continue
        severity = 'CRITICAL' if abs(rel) >= ALERT_DRIFT_CRITICAL_REL else 'WARN'
        alerts.append(make_alert(
            severity,
            'CHANNEL_DRIFT',
            marca=marca,
            canal=canal,
            metric='count_vs_same_month_history',
            value=int(round(delta)),
            threshold='+/-{} and +/-{:.0%}'.format(ALERT_DRIFT_ABS, ALERT_DRIFT_REL),
            detail='actual={}; media_mismo_mes={:.1f}; historico={}; rel={:+.1%}'.format(
                current, avg, ','.join(str(v) for v in values), rel
            ),
        ))


def normalize_marca(marca, modelo=''):
    m = marca.strip().upper()
    mo = modelo.strip().upper()
    m = _BRAND_NORM.get(m, m)
    if m == 'SPORTEQUIPE' and ('ICH-X' in mo or mo.startswith('X K')):
        return 'ICH-X'
    if m in ('MERCEDES', 'MERCEDES BENZ', 'MERCEDES-BENZ', 'MERCEDES-AMG'):
        # Mercedes V-Class derivatives → Mercedes-V scope (separate brand in Simmix)
        # DGT raw F_MODELO: 'V 220 D...', 'VITO 116...', 'EQV 300...', 'MARCO POLO'
        if 'VITO' in mo:
            return 'MERCEDES-V'
        # T-Class and commercial vans → outside Simmix scope (exclude)
        # DGT raw F_MODELO: 'T 180 D...', 'CITAN 110...', 'ECITAN...', 'EQT...', 'SPRINTER...'
    return m


def get_fuel_type_code(line_s):
    prop = line_s[F_PROPULSION[0]:F_PROPULSION[1]].strip()
    cat  = line_s[F_CAT_ELECTRICO[0]:F_CAT_ELECTRICO[1]].strip().upper()
    if cat in ('BEV', 'REEV') or prop == '2':
        return 'BEV'
    if cat == 'PHEV':
        return 'PHEV'
    return 'ICE'


def classify(servicio, persona, renting, mun, marca):
    s  = servicio.strip()
    m  = marca.strip().upper()
    r  = renting.strip()
    mu = mun.strip()
    p  = persona.strip()


    if s == 'A01':
        if mu in CAMPA_MUNICIPIOS_ALL:
            if m in CAMPA_VENTURADA_RAC:
                return 'RAC'
            return 'Corporate'
        if mu in CAMPA_MUNICIPIOS_PSA and m in CAMPA_PSA_MARCAS:
            return 'Corporate'
        if m == 'PEUGEOT' and r == 'S' and mu in CAMPA_PEUGEOT_RS_MUN:
            return 'Corporate'
        return 'RAC'


    if s == 'B00':
        if p == 'X': return 'Corporate'
        # Km.0 en municipio concesionario: B00+D matriculado en CP de dealer → Corporate
        # (Simmix clasifica así; en DGT solo tenemos municipio, no CP)
        if mu in DEALER_MUN.get(m, NO_DEALER_MUN): return 'Corporate'
        if m not in DEALER_MUN_ALL_EXCLUDED_BRANDS and mu in DEALER_MUN_ALL: return 'Corporate'
        return 'Private'


    if s in ('A18', 'B18'):
        return 'Corporate'
    if s in ('B17', 'B19', 'B21', 'A04', 'A07', 'A03'):
        return 'Private'
    if s in ('A02', 'A05', 'A09', 'A10', 'A11', 'A12', 'A13', 'A14', 'A15', 'A16', 'A20'):
        return 'Corporate'


    return 'Corporate' if p == 'X' else 'Private'




def es_turismo_o_furgoneta(line_s):
    """True si turismo (plazas>=4) o furgoneta ligera N1 (plazas=2-3, MMA 700-3500 kg).
    Excluye motos (MMA<700), camiones pesados (MMA>3500) y trailers (plazas=0)."""
    cat_homol = line_s[F_HOMOLOGACION[0]:F_HOMOLOGACION[1]].strip().upper()
    if cat_homol:
        return cat_homol.startswith('M1') or cat_homol.startswith('N1')


    plazas_s = line_s[F_PLAZAS[0]:F_PLAZAS[1]].strip()
    plazas = int(plazas_s) if plazas_s.isdigit() else 0


    if plazas >= 4:
        return True  # turismo / SUV / MPV: siempre incluir


    if plazas in (2, 3):
        try:
            mma = int(line_s[F_MMA[0]:F_MMA[1]].strip())
        except (ValueError, IndexError):
            return False
        return 700 <= mma <= 3500  # furgoneta ligera N1


    return False  # plazas=0 (trailer), plazas=1 (moto solo-seat)


# ---------------------------------------------------------------------------
# VIN10 deduplication index
# Stores the first 10 useful chars of the bastidor for every N/U=N vehicle that
# passes scope.  Used to decide whether a tram=B record in the 61-730 day window
# is a genuine first-time registration (VIN not seen before → include) or a
# finalisation of an already-counted provisional plate (VIN in index → exclude).
# ---------------------------------------------------------------------------
_VIN10_NU_N_INDEX: set = set()


def _load_vin10_index():
    """Load the persisted VIN10 index into the global set at process start."""
    global _VIN10_NU_N_INDEX
    if os.path.exists(VIN10_INDEX_FILE):
        with open(VIN10_INDEX_FILE, 'r', encoding='ascii') as _f:
            _VIN10_NU_N_INDEX = {_l.strip() for _l in _f if _l.strip()}
        print('  -> vin10 index cargado: {:,} entradas'.format(len(_VIN10_NU_N_INDEX)))
    else:
        _VIN10_NU_N_INDEX = set()
        print('  -> vin10 index: fichero no encontrado, empezando vacío')


def _save_vin10_index():
    """Persist the in-memory VIN10 index to disk."""
    with open(VIN10_INDEX_FILE, 'w', encoding='ascii') as _f:
        for _v in sorted(_VIN10_NU_N_INDEX):
            _f.write(_v + '\n')
    print('  -> vin10 index guardado: {:,} entradas'.format(len(_VIN10_NU_N_INDEX)))


def _is_tram_b_extended_window(line_s):
    """True for non-BMW tram=B records with fec_prim between 61 and 730 days
    before fec_mat.  These are candidates for VIN-dedup inclusion in
    process_lines(); the final decision is made there against _VIN10_NU_N_INDEX.
    """
    if line_s[F_CLAVE_TRAMITE[0]:F_CLAVE_TRAMITE[1]].strip() != 'B':
        return False
    if line_s[F_NUEVO_USADO[0]:F_NUEVO_USADO[1]].strip() != 'U':
        return False
    _marca_raw = line_s[F_MARCA[0]:F_MARCA[1]]
    _modelo_raw = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
    if normalize_marca(_marca_raw, _modelo_raw) == 'BMW':
        return False
    fec_mat  = _parse_dgt_date(line_s[F_FEC_MATRICULA[0]:F_FEC_MATRICULA[1]])
    fec_prim = _parse_dgt_date(
        line_s[F_FEC_PRIM_MATRICULACION[0]:F_FEC_PRIM_MATRICULACION[1]]
    )
    if not fec_mat or not fec_prim:
        return False
    days = (fec_mat - fec_prim).days
    return TRAM_B_MAX_PROVISIONAL_DAYS < days <= TRAM_B_VIN_DEDUP_MAX_DAYS


def _is_tram_b_extended_allowlisted(line_s):
    """Exact allowlist for tram=B records absent from DGT's prior N/U=N feed."""
    if line_s[F_CLAVE_TRAMITE[0]:F_CLAVE_TRAMITE[1]].strip() != 'B':
        return False
    if line_s[F_NUEVO_USADO[0]:F_NUEVO_USADO[1]].strip() != 'U':
        return False
    _marca_raw = line_s[F_MARCA[0]:F_MARCA[1]]
    _modelo_raw = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
    if normalize_marca(_marca_raw, _modelo_raw) == 'BMW':
        return False
    fec_mat_raw = line_s[F_FEC_MATRICULA[0]:F_FEC_MATRICULA[1]]
    fec_prim_raw = line_s[F_FEC_PRIM_MATRICULACION[0]:F_FEC_PRIM_MATRICULACION[1]]
    vin10 = visible_dgt_vin10(line_s)
    if (vin10, fec_mat_raw, fec_prim_raw) not in TRAM_B_EXTENDED_ALLOWLIST:
        return False
    fec_mat = _parse_dgt_date(fec_mat_raw)
    fec_prim = _parse_dgt_date(fec_prim_raw)
    if not fec_mat or not fec_prim:
        return False
    days = (fec_mat - fec_prim).days
    return TRAM_B_MAX_PROVISIONAL_DAYS < days <= 730


def passes_dgt_scope_filters(line_s):
    """Criterios base de conteo DGT/Simmix antes de clasificar canal."""
    if line_s[F_CLASE_MAT[0]:F_CLASE_MAT[1]].strip() != '0':
        return False
    if (line_s[F_NUEVO_USADO[0]:F_NUEVO_USADO[1]].strip() != 'N'
            and not is_recent_temp_to_final_used(line_s)
            and not _is_tram_b_extended_window(line_s)
            and not _is_tram_b_extended_allowlisted(line_s)):
        return False
    if line_s[F_CLAVE_TRAMITE[0]:F_CLAVE_TRAMITE[1]].strip() == '5':
        return False
    cod_tipo = line_s[F_COD_TIPO[0]:F_COD_TIPO[1]].strip()
    if (cod_tipo not in DGT_SCOPE_COD_TIPO
            and not is_mercedes_rest_scope_cod_tipo_exception(line_s)
            and not is_toyota_rest_scope_cod_tipo_exception(line_s)
            and not is_peugeot_rest_scope_cod_tipo_exception(line_s)):
        return False
    return True




def fuel_to_canal_counts(fuel_counts):
    """Agrega fuel_counts (clave extendida) → {(marca, canal): n}."""
    agg = collections.Counter()
    for key, n in fuel_counts.items():
        # key puede ser (marca, modelo, canal, fuel, seg, sub, hp, body)
        #            o  (marca, canal, fuel)  (formato antiguo)
        if len(key) == 9:
            marca, canal = key[0], key[2]
        elif len(key) == 8:
            marca, canal = key[0], key[2]
        elif len(key) == 3:
            marca, canal = key[0], key[1]
        else:
            marca, canal = key[0], key[1]
        agg[(marca, canal)] += n
    return agg


def process_lines(lines_iter, apply_calibration=True, current_yyyymm=None):
    global LAST_PROCESS_ALERTS
    counts      = collections.Counter()
    fuel_counts = collections.Counter()
    prov_counts = collections.Counter()
    retro_corrections = collections.Counter()  # (target_yyyymm, *bucket) → -1 each
    km0_fallback_pool = collections.Counter()
    carrocero_unmapped_pool = collections.Counter()
    invalid_scope_pool = collections.Counter()
    itv_quality_pool = collections.Counter()
    alerts = []
    for raw in lines_iter:
        line = raw.rstrip(b'\r\n')
        if len(line) < 250:
            continue
        try:
            line_s = line.decode('latin-1')
        except Exception:
            continue
        if not passes_dgt_scope_filters(line_s):
            continue
        marca_raw = line_s[F_MARCA[0]:F_MARCA[1]]
        modelo = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
        marca  = normalize_marca(marca_raw, modelo)
        if not es_turismo_o_furgoneta(line_s):
            # Rescate N2: derivados de furgoneta que Simmix sí incluye
            cat_homol = line_s[F_HOMOLOGACION[0]:F_HOMOLOGACION[1]].strip().upper()
            if not cat_homol.startswith('N2'):
                continue
            n2_target = n2_van_target(marca, modelo)
            if n2_target is None:
                continue
            marca = n2_target
        # Carrozados/camperizados → marca del chasis (metodología Simmix)
        marca, modelo, carro_unmapped = reassign_carrocero(marca, modelo)
        if carro_unmapped:
            carrocero_unmapped_pool[marca] += 1
        if is_excluded_scope(marca_raw, marca, modelo):
            continue
        servicio  = line_s[F_SERVICIO[0]:F_SERVICIO[1]]
        persona   = line_s[F_PERSONA_FJ[0]:F_PERSONA_FJ[1]]
        renting   = line_s[F_RENTING[0]:F_RENTING[1]]
        mun       = line_s[F_MUNICIPIO[0]:F_MUNICIPIO[1]]
        canal     = classify(servicio, persona, renting, mun, marca)
        invalid_reason = invalid_itv_scope_reason(
            line_s, marca, canal, servicio, persona, renting
        )
        if invalid_reason:
            invalid_scope_pool[(marca, canal, visible_dgt_vin10(line_s), invalid_reason)] += 1
            continue
        itv_warning = itv_quality_warning_reason(line_s, marca)
        if itv_warning:
            itv_quality_pool[(marca, canal, visible_dgt_vin10(line_s), itv_warning)] += 1
        fuel_code = get_fuel_type_code(line_s)
        cod_prov  = mun[:2].strip()
        # Enriquecimiento: obtener modelo canónico y dimensiones de segmento
        modelo_canon, seg, sub, hp, body, fuel_detail = lookup_enrichment(marca, modelo, line_s)
        if marca == 'BMW' and modelo_canon in _BMW_IMODEL_FIX:
            modelo_canon = _BMW_IMODEL_FIX[modelo_canon]
        if not fuel_detail:
            fuel_detail = get_fuel_detail_from_dgt(line_s)
        hp = classify_high_performance(marca, modelo, hp)
        # ── VIN-dedup gate for extended-window tram=B (61-730 days) ──────────
        # For records that passed scope via _is_tram_b_extended_window(), check
        # whether the VIN was already seen as N/U=N in a prior month.
        #   • vin10 empty → can't verify → conservative: skip (no overcount)
        #   • vin10 in _VIN10_NU_N_INDEX → prior N/U=N record exists → skip
        #   • vin10 not in index → genuine first registration → count it
        _nu_field   = line_s[F_NUEVO_USADO[0]:F_NUEVO_USADO[1]].strip()
        _tram_field = line_s[F_CLAVE_TRAMITE[0]:F_CLAVE_TRAMITE[1]].strip()
        if _nu_field == 'U' and _tram_field == 'B' and _is_tram_b_extended_window(line_s):
            _vin10_ext = visible_dgt_vin10(line_s)
            if not _vin10_ext or _vin10_ext in _VIN10_NU_N_INDEX:
                continue  # skip: was already counted or VIN unreadable
        # ─────────────────────────────────────────────────────────────────────

        counts[(marca, canal)] += 1
        fuel_counts[(marca, modelo_canon, canal, fuel_code, fuel_detail, seg, sub, hp, body)] += 1
        if cod_prov.isdigit():
            prov_counts[(cod_prov, marca, canal, fuel_code)] += 1

        # Collect vin10 for N/U=N records so future tram=B dedup checks work
        if _nu_field == 'N':
            _vin10_n = visible_dgt_vin10(line_s)
            if _vin10_n:
                _VIN10_NU_N_INDEX.add(_vin10_n)

        # Retroactive correction: when a tram=B vehicle's provisional was in a
        # prior month, we must subtract that provisional count from that month so
        # the vehicle is counted only once (in the definitive month), matching
        # Simmix's VIN-deduplication behaviour.
        if (current_yyyymm is not None
                and line_s[F_CLAVE_TRAMITE[0]:F_CLAVE_TRAMITE[1]].strip() == 'B'
                and line_s[F_NUEVO_USADO[0]:F_NUEVO_USADO[1]].strip() == 'U'):
            retro_month = _tram_b_retro_yyyymm(line_s, current_yyyymm)
            if retro_month:
                retro_key = (retro_month, marca, modelo_canon, canal,
                             fuel_code, fuel_detail, seg, sub, hp, body)
                retro_corrections[retro_key] -= 1
        if canal == 'Private' and servicio.strip() == 'B00' and persona.strip() == 'D':
            rate_brand = km0_rate_brand(marca)
            if rate_brand in KM0_BRAND_FALLBACK_RATE:
                km0_fallback_pool[marca] += 1


    for marca, n in carrocero_unmapped_pool.items():
        if n >= ALERT_CARROCERO_UNMAPPED:
            alerts.append(make_alert(
                'INFO',
                'CARROCERO_UNMAPPED',
                marca=marca,
                canal='',
                metric='registros_carrocero_sin_chasis_detectado',
                value=n,
                threshold=ALERT_CARROCERO_UNMAPPED,
                detail='ampliar _CHASSIS_RULES o CARROCERO_BRANDS',
            ))

    for (marca, canal, vin10, reason), n in invalid_scope_pool.items():
        alerts.append(make_alert(
            'INFO',
            'INVALID_ITV_SCOPE_EXCLUDED',
            marca=marca,
            canal=canal,
            metric='registros_excluidos_ficha_itv_invalida',
            value=n,
            threshold=1,
            detail='vin10={}; {}'.format(vin10, reason),
        ))

    for (marca, canal, vin10, reason), n in itv_quality_pool.items():
        alerts.append(make_alert(
            'INFO',
            'ITV_QUALITY_SUSPECT',
            marca=marca,
            canal=canal,
            metric='registros_ficha_itv_sospechosa_no_excluidos',
            value=n,
            threshold=1,
            detail='vin10={}; {}'.format(vin10, reason),
        ))

    for marca, n in km0_fallback_pool.items():
        rate = KM0_BRAND_FALLBACK_RATE[km0_rate_brand(marca)]
        moved = int(round(n * rate))
        if moved <= 0:
            continue
        counts[(marca, 'Private')] -= moved
        counts[(marca, 'Corporate')] += moved
        if moved >= ALERT_KM0_FALLBACK_MOVED:
            alerts.append(make_alert(
                'INFO',
                'KM0_FALLBACK',
                marca=marca,
                canal='Corporate',
                metric='b00d_private_moved_to_corporate',
                value=moved,
                threshold=ALERT_KM0_FALLBACK_MOVED,
                detail='pool_b00d_private={}; rate={:.4f}'.format(n, rate),
            ))
    LAST_PROCESS_ALERTS = alerts
    if not apply_calibration:
        return fuel_counts, prov_counts, retro_corrections
    calibrated = apply_scope_calibration(counts) if apply_calibration else counts
    raw_totals = {}
    for key, n in fuel_counts.items():
        marca = key[0]
        canal = key[2] if len(key) in (8, 9) else key[1]
        raw_totals[(marca, canal)] = raw_totals.get((marca, canal), 0) + n
    calibrated_fuel = collections.Counter()
    for key, n in fuel_counts.items():
        marca = key[0]
        canal = key[2] if len(key) in (8, 9) else key[1]
        raw = raw_totals.get((marca, canal), 0)
        cal = calibrated.get((marca, canal), raw)
        calibrated[(marca, canal)] = cal
    calibrated_fuel = allocate_calibrated_fuel(fuel_counts, calibrated, raw_totals)
    return calibrated_fuel, prov_counts, retro_corrections




def process_zip(zip_path, apply_calibration=True, current_yyyymm=None):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()
        txt_names = [n for n in names if n.lower().endswith('.txt')]
        if not txt_names:
            raise ValueError("ZIP sin .txt: {}".format(names))
        with zf.open(txt_names[0]) as f:
            return process_lines(f, apply_calibration=apply_calibration,
                                 current_yyyymm=current_yyyymm)




def process_raw_txt(txt_path, apply_calibration=True, current_yyyymm=None):
    with open(txt_path, 'rb') as f:
        return process_lines(f, apply_calibration=apply_calibration,
                             current_yyyymm=current_yyyymm)




def save_csv(counts, yyyymm):
    """counts: {(marca, modelo, canal, fuel_type, seg, sub, hp, body): n}"""
    year, month = yyyymm[:4], yyyymm[4:]
    path = os.path.join(OUT_DIR, "dgt_canal_{}.csv".format(yyyymm))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(["anyo","mes","marca","modelo","canal","fuel_type","fuel","segmento","subseg","hp","body_type","count"])
        for key, n in sorted(counts.items()):
            if len(key) == 9:
                marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body = key
            elif len(key) == 8:
                marca, modelo, canal, fuel_type, seg, sub, hp, body = key
                fuel_det = ''
            else:
                marca, canal, fuel_type = key[0], key[1], key[2]
                modelo = seg = sub = hp = body = fuel_det = ''
            w.writerow([year, month, marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body, n])
    total = sum(counts.values())
    print("  -> {}  ({:,} registros nuevos, {} combos)".format(path, total, len(counts)))
    return path


def save_prov_csv(prov_counts, yyyymm):
    """prov_counts: {(cod_prov, marca, canal, fuel_type): n}"""
    import csv as csv_mod
    year, month = yyyymm[:4], yyyymm[4:]
    path = os.path.join(OUT_DIR, "dgt_prov_{}.csv".format(yyyymm))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv_mod.writer(f, quoting=csv_mod.QUOTE_MINIMAL)
        w.writerow(["anyo","mes","marca","cod_prov","provincia","canal","fuel_type","count"])
        for key, n in sorted(prov_counts.items()):
            if len(key) == 4:
                cod_prov, marca, canal, fuel_type = key
            else:
                cod_prov, canal, fuel_type = key
                marca = ""
            nombre = PROV_NAMES.get(cod_prov, 'Desconocida')
            w.writerow([year, month, marca, cod_prov, nombre, canal, fuel_type, n])
    print("  -> {}  ({} combos provincia)".format(path, len(prov_counts)))
    return path


def save_daily_csv(counts, yyyymmdd):
    """counts: {(marca, modelo, canal, fuel_type, seg, sub, hp, body): n}"""
    year, month, day = yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:]
    path = os.path.join(OUT_DIR, "dgt_canal_daily_{}.csv".format(yyyymmdd))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(["anyo","mes","dia","marca","modelo","canal","fuel_type","fuel","segmento","subseg","hp","body_type","count"])
        for key, n in sorted(counts.items()):
            if len(key) == 9:
                marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body = key
            elif len(key) == 8:
                marca, modelo, canal, fuel_type, seg, sub, hp, body = key
                fuel_det = ''
            else:
                marca, canal, fuel_type = key[0], key[1], key[2]
                modelo = seg = sub = hp = body = fuel_det = ''
            w.writerow([year, month, day, marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body, n])
    total = sum(counts.values())
    print("  -> {}  ({:,} registros nuevos, {} combos)".format(path, total, len(counts)))
    return path


def save_prov_daily_csv(prov_counts, yyyymmdd):
    import csv as csv_mod
    year, month, day = yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:]
    path = os.path.join(OUT_DIR, "dgt_prov_daily_{}.csv".format(yyyymmdd))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv_mod.writer(f, quoting=csv_mod.QUOTE_MINIMAL)
        w.writerow(["anyo","mes","dia","marca","cod_prov","provincia","canal","fuel_type","count"])
        for key, n in sorted(prov_counts.items()):
            if len(key) == 4:
                cod_prov, marca, canal, fuel_type = key
            else:
                cod_prov, canal, fuel_type = key
                marca = ""
            nombre = PROV_NAMES.get(cod_prov, 'Desconocida')
            w.writerow([year, month, day, marca, cod_prov, nombre, canal, fuel_type, n])
    return path


def read_channel_counts(path):
    """Lee CSV daily → {(marca, modelo, canal, fuel_type, seg, sub, hp, body): n}"""
    counts = collections.Counter()
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            marca     = (row.get('marca') or '').strip().upper()
            modelo    = (row.get('modelo') or '').strip().upper()
            canal     = (row.get('canal') or '').strip()
            fuel_type = (row.get('fuel_type') or 'ICE').strip() or 'ICE'
            fuel_det  = (row.get('fuel') or '').strip()
            seg       = (row.get('segmento') or '').strip()
            sub       = (row.get('subseg') or '').strip()
            hp        = (row.get('hp') or '').strip()
            body      = (row.get('body_type') or '').strip()
            if not marca or not canal:
                continue
            try:
                n = int(float(row.get('count', 0)))
            except (TypeError, ValueError):
                continue
            counts[(marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body)] += n
    return counts


def save_mtd_from_daily(yyyymm):
    import csv as csv_mod
    counts = collections.Counter()
    prefix = "dgt_canal_daily_{}".format(yyyymm)
    for name in os.listdir(OUT_DIR):
        if name.startswith(prefix) and name.endswith('.csv'):
            counts.update(read_channel_counts(os.path.join(OUT_DIR, name)))
    if not counts:
        return None
    year, month = yyyymm[:4], yyyymm[4:]
    path = os.path.join(OUT_DIR, "dgt_canal_{}_mtd.csv".format(yyyymm))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv_mod.writer(f, quoting=csv_mod.QUOTE_MINIMAL)
        w.writerow(["anyo","mes","marca","modelo","canal","fuel_type","fuel","segmento","subseg","hp","body_type","count"])
        for key, n in sorted(counts.items()):
            if len(key) == 9:
                marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body = key
            elif len(key) == 8:
                marca, modelo, canal, fuel_type, seg, sub, hp, body = key
                fuel_det = ''
            else:
                marca, canal, fuel_type = key[0], key[1], key[2]
                modelo = seg = sub = hp = body = fuel_det = ''
            w.writerow([year, month, marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body, n])
    print("  -> {}  ({:,} registros MTD)".format(path, sum(counts.values())))
    return path


def save_alerts(alerts, yyyymm):
    import csv as csv_mod
    path = os.path.join(OUT_DIR, "dgt_alerts_{}.csv".format(yyyymm))
    fields = ['yyyymm', 'severity', 'kind', 'marca', 'canal', 'metric', 'value', 'threshold', 'detail']
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv_mod.DictWriter(f, fieldnames=fields, quoting=csv_mod.QUOTE_MINIMAL)
        w.writeheader()
        for alert in alerts:
            row = {'yyyymm': yyyymm}
            row.update(alert)
            w.writerow(row)
    if alerts:
        by_severity = collections.Counter(a['severity'] for a in alerts)
        summary = ', '.join("{}={}".format(k, by_severity[k]) for k in sorted(by_severity))
        print("  WARN alertas {}: {} ({})".format(yyyymm, len(alerts), summary))
    else:
        print("  -> alertas {}: 0".format(yyyymm))
    return path


def apply_retro_corrections_to_csv(target_yyyymm, corrections):
    """Subtract provisional-month counts from a completed monthly CSV.

    corrections: {(marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body): delta}
                 delta values are negative (−1 per vehicle).

    Only modifies buckets that exist and have count > 0.  Buckets not found
    in the CSV are silently skipped (the vehicle may have been imported without
    a prior N/U=N DGT record — no correction needed).
    """
    path = os.path.join(OUT_DIR, 'dgt_canal_{}.csv'.format(target_yyyymm))
    if not os.path.exists(path):
        print('  WARN retro: no CSV mensual para {}, correcciones omitidas'.format(target_yyyymm))
        return 0
    counts = read_channel_counts(path)
    applied = 0
    for bucket, delta in corrections.items():
        if counts.get(bucket, 0) > 0:
            counts[bucket] = max(0, counts[bucket] + delta)
            applied += 1
        # else: bucket not present or already 0 — vehicle had no prior N/U=N DGT
        # record (imported / single-entry); the tram=B count in the current month
        # is the only record, so no subtraction is needed.
    if applied:
        save_csv(counts, target_yyyymm)
        print('  -> retro {}: {} buckets corregidos'.format(target_yyyymm, applied))
    return applied


def save_retro_corrections_log(retro_corrections, processed_date):
    """Append retroactive corrections to the audit log."""
    file_exists = os.path.exists(RETRO_CORRECTIONS_FILE)
    with open(RETRO_CORRECTIONS_FILE, 'a', encoding='utf-8', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        if not file_exists:
            w.writerow(RETRO_CORRECTIONS_HEADER)
        for (target_yyyymm, marca, modelo, canal,
             fuel_type, fuel_det, seg, sub, hp, body), delta in retro_corrections.items():
            w.writerow([processed_date, target_yyyymm, marca, modelo, canal,
                        fuel_type, fuel_det, seg, sub, hp, body, delta])


def _apply_retro_dict(retro_corrections):
    """Group retro_corrections Counter by target_yyyymm and apply to each CSV."""
    by_month = collections.defaultdict(collections.Counter)
    for (target_yyyymm, marca, modelo, canal,
         fuel_type, fuel_det, seg, sub, hp, body), delta in retro_corrections.items():
        bucket = (marca, modelo, canal, fuel_type, fuel_det, seg, sub, hp, body)
        by_month[target_yyyymm][bucket] += delta
    total = 0
    for target_yyyymm, corrections in by_month.items():
        total += apply_retro_corrections_to_csv(target_yyyymm, corrections)
    return total


def finalize_month(result, yyyymm):
    fuel_counts, prov_counts, retro_corrections = result
    save_csv(fuel_counts, yyyymm)
    save_prov_csv(prov_counts, yyyymm)
    canal_counts = fuel_to_canal_counts(fuel_counts)
    alerts = list(LAST_PROCESS_ALERTS)
    add_unknown_brand_alerts(yyyymm, canal_counts, alerts)
    add_drift_alerts(yyyymm, canal_counts, alerts)
    save_alerts(alerts, yyyymm)
    if retro_corrections:
        _apply_retro_dict(retro_corrections)
        save_retro_corrections_log(retro_corrections, yyyymm)
    _save_vin10_index()


def finalize_day(result, yyyymmdd):
    fuel_counts, prov_counts, retro_corrections = result
    save_daily_csv(fuel_counts, yyyymmdd)
    save_prov_daily_csv(prov_counts, yyyymmdd)
    save_alerts(list(LAST_PROCESS_ALERTS), yyyymmdd)
    if retro_corrections:
        _apply_retro_dict(retro_corrections)
        save_retro_corrections_log(retro_corrections, yyyymmdd)
    _save_vin10_index()


def download_and_process(yyyymm, keep_raw=False, force=False):
    out_csv  = os.path.join(OUT_DIR, "dgt_canal_{}.csv".format(yyyymm))
    zip_path = os.path.join(TMP_DIR, "export_mensual_mat_{}.zip".format(yyyymm))
    txt_path = os.path.join(TMP_DIR, "export_mensual_mat_{}.txt".format(yyyymm))


    if os.path.exists(out_csv) and not force:
        if os.path.getsize(out_csv) > 100:
            print("[{}] Ya procesado, skip.".format(yyyymm))
            return
        else:
            print("[{}] CSV vacio, reprocesando...".format(yyyymm))
            try:
                os.remove(out_csv)
            except Exception as e:
                print("  WARN no pudo borrar CSV vacio: {}".format(e))


    # procesar TXT legacy (ya descomprimido en /tmp/)
    if os.path.exists(txt_path):
        print("[{}] TXT raw en /tmp, procesando...".format(yyyymm))
        counts = process_raw_txt(txt_path, current_yyyymm=yyyymm)
        finalize_month(counts, yyyymm)
        if not keep_raw:
            os.remove(txt_path)
            print("  -> txt borrado")
        return


    # descargar ZIP si no esta
    if not os.path.exists(zip_path):
        url = get_url(yyyymm)
        print("[{}] ZIP no encontrado, descargando...".format(yyyymm))
        if not download_zip(url, zip_path):
            return
    else:
        print("[{}] ZIP ya en /tmp, procesando...".format(yyyymm))


    # procesar ZIP
    print("[{}] Procesando ZIP...".format(yyyymm))
    try:
        counts = process_zip(zip_path, current_yyyymm=yyyymm)
    except Exception as e:
        print("  ERROR procesando ZIP: {}".format(e))
        return
    finalize_month(counts, yyyymm)


    if not keep_raw:
        os.remove(zip_path)
        print("  -> zip borrado")




def download_and_process_month_url(yyyymm, url, keep_raw=False, force=False):
    out_csv = os.path.join(OUT_DIR, "dgt_canal_{}.csv".format(yyyymm))
    zip_path = os.path.join(TMP_DIR, "export_mensual_mat_{}.zip".format(yyyymm))
    if os.path.exists(out_csv) and not force and os.path.getsize(out_csv) > 100:
        print("[{}] Mensual ya procesado, skip.".format(yyyymm))
        return None
    print("[{}] Procesando mensual publicado...".format(yyyymm))
    if not download_zip(url, zip_path):
        return None
    try:
        counts = process_zip(zip_path, current_yyyymm=yyyymm)
    except Exception as e:
        print("  ERROR procesando ZIP: {}".format(e))
        return None
    finalize_month(counts, yyyymm)
    if not keep_raw:
        os.remove(zip_path)
        print("  -> zip borrado")
    return counts




def download_and_process_daily(yyyymmdd, url=None, keep_raw=False, force=False):
    out_csv = os.path.join(OUT_DIR, "dgt_canal_daily_{}.csv".format(yyyymmdd))
    zip_path = os.path.join(TMP_DIR, "export_mat_{}.zip".format(yyyymmdd))
    if os.path.exists(out_csv) and not force and os.path.getsize(out_csv) > 100:
        print("[{}] Diario ya procesado, skip.".format(yyyymmdd))
        return None
    if url is None:
        url = "https://www.dgt.es/microdatos/salida/{}/{}/vehiculos/matriculaciones/export_mat_{}.zip".format(
            yyyymmdd[:4], int(yyyymmdd[4:6]), yyyymmdd
        )
    print("[{}] Procesando diario publicado...".format(yyyymmdd))
    if not download_zip(url, zip_path):
        return None
    current_yyyymm = yyyymmdd[:6]
    try:
        counts = process_zip(zip_path, apply_calibration=False,
                             current_yyyymm=current_yyyymm)
    except Exception as e:
        print("  ERROR procesando ZIP: {}".format(e))
        return None
    finalize_day(counts, yyyymmdd)
    if not keep_raw:
        os.remove(zip_path)
        print("  -> zip borrado")
    return counts




def sync_monthly_2026(keep_raw=False, force=False):
    links = discover_monthly_links(start='202601')
    print("Mensuales 2026 publicados: {}".format(len(links)))
    for yyyymm, url in links:
        download_and_process_month_url(yyyymm, url, keep_raw=keep_raw, force=force)




def sync_daily_current(keep_raw=False, force=False):
    links = discover_daily_links()
    print("Diarios publicados en pagina DGT: {}".format(len(links)))
    months = set()
    for yyyymmdd, url in links:
        months.add(yyyymmdd[:6])
        download_and_process_daily(yyyymmdd, url=url, keep_raw=keep_raw, force=force)
    for yyyymm in sorted(months):
        save_mtd_from_daily(yyyymm)




def sync_auto(keep_raw=False, force=False):
    sync_monthly_2026(keep_raw=keep_raw, force=force)
    sync_daily_current(keep_raw=keep_raw, force=force)




def all_months(start='202301', end='202512'):
    months = []
    y, m = int(start[:4]), int(start[4:])
    ey, em = int(end[:4]), int(end[4:])
    while (y, m) <= (ey, em):
        months.append("{:04d}{:02d}".format(y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months




if __name__ == '__main__':
    # Cargar lookup de enriquecimiento marca+modelo → segmento/body_type
    _load_simmix_bbdd()
    _load_enrichment()
    _load_eea_lookup()
    _load_vin10_index()
    print(f"  -> Model lookup: {len(_MODEL_LOOKUP):,} combos (Simmix)")


    arg   = sys.argv[1] if len(sys.argv) > 1 else 'all'
    keep  = '--keep'  in sys.argv
    force = '--force' in sys.argv


    if arg == 'all':
        import datetime as _dt
        _now = _dt.date.today()
        _end = '{:04d}{:02d}'.format(_now.year, _now.month)
        for yyyymm in all_months():
            download_and_process(yyyymm, keep_raw=keep, force=force)
    elif arg == 'monthly-2026':
        sync_monthly_2026(keep_raw=keep, force=force)
    elif arg == 'daily-current':
        sync_daily_current(keep_raw=keep, force=force)
    elif arg == 'auto':
        sync_auto(keep_raw=keep, force=force)
    else:
        download_and_process(arg, keep_raw=keep, force=force)
