@echo off
set URL=https://imtheo.lol/Offsets/Offsets.json
set FILE=Update\Offsets.py

if not exist Update mkdir Update

echo Updating offsets...

powershell -Command "Invoke-WebRequest -Uri '%URL%' -UseBasicParsing | Select-Object -ExpandProperty Content | Set-Content '%FILE%'"

echo Done!
pause
