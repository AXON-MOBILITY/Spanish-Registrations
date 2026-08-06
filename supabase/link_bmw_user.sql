-- Vincula el usuario ya creado (bmw@accounts.axonmobility.internal) a la
-- organizacion BMW. Correr una sola vez en el SQL Editor de Supabase.
insert into org_members (user_id, org_id, role)
select u.id, o.id, 'admin'
from auth.users u, organizations o
where u.email = 'bmw@accounts.axonmobility.internal'
  and o.slug = 'bmw'
on conflict (user_id, org_id) do nothing;

-- Verificacion: deberia devolver una fila (bmw / admin)
select o.slug, m.role, u.email
from org_members m
join organizations o on o.id = m.org_id
join auth.users u on u.id = m.user_id;
