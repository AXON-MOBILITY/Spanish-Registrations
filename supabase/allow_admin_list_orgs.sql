-- Permite que un platform_admin vea la lista completa de organizaciones
-- (antes cada usuario solo podia ver la propia). Necesario para poder
-- listarlas y borrarlas desde el panel de administracion.
-- Correr una sola vez en el SQL Editor de Supabase.

drop policy if exists "org: select own" on organizations;
create policy "org: select own or admin" on organizations
  for select using (
    id in (select org_id from org_members where user_id = auth.uid())
    or auth.uid() in (select user_id from platform_admins)
  );
