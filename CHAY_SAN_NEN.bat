@echo off
rem Keo tha 1 hoac nhieu file DWG/DXF vao file nay
chcp 65001 >nul
set VENV=%LOCALAPPDATA%\SanNenPro\venv
if not exist "%VENV%\Scripts\python.exe" call "%~dp0CAI_DAT.bat"
if "%~1"=="" (echo Hay keo tha file DWG hoac DXF vao file nay. & pause & exit /b 1)
set TD=
set STEP=5
set K=1
set /p TD=Cao do thiet ke (Enter = doc tu layer TL-CDTK): 
set /p STEP=Buoc luoi m [5]: 
set /p K=He so K [1]: 
set ARG=--step %STEP% --k %K%
if not "%TD%"=="" set ARG=%ARG% --td %TD%
"%VENV%\Scripts\python.exe" "%~dp0sannen.py" %* %ARG%
pause
