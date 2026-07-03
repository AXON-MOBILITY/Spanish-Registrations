@echo off
REM Publica los cambios del dashboard: doble clic y listo.
cd /d "%~dp0"
git add -A
git commit -m "Update dashboard %date% %time%"
git push
echo.
echo ================================================
echo  Publicado. Vercel desplegara en ~1 minuto.
echo  Refresca el dashboard con Ctrl+F5.
echo ================================================
pause
