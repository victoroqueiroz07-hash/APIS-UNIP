@echo off
cd /d "%~dp0"
echo ================================================
echo     AlertaABC - mapa de alagamentos
 echo ================================================
echo.
echo Verificando dependencias...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Nao foi possivel instalar as dependencias.
  echo Verifique a internet e a instalacao do Python.
  pause
  exit /b 1
)
echo.
echo Abra no navegador: http://127.0.0.1:5000
echo Nao feche esta janela enquanto estiver usando o site.
echo.
python mainalagado.py
if errorlevel 1 (
  echo.
  echo Erro ao iniciar. Verifique os detalhes acima.
  pause
)
