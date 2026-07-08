"""Tests de las reglas de negocio de la ETL (metodología Simmix replicada).

No requieren red ni datos DGT: prueban las funciones puras de scripts/process_month.py.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import process_month as pm


def _scope_filter_line(clase='0', nuevo='N', tramite='1', cod_tipo='40'):
    line = [' '] * 714
    line[pm.F_CLASE_MAT[0]:pm.F_CLASE_MAT[1]] = list(clase[:1])
    line[pm.F_NUEVO_USADO[0]:pm.F_NUEVO_USADO[1]] = list(nuevo[:1])
    line[pm.F_CLAVE_TRAMITE[0]:pm.F_CLAVE_TRAMITE[1]] = list(tramite[:1])
    line[pm.F_COD_TIPO[0]:pm.F_COD_TIPO[1]] = list(cod_tipo[:2].rjust(2))
    return ''.join(line)


def test_filtros_scope_dgt_aceptan_criterio_simmix():
    assert pm.passes_dgt_scope_filters(_scope_filter_line())
    assert pm.passes_dgt_scope_filters(_scope_filter_line(clase='1'))
    assert pm.passes_dgt_scope_filters(_scope_filter_line(cod_tipo='25'))


def test_filtros_scope_dgt_excluyen_matriculas_diplomaticas():
    assert not pm.passes_dgt_scope_filters(_scope_filter_line(clase='3'))


def test_filtros_scope_dgt_excluyen_usados():
    assert not pm.passes_dgt_scope_filters(_scope_filter_line(nuevo='U'))


def test_filtros_scope_dgt_excluyen_rematriculaciones():
    assert not pm.passes_dgt_scope_filters(_scope_filter_line(tramite='5'))


def test_filtros_scope_dgt_excluyen_cod_tipo_fuera_de_scope():
    assert not pm.passes_dgt_scope_filters(_scope_filter_line(cod_tipo='30'))


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

def test_a01_bmw_venturada_renting_es_rac():
    assert pm.classify('A01', 'X', 'S', '28169', 'BMW') == 'RAC'

def test_a01_marca_no_rac_venturada_sigue_corporate():
    assert pm.classify('A01', 'X', 'S', '28169', 'MERCEDES') == 'Corporate'

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

def _scope_line(
    modelo_itv,
    servicio='B00',
    persona='D',
    renting='N',
    mun='99999',
    plazas='0',
    mma='002000',
    homol='M1',
    tech='',
    variante='',
    fabricante='ND',
):
    line = [' '] * 714
    line[pm.F_MODELO[0]:110] = list(modelo_itv[:63].ljust(63))
    line[pm.F_PLAZAS[0]:pm.F_PLAZAS[1]] = list(plazas[:1])
    line[pm.F_MMA[0]:pm.F_MMA[1]] = list(mma[:6].rjust(6))
    line[pm.F_HOMOLOGACION[0]:pm.F_HOMOLOGACION[1]] = list(homol[:4].ljust(4))
    line[pm.F_SERVICIO[0]:pm.F_SERVICIO[1]] = list(servicio[:3].ljust(3))
    line[pm.F_PERSONA_FJ[0]:pm.F_PERSONA_FJ[1]] = list(persona[:1])
    line[pm.F_RENTING[0]:pm.F_RENTING[1]] = list(renting[:1])
    line[pm.F_MUNICIPIO[0]:pm.F_MUNICIPIO[1]] = list(mun[:5].ljust(5))
    line[250:330] = list(tech[:80].ljust(80))
    if variante:
        width = pm.F_VARIANTE_ITV[1] - pm.F_VARIANTE_ITV[0]
        line[pm.F_VARIANTE_ITV[0]:pm.F_VARIANTE_ITV[1]] = list(variante[:width].ljust(width))
    line[330:390] = list(fabricante[:60].ljust(60))
    return ''.join(line)

def test_ficha_itv_incompleta_se_excluye_en_cualquier_canal():
    line = _scope_line('BMW 318D              3WBAUX11060***********400')
    assert pm.visible_dgt_vin10(line) == 'WBAUX11060'
    reason = pm.invalid_itv_scope_reason(
        line, 'BMW', 'Private', 'B00', 'D', 'N'
    )
    assert 'sin codigos' in reason

def test_ficha_itv_incompleta_tambien_excluye_corporate():
    line = _scope_line('X3                    3WBAPA91060***********401', persona='X')
    assert pm.visible_dgt_vin10(line) == 'WBAPA91060'
    reason = pm.invalid_itv_scope_reason(
        line, 'BMW', 'Corporate', 'B00', 'X', 'N'
    )
    assert 'sin codigos' in reason

def test_ficha_sin_codigo_itv_con_plazas_validas_no_se_excluye():
    line = _scope_line(
        'X1                    1WBXJG9C01M***********400',
        persona='X',
        plazas='5',
        tech='N                                         TURISMO                  ---',
        fabricante='ND',
    )
    assert pm.visible_dgt_vin10(line) == 'WBXJG9C01M'
    assert not pm.invalid_itv_scope_reason(
        line, 'BMW', 'Corporate', 'B00', 'X', 'N'
    )

def test_bmw_version_confirmada_por_eplate_no_se_excluye():
    line = _scope_line(
        'X2 SDRIVE20I          3WBA21GM010***********400',
        plazas='5',
        tech='21GM                     FAV508L0',
        fabricante='BAYERISCHE MOTOREN WERKE AG',
    )
    assert pm.visible_dgt_vin10(line) == 'WBA21GM010'
    assert not pm.invalid_itv_scope_reason(
        line, 'BMW', 'Private', 'B00', 'D', 'N'
    )

def test_ficha_itv_m1_con_mma_cero_genera_alerta_no_bloqueante():
    line = _scope_line(
        '320D                  3WBAUY11090***********400',
        plazas='5',
        mma='0',
        tech='UY11                     FAA500L0',
        variante='UY11',
        fabricante='BAYERISCHE MOTOREN WERKE AG',
    )
    assert not pm.invalid_itv_scope_reason(
        line, 'BMW', 'Private', 'B00', 'D', 'N'
    )
    reason = pm.itv_quality_warning_reason(line, 'BMW')
    assert 'MMA invalida' in reason

def test_ficha_itv_m1_con_mma_cero_y_variante_conocida_no_se_excluye(monkeypatch):
    monkeypatch.setitem(pm._EEA_LOOKUP, ('BMW', '21GM'), 'X2 SDRIVE20I')
    line = _scope_line(
        'X2 SDRIVE20I          3WBA21GM010***********400',
        plazas='5',
        mma='0',
        tech='21GM                     FAV508L0',
        variante='21GM',
        fabricante='BAYERISCHE MOTOREN WERKE AG',
    )
    assert not pm.invalid_itv_scope_reason(
        line, 'BMW', 'Private', 'B00', 'D', 'N'
    )
    assert not pm.itv_quality_warning_reason(line, 'BMW')

def test_eea_bmw_118d_cae_a_serie_1_si_existe_modelo_canonico(monkeypatch):
    line = _scope_line('118D                  3WBA11GF')
    line = list(line)
    line[pm.F_VARIANTE_ITV[0]:pm.F_VARIANTE_ITV[1]] = list('11GF'.ljust(pm.F_VARIANTE_ITV[1] - pm.F_VARIANTE_ITV[0]))
    line = ''.join(line)
    monkeypatch.setitem(pm._EEA_LOOKUP, ('BMW', '11GF'), '118D')
    monkeypatch.setitem(pm._MODEL_LOOKUP, ('BMW', 'SERIE 1'), {
        'modelo': 'SERIE 1',
        'seg': 'UKL2',
        'sub': 'FOCUS SEGMENT',
        'hp': 'Standard',
        'body': 'HACH 5P',
        'fuel_detail': 'Diesel',
    })
    modelo, seg, sub, hp, body, fuel_detail = pm.lookup_enrichment('BMW', '118D', line)
    assert (modelo, seg, sub, body) == ('SERIE 1', 'UKL2', 'FOCUS SEGMENT', 'HACH 5P')


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
