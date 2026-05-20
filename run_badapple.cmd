@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "PLAYER=%SCRIPT_DIR%cmd_badapple.py"

if not exist "%PYTHON_EXE%" (
  echo [ERRO] Ambiente virtual nao encontrado em .venv
  echo Execute: python -m venv .venv
  exit /b 1
)

if not "%~1"=="" (
  call :run_video "%~1" %2 %3 %4 %5 %6 %7 %8 %9
)

:menu
echo.
echo ================== ASCII VIDEO PLAYER ==================
echo Arraste e solte um video aqui, ou escolha uma opcao:
echo.
echo [1] Rodar bad_apple.mp4 (padrao)
echo [2] Escolher video da pasta
echo [3] Colar caminho completo manualmente
echo [Q] Sair
echo.
set /p "OPT=Opcao: "

if /I "%OPT%"=="Q" exit /b 0
if "%OPT%"=="1" (
  if exist "%SCRIPT_DIR%bad_apple.mp4" (
    call :run_video "%SCRIPT_DIR%bad_apple.mp4"
    goto :menu
  )
  echo [ERRO] bad_apple.mp4 nao encontrado.
  goto :menu
)
if "%OPT%"=="2" (
  call :choose_from_folder
  goto :menu
)
if "%OPT%"=="3" (
  set /p "MANUAL_PATH=Cole o caminho do video: "
  if "%MANUAL_PATH%"=="" (
    echo [ERRO] Caminho vazio.
    goto :menu
  )
  call :run_video "%MANUAL_PATH%"
  goto :menu
)

rem Se o usuario colar/arrastar caminho diretamente no prompt de opcao.
if exist "%OPT%" (
  call :run_video "%OPT%"
  goto :menu
)

echo [ERRO] Opcao invalida.
goto :menu

:choose_from_folder
set /a COUNT=0
for %%F in ("*.mp4" "*.mkv" "*.avi" "*.mov" "*.webm") do (
  if exist "%%~fF" (
    set /a COUNT+=1
    set "VID_!COUNT!=%%~fF"
    echo [!COUNT!] %%~nxF
  )
)

if %COUNT% EQU 0 (
  echo [ERRO] Nenhum video encontrado na pasta atual.
  exit /b 0
)

set /p "IDX=Digite o numero do video: "
if "%IDX%"=="" (
  echo [ERRO] Numero vazio.
  exit /b 0
)

set "CHOSEN=!VID_%IDX%!"
if not defined CHOSEN (
  echo [ERRO] Numero invalido.
  exit /b 0
)

call :run_video "!CHOSEN!"
exit /b %errorlevel%

:run_video
set "VIDEO_PATH=%~1"
if not exist "%VIDEO_PATH%" (
  echo [ERRO] Video nao encontrado: %VIDEO_PATH%
  exit /b 1
)

"%PYTHON_EXE%" "%PLAYER%" --video "%VIDEO_PATH%" --width 0 --fps 30 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

endlocal
