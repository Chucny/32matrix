@echo off
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
py -3 -m 32matrix %*
exit /b %ERRORLEVEL%
