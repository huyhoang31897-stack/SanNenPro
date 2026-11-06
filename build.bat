@echo off
rem Đóng gói SanNenPro.exe (chạy trên Windows có Python)
cd /d %~dp0
set PY=python
if exist ..\venv\Scripts\python.exe set PY=..\venv\Scripts\python.exe
%PY% -m pip install -q --disable-pip-version-check pyinstaller -r requirements.txt > build.log 2>&1
%PY% -m PyInstaller --noconfirm --clean --windowed --onedir --name SanNenPro --distpath dist --workpath build ^
  --hidden-import win32com.client --hidden-import pythoncom --hidden-import contourpy --hidden-import sannen3d ^
  --add-data "sannen3d_view.html;." ^
  --collect-data ezdxf --collect-submodules ezdxf.addons ^
  --exclude-module PyQt5 --exclude-module PySide6 --exclude-module IPython --exclude-module pytest --exclude-module pandas ^
  sannen_gui.py >> build.log 2>&1
echo BUILD_DONE >> build.log
