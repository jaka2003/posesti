@echo off
REM Launcher za Windows Task Scheduler. Zazene monitor.py v projektni mapi.
cd /d "%~dp0"
"C:\Users\Jaka\AppData\Local\Programs\Python\Python314\python.exe" monitor.py >> run.log 2>&1
