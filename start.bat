@echo off
cd /d "%~dp0"
python -c "import PIL, cv2, numpy" >nul 2>&1
if errorlevel 1 (
  echo Dependencies are required. Run: python -m pip install -r requirements.txt
  pause
  exit /b 1
)
python app.py
if errorlevel 1 pause
