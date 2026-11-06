@echo off
rem Cai moi truong Python cho SanNenPro (chi can chay 1 lan)
set VENV=%LOCALAPPDATA%\SanNenPro\venv
python -m venv "%VENV%" || (echo Khong tim thay Python & pause & exit /b 1)
"%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "%~dp0requirements.txt" || (pause & exit /b 1)
echo Cai dat xong.
pause
