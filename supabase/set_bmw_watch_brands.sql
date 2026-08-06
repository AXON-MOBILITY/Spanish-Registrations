-- Marcas vigiladas de BMW = el set completo "TRADITIONAL COMPETITION" que ya
-- usa la clasificacion Focus Segment del dataset (ver _BRAND_CONCEPT en
-- index.html), no solo Mercedes/Audi. Se usa para: quien gana cada
-- provincia en el mapa, texto rojo de rival en Overview/PDF, tarjetas de
-- Prognosis, y prioridad de orden en Alerts.
-- Correr en el SQL Editor de Supabase (reemplaza el valor anterior si ya
-- se habia corrido la version de 3 marcas).
update organizations
set config = config || '{"watch_brands": ["BMW", "Audi", "Mercedes", "MINI", "Porsche", "Volvo", "Lexus", "Jaguar", "Land Rover", "Maserati", "Ferrari", "Lamborghini", "Bentley", "Rolls-Royce", "McLaren", "Aston Martin", "Cadillac"]}'::jsonb
where slug = 'bmw';

-- Verificacion
select slug, config->'watch_brands' as watch_brands from organizations where slug='bmw';
