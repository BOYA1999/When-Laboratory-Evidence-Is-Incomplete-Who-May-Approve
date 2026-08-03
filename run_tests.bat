@echo off
"%~dp0.venv\Scripts\python.exe" -m pytest -q tests
if errorlevel 1 exit /b %errorlevel%
"%~dp0.venv\Scripts\python.exe" tests_smoke.py
