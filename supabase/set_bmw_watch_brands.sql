-- Preserva el comportamiento actual de BMW: Audi y Mercedes marcados como
-- rivales vigilados (texto rojo en Overview/PDF, tarjetas destacadas en
-- Prognosis, prioridad de orden en Alerts). Sin esto, watch_brands cae al
-- default (solo la marca propia) y esos resaltados de rival desaparecen.
-- Correr una sola vez en el SQL Editor de Supabase, DESPUES de que el
-- deploy con "watch_brands" este en produccion.
update organizations
set config = config || '{"watch_brands": ["BMW", "Mercedes", "Audi"]}'::jsonb
where slug = 'bmw';

-- Verificacion
select slug, config->'watch_brands' as watch_brands from organizations where slug='bmw';
