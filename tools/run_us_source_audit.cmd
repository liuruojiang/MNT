@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
if not "%~1"=="" set "TIINGO_DPAPI_FILE=%~1"
if not defined TIINGO_DPAPI_FILE (
  echo 请提供现有 Tiingo 加密凭证文件路径，不能填写密钥本身。
  echo 用法：run_us_source_audit.cmd "加密文件的完整路径"
  pause
  exit /b 2
)
python -B "%~dp0audit_us_sources.py" --tiingo-credential "%TIINGO_DPAPI_FILE%"
set "SOURCE_AUDIT_EXIT=%ERRORLEVEL%"
echo.
echo 本入口仅核验数据。退出码 2 表示仍有冲突或未覆盖项，不代表已修改策略。
pause
exit /b %SOURCE_AUDIT_EXIT%
