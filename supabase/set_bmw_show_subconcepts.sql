-- Activa el desglose TRAD. COMP. / NEW PLAYERS & TESLA dentro de FOCUS
-- SEGMENT en el filtro de la izquierda, solo para BMW. Es la forma en que
-- BMW encuadra su competencia (estrategia propia), asi que no debe verla
-- ninguna otra organizacion por defecto.
--
-- Si en el futuro otra marca pide algo similar, se activa igual: cambiar
-- el "where slug = 'bmw'" por el slug de esa organizacion.
update organizations
set config = config || '{"show_subconcepts": true}'::jsonb
where slug = 'bmw';

-- Verificacion
select slug, config->'show_subconcepts' as show_subconcepts from organizations where slug='bmw';
