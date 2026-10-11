@echo off
title BloodLink AI Server
echo ========================================================
echo        Starting BloodLink AI Platform...
echo ========================================================
echo.

python -m pip install -r requirements.txt
python run.py

pause
