@echo off
setlocal

cd /d "%~dp0"

set "APP_NAME=AutoCruiseCE"
set "SPEC_FILE=%~dp0AutoCruise.spec"
set "SETUP_SPEC_FILE=%~dp0AutoCruiseSetup.spec"
set "RELEASE_DIR=%~dp0release"
set "BUILD_ROOT=%~dp0build"
set "BUILD_DIR=%~dp0build\pyinstaller"

for /f %%i in ('python -c "import sys; sys.path.insert(0, r'%~dp0src'); from autocruise.version import APP_VERSION; print(APP_VERSION, end='') "') do set "APP_VERSION=%%i"
if "%APP_VERSION%"=="" set "APP_VERSION=1.3.0"

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

if exist "%RELEASE_DIR%\%APP_NAME%" (
  rmdir /s /q "%RELEASE_DIR%\%APP_NAME%"
)
if exist "%RELEASE_DIR%\AutoCruise" (
  rmdir /s /q "%RELEASE_DIR%\AutoCruise"
)
if exist "%RELEASE_DIR%\%APP_NAME%-portable-%APP_VERSION%.zip" (
  del /q "%RELEASE_DIR%\%APP_NAME%-portable-%APP_VERSION%.zip"
)
if exist "%RELEASE_DIR%\AutoCruiseSetup.exe" (
  del /q "%RELEASE_DIR%\AutoCruiseSetup.exe"
)
for %%F in ("%RELEASE_DIR%\AutoCruise-portable-*.zip") do (
  if exist "%%~fF" del /q "%%~fF"
)
if exist "%RELEASE_DIR%\installer" (
  rmdir /s /q "%RELEASE_DIR%\installer"
)

if exist "%BUILD_DIR%" (
  rmdir /s /q "%BUILD_DIR%"
)
if exist "%BUILD_ROOT%" (
  rmdir /s /q "%BUILD_ROOT%"
)

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo PyInstaller is not installed.
  echo Install it with: python -m pip install pyinstaller
  exit /b 1
)

if exist "%~dp0autocruise_logo.png" (
  echo Preparing application icon...
  python -c "from PySide6.QtGui import QImage; import sys; img=QImage(r'%~dp0autocruise_logo.png'); sys.exit(0 if (not img.isNull() and img.save(r'%~dp0autocruise_logo.ico')) else 1)"
  if errorlevel 1 (
    echo Failed to generate autocruise_logo.ico from autocruise_logo.png
    exit /b 1
  )
)

echo Building %APP_NAME%...
python -m PyInstaller --noconfirm --clean "%SPEC_FILE%" --distpath "%RELEASE_DIR%" --workpath "%BUILD_DIR%"
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

copy /Y "%~dp0README.md" "%RELEASE_DIR%\%APP_NAME%\README.md" >nul

echo Building AutoCruiseSetup...
python -m PyInstaller --noconfirm --clean "%SETUP_SPEC_FILE%" --distpath "%RELEASE_DIR%" --workpath "%BUILD_DIR%\setup"
if errorlevel 1 (
  echo Setup build failed.
  exit /b 1
)

copy /Y "%RELEASE_DIR%\AutoCruiseSetup.exe" "%RELEASE_DIR%\%APP_NAME%\AutoCruiseSetup.exe" >nul

echo Creating portable ZIP...
powershell -NoProfile -Command "Compress-Archive -Path '%RELEASE_DIR%\%APP_NAME%' -DestinationPath '%RELEASE_DIR%\%APP_NAME%-portable-%APP_VERSION%.zip' -Force"
if errorlevel 1 (
  echo Failed to create portable ZIP.
  exit /b 1
)

for /d /r "%~dp0" %%d in (__pycache__) do (
  if exist "%%d" rmdir /s /q "%%d"
)

if exist "%BUILD_DIR%" (
  rmdir /s /q "%BUILD_DIR%"
)
if exist "%BUILD_ROOT%" (
  rmdir /s /q "%BUILD_ROOT%"
)

echo.
echo Build completed.
echo Double-click this file to start:
echo %RELEASE_DIR%\%APP_NAME%\AutoCruiseCE.exe
echo Setup helper:
echo %RELEASE_DIR%\AutoCruiseSetup.exe
echo Portable package:
echo %RELEASE_DIR%\%APP_NAME%-portable-%APP_VERSION%.zip

exit /b 0
