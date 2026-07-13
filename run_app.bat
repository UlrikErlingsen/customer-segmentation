@echo off
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash requirements.txt -Algorithm SHA256).Hash.ToLower()"') do set REQ_HASH=%%H
if not exist .venv\.segmentsignal-requirements-%REQ_HASH% (
  echo First launch: downloading packages. Later launches will be faster.
  python -m pip --disable-pip-version-check install --prefer-binary -r requirements.txt
  del /q .venv\.segmentsignal-requirements-* .venv\.segmentsignal-ready 2>nul
  type nul > .venv\.segmentsignal-requirements-%REQ_HASH%
)
python -m streamlit run app.py --server.headless=false --server.address=127.0.0.1 --server.maxUploadSize=200 --server.fileWatcherType=none --browser.gatherUsageStats=false
