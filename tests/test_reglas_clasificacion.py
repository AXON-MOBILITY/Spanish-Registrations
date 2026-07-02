"""Tests de las reglas de negocio de la ETL (metodología Simmix replicada).

No requieren red ni datos DGT: prueban las funciones puras de scripts/process_month.py.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import process_month as pm


# ── Canal (SERVICIO + persona física/jurídica) ──────────────────────────────

def test_b00_empresa_es_corporate():
    assert pm.classify('B00', 'X', ' ', '99999', 'TOYOTA') == 'Corporate'

def test_b00_particular_municipio_normal_es_private():
    assert pm.classify('B00', 'D', ' ', '99999', 'TOYOTA') == 'Private'

def test_b00_particular_en_municipio_dealer_es_km0_corporate():
    # Cualquier municipio del set universal DEALER_MUN_ALL (salvo marcas excluidas)
    mun = next(iter(pm.DEALER_MUN_ALL))
    assert pm.classify('B00', 'D', ' ', mun, 'RENAULT') == 'Corporate'

def test_b00_dealer_mun_marca_excluida_sigue_private():
    mun = next(iter(pm.DEALER_MUN_ALL))
    for marca in pm.DEALER_MUN_ALL_EXCLUDED_BRANDS:
        if marca in pm.DEALER_MUN or mun in pm.DEALER_MUN.get(marca, set()):
            continue
        assert pm.classify('B00', 'D', ' ', mun, marca) == 'Private'

def test_a01_es_rac():
    assert pm.classify('A01', 'X', ' ', '99999', 'KIA') == 'RAC'

def test_a18_actividad_economica_es_corporate():
    assert pm.classify('A18', 'X', ' ', '99999', 'SEAT') == 'Corporate'


# ── Carroceros / camperizadores → marca del chasis ──────────────────────────

def test_camper_ducato_va_a_fiat():
    marca, modelo, unmapped = pm.reassign_carrocero('BENIMAR', 'MIZAR DUCATO 140')
    assert (marca, modelo, unmapped) == ('FIAT', 'DUCATO', False)

def test_carrozado_transit_custom_va_a_ford():
    marca, modelo, unmapped = pm.reassign_carrocero('ERKE', 'FORD TRANSIT CUSTOM L2')
    assert (marca, modelo) == ('FORD', 'TRANSIT CUSTOM')
    assert not unmapped

def test_carrozado_master_va_a_renault_trucks():
    marca, modelo, _ = pm.reassign_carrocero('EUROCARROCERA', 'MASTER L3H2')
    assert (marca, modelo) == ('RENAULT TRUCKS', 'MASTER')

def test_carrozado_tge_va_a_man():
    marca, modelo, _ = pm.reassign_carrocero('CAPRON', 'MAN TGE 3.140')
    assert (marca, modelo) == ('MAN', 'TGE')

def test_carrocero_sin_chasis_detectado_marca_unmapped():
    marca, modelo, unmapped = pm.reassign_carrocero('BENIMAR', 'TESSORO 481')
    assert marca == 'BENIMAR' and unmapped

def test_marca_normal_no_se_toca():
    marca, modelo, unmapped = pm.reassign_carrocero('BMW', 'TRANSIT')  # nombre casual
    assert (marca, modelo, unmapped) == ('BMW', 'TRANSIT', False)


# ── Rescate N2 de derivados de furgoneta ────────────────────────────────────

def test_n2_renault_master_va_a_renault_trucks():
    assert pm.n2_van_target('RENAULT', 'MASTER RED 4.5T') == 'RENAULT TRUCKS'

def test_n2_man_tge_incluido():
    assert pm.n2_van_target('MAN', 'TGE 5.180') == 'MAN'

def test_n2_fuso_canter_incluido():
    assert pm.n2_van_target('MITSUBISHI-FUSO', 'CANTER 7C15') == 'MITSUBISHI-FUSO'

def test_n2_camion_normal_excluido():
    assert pm.n2_van_target('SCANIA', 'P280') is None
    assert pm.n2_van_target('MAN', 'TGL 8.190') is None


# ── Filtro de scope M1/N1 (líneas de ancho fijo sintéticas) ─────────────────

def _linea(cat_homol='M1  ', plazas='5', mma='002000'):
    line = [' '] * 714
    line[pm.F_HOMOLOGACION[0]:pm.F_HOMOLOGACION[1]] = list(cat_homol[:4].ljust(4))
    line[pm.F_PLAZAS[0]:pm.F_PLAZAS[1]] = list(plazas)
    line[pm.F_MMA[0]:pm.F_MMA[1]] = list(mma)
    return ''.join(line)

def test_turismo_m1_incluido():
    assert pm.es_turismo_o_furgoneta(_linea('M1  '))

def test_furgoneta_n1_incluida():
    assert pm.es_turismo_o_furgoneta(_linea('N1  '))

def test_camion_n2_excluido_del_filtro_base():
    # El rescate N2 se decide después con n2_van_target()
    assert not pm.es_turismo_o_furgoneta(_linea('N2  '))

def test_sin_homologacion_usa_plazas_y_mma():
    assert pm.es_turismo_o_furgoneta(_linea('    ', plazas='5'))
    assert pm.es_turismo_o_furgoneta(_linea('    ', plazas='3', mma='002800'))
    assert not pm.es_turismo_o_furgoneta(_linea('    ', plazas='0'))


# ── Calibración: los factores retirados no deben reaparecer ─────────────────

def test_factores_obsoletos_eliminados():
    prohibidos = [('DS', c) for c in ('Corporate', 'Private', 'RAC')]
    prohibidos += [('LEAPMOTOR', c) for c in ('Corporate', 'Private')]
    prohibidos += [('IVECO', c) for c in ('Corporate', 'Private', 'RAC')]
    prohibidos += [('MAN', 'Corporate'), ('MAN', 'RAC'), ('ISUZU', 'Corporate')]
    prohibidos += [(m, 'Private') for m in ('FIAT', 'FORD', 'CITROEN', 'OPEL', 'RENAULT')]
    for key in prohibidos:
        assert key not in pm.CHANNEL_SCOPE_FACTOR, f'factor obsoleto presente: {key}'
