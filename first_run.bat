@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo Installing required libraries...
pip install pandas
pip install selenium
pip install webdriver-manager
pip install xlsxwriter
pip install openpyxl

echo Tkinter is usually included with Python. If you don't have it, install it manually.
echo Installing Tkinter (for Windows):
pip install tk

echo All libraries are installed.
pause
