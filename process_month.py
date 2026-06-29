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

import sys, os, zipfile, urllib.request, collections, tempfile, re

TMP_DIR = tempfile.gettempdir()
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
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

# Modelos excluidos del scope (no estan en Simmix)
EXCLUIR_MARCA_MODELO = {}

# Reglas de campa
# 28169 Venturada = campa fabricante (Corporate) excepto Toyota/Lexus que van a alquiler (RAC)
# 28093 Navacerrada = deposito RAC (Skoda ya no va como Corporate)
# 28022 Boadilla = campa fabricante PSA (Corporate)
CAMPA_MUNICIPIOS_ALL = {'28169'}    # Venturada
CAMPA_VENTURADA_RAC  = {'TOYOTA', 'LEXUS', 'AUDI'}   # estas marcas en Venturada = RAC
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

# Residual scope calibration by brand/channel, learned from the 2023-2025
# DGT-vs-Simmix comparison after deterministic rules and Km.0 fallback.
# This handles cases where Simmix includes/excludes a slightly different scope
# than the DGT microdata filter or brand aliases.
CHANNEL_SCOPE_FACTOR = {
    ('AUDI', 'Private'): 1.02446686,
    ('AUDI', 'RAC'): 0.96362760,
    ('BMW', 'Private'): 0.98484432,
    ('BYD', 'Corporate'): 0.96574882,
    ('CITROEN', 'Private'): 1.06724235,
    ('CITROEN', 'RAC'): 0.99078595,
    ('DACIA', 'Private'): 1.00758472,
    ('DS', 'Corporate'): 1.68537824,
    ('DS', 'Private'): 1.48584371,
    ('DS', 'RAC'): 2.12815716,
    ('EVO', 'Private'): 2.17007874,
    ('FIAT', 'Private'): 1.78707951,
    ('FIAT', 'RAC'): 1.01984023,
    ('FORD', 'Private'): 1.24729364,
    ('FORD', 'RAC'): 0.90588365,
    ('HYUNDAI', 'RAC'): 0.99352733,
    ('ISUZU', 'Corporate'): 1.48877942,
    ('IVECO', 'Corporate'): 1.99602178,
    ('IVECO', 'Private'): 1.62838915,
    ('IVECO', 'RAC'): 1.62768031,
    ('KIA', 'Corporate'): 0.99571533,
    ('LEAPMOTOR', 'Corporate'): 0.70937129,
    ('LEAPMOTOR', 'Private'): 0.50065246,
    ('MAN', 'Corporate'): 1.12428793,
    ('MAN', 'RAC'): 1.49287169,
    ('MERCEDES-BENZ', 'Private'): 1.00714571,
    ('MERCEDES-BENZ', 'RAC'): 1.04516948,
    ('MERCEDES-V', 'Corporate'): 0.92486428,
    ('MG', 'Corporate'): 0.94479441,
    ('MG', 'Private'): 1.00496327,
    ('NISSAN', 'Private'): 1.01034865,
    ('NISSAN', 'RAC'): 0.92680608,
    ('OPEL', 'Private'): 1.14733492,
    ('OPEL', 'RAC'): 0.95423341,
    ('PEUGEOT', 'Private'): 1.07181872,
    ('PEUGEOT', 'RAC'): 1.01310178,
    ('RENAULT', 'Private'): 1.07027027,
    ('RENAULT', 'RAC'): 0.97824095,
    ('SEAT', 'Private'): 1.03028465,
    ('SEAT', 'RAC'): 0.94677806,
    ('SKODA', 'Corporate'): 0.97607462,
    ('SKODA', 'RAC'): 1.05566792,
    ('SSANGYONG', 'Private'): 1.07851385,
    ('SUZUKI', 'Corporate'): 0.91580977,
    ('SUZUKI', 'RAC'): 1.14340263,
    ('TESLA', 'Corporate'): 0.92346883,
    ('TESLA', 'Private'): 1.01811047,
    ('TOYOTA', 'Private'): 1.01480633,
    ('TOYOTA', 'RAC'): 0.98402966,
    ('VOLKSWAGEN', 'Corporate'): 0.99806854,
    ('VOLKSWAGEN', 'Private'): 1.00295073,
    ('VOLKSWAGEN', 'RAC'): 1.06340502,
    ('VOLVO', 'Private'): 0.98286175,
}

ALERT_DRIFT_START_YEAR = 2026
ALERT_MIN_BASELINE_COUNT = 50
ALERT_DRIFT_ABS = 250
ALERT_DRIFT_REL = 0.25
ALERT_DRIFT_CRITICAL_REL = 0.50
ALERT_NEW_BRAND_COUNT = 250
ALERT_KM0_FALLBACK_MOVED = 100

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
            with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                for row in csv_mod.DictReader(f):
                    try:
                        n = int(float(row.get('count', 0)))
                    except (TypeError, ValueError):
                        continue
                    yield yyyymm, row.get('marca', '').strip().upper(), row.get('canal', '').strip(), n
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
    if m in ('MERCEDES', 'MERCEDES BENZ', 'MERCEDES-BENZ', 'MERCEDES-AMG') and 'VITO' in mo:
        return 'MERCEDES-V'
    if m == 'LYNK&CO':
        return 'LYNK & CO'
    return m

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


