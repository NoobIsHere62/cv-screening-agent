@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Khong tim thay Python. Hay cai Python 3.10 tro len tai python.org roi chay lai.
    pause
    exit /b 1
)
python -c "import pydantic, pymupdf, pdfplumber, docx, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo Thieu thu vien. Hay chay lenh sau roi mo lai:
    echo     python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo Dang mo giao dien sang loc CV... (trinh duyet se tu mo). Dong cua so nay de tat.
python serve.py
if errorlevel 1 pause
