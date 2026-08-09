-- Restaura la clasificacion Focus/Resto original de BMW (precisa, a nivel
-- modelo, con TRAD. COMP. / NEW PLAYERS & TESLA). El panel "My view
-- settings" habia guardado un focus_brands explicito (Audi/BMW/MINI/
-- Mercedes) que activaba el modo "set competitivo propio" a nivel marca
-- en vez del fallback al dataset. Sacar la clave por completo restaura el
-- comportamiento de siempre (rowSubBucket usa el dataset cuando
-- focus_brands no existe).
update organizations
set config = config - 'focus_brands'
where slug = 'bmw';

-- Verificacion: focus_brands no debe aparecer en el resultado
select slug, config from organizations where slug='bmw';