def process_lines(lines_iter):
    global LAST_PROCESS_ALERTS
    counts = collections.Counter()
    km0_fallback_pool = collections.Counter()
    alerts = []
    for raw in lines_iter:
        line = raw.rstrip(b'\r\n')
        if len(line) < 250:
            continue
        try:
            line_s = line.decode('latin-1')
        except Exception:
            continue
        if line_s[F_NUEVO_USADO[0]:F_NUEVO_USADO[1]].strip() != 'N':
            continue
        if not es_turismo_o_furgoneta(line_s):
            continue
        marca_raw = line_s[F_MARCA[0]:F_MARCA[1]]
        modelo = line_s[F_MODELO[0]:F_MODELO[1]].strip().upper()
        marca  = normalize_marca(marca_raw, modelo)
        # Excluir modelos fuera del scope de Simmix
        # Simmix no tiene Vito (ni cargo ni tourer). La Clase V de Simmix = V-Class puro (V xxx).
        excl = EXCLUIR_MARCA_MODELO.get(marca)
        if excl and any(m in modelo for m in excl):
            continue
        servicio = line_s[F_SERVICIO[0]:F_SERVICIO[1]]
        persona  = line_s[F_PERSONA_FJ[0]:F_PERSONA_FJ[1]]
        renting  = line_s[F_RENTING[0]:F_RENTING[1]]
        mun      = line_s[F_MUNICIPIO[0]:F_MUNICIPIO[1]]
        canal = classify(servicio, persona, renting, mun, marca)
        counts[(marca, canal)] += 1
        if canal == 'Private' and servicio.strip() == 'B00' and persona.strip() == 'D':
            rate_brand = km0_rate_brand(marca)
            if rate_brand in KM0_BRAND_FALLBACK_RATE:
                km0_fallback_pool[marca] += 1

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
    return apply_scope_calibration(counts)


def process_zip(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()
        txt_names = [n for n in names if n.lower().endswith('.txt')]
        if not txt_names:
            raise ValueError("ZIP sin .txt: {}".format(names))
        with zf.open(txt_names[0]) as f:
            return process_lines(f)


def process_raw_txt(txt_path):
    with open(txt_path, 'rb') as f:
        return process_lines(f)


def save_csv(counts, yyyymm):
    import csv as csv_mod
    year  = yyyymm[:4]
    month = yyyymm[4:]
    path  = os.path.join(OUT_DIR, "dgt_canal_{}.csv".format(yyyymm))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv_mod.writer(f, quoting=csv_mod.QUOTE_MINIMAL)
        w.writerow(["anyo","mes","marca","canal","count"])
        for (marca, canal), n in sorted(counts.items()):
            w.writerow([year, month, marca, canal, n])
    total = sum(counts.values())
    print("  -> {}  ({:,} registros nuevos, {} combos)".format(path, total, len(counts)))
    return path

def save_daily_csv(counts, yyyymmdd):
    import csv as csv_mod
    year  = yyyymmdd[:4]
    month = yyyymmdd[4:6]
    day   = yyyymmdd[6:]
    path  = os.path.join(OUT_DIR, "dgt_canal_daily_{}.csv".format(yyyymmdd))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv_mod.writer(f, quoting=csv_mod.QUOTE_MINIMAL)
        w.writerow(["anyo","mes","dia","marca","canal","count"])
        for (marca, canal), n in sorted(counts.items()):
            w.writerow([year, month, day, marca, canal, n])
    total = sum(counts.values())
    print("  -> {}  ({:,} registros nuevos, {} combos)".format(path, total, len(counts)))
    return path

def read_channel_counts(path):
    import csv as csv_mod
    counts = collections.Counter()
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv_mod.DictReader(f):
            marca = row.get('marca', '').strip().upper()
            canal = row.get('canal', '').strip()
            if not marca or not canal:
                continue
            try:
                n = int(float(row.get('count', 0)))
            except (TypeError, ValueError):
                continue
            counts[(marca, canal)] += n
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
        w.writerow(["anyo","mes","marca","canal","count"])
        for (marca, canal), n in sorted(counts.items()):
            w.writerow([year, month, marca, canal, n])
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

def finalize_month(counts, yyyymm):
    save_csv(counts, yyyymm)
    alerts = list(LAST_PROCESS_ALERTS)
    add_unknown_brand_alerts(yyyymm, counts, alerts)
    add_drift_alerts(yyyymm, counts, alerts)
    save_alerts(alerts, yyyymm)

def finalize_day(counts, yyyymmdd):
    save_daily_csv(counts, yyyymmdd)
    save_alerts(list(LAST_PROCESS_ALERTS), yyyymmdd)

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
        counts = process_raw_txt(txt_path)
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
        counts = process_zip(zip_path)
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
        counts = process_zip(zip_path)
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
    try:
        counts = process_zip(zip_path)
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
    sync_monthly_2026(keep_raw=keep_raw, force=False)
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
    arg   = sys.argv[1] if len(sys.argv) > 1 else 'all'
    keep  = '--keep'  in sys.argv
    force = '--force' in sys.argv

    if arg == 'all':
        months = all_months('202301', '202512')
        print("Procesando {} meses (2023-2025)...".format(len(months)))
        for mm in months:
            download_and_process(mm, keep_raw=keep, force=force)
    elif arg == 'monthly-2026':
        sync_monthly_2026(keep_raw=keep, force=force)
    elif arg == 'daily-current':
        sync_daily_current(keep_raw=keep, force=force)
    elif arg == 'auto':
        sync_auto(keep_raw=keep, force=force)
    else:
        download_and_process(arg, keep_raw=keep, force=force)
