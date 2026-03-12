@echo off
REM ======================================================================
REM Qlib Data Conversion Script (CSV to BIN)
REM ======================================================================

REM 1. Define script and directory paths
set SCRIPT_PATH=.\qlib-main\scripts\dump_bin.py
set DATA_PATH=.\qlib_source_csvs
set QLIB_DIR=.\qlib_data\my_custom_cn_data

REM 2. Define field configurations
set INCLUDE_FIELDS=open,high,low,close,volume,amount,vwap,factor
set SYMBOL_FIELD=symbol
set DATE_FIELD=date

REM 3. Define the dump mode (e.g., dump_all, dump_update, dump_fix)
set DUMP_MODE=dump_all

REM ======================================================================
REM Execution Section
REM ======================================================================

echo [INFO] Starting Qlib data conversion process...
echo [INFO] Script Path : %SCRIPT_PATH%
echo [INFO] Source Dir  : %DATA_PATH%
echo [INFO] Target Dir  : %QLIB_DIR%
echo [INFO] Fields      : %INCLUDE_FIELDS%
echo.

REM Run the python command with variables
REM The caret symbol (^) is used for line continuation in Windows Batch
python "%SCRIPT_PATH%" %DUMP_MODE% ^
    --data_path "%DATA_PATH%" ^
    --qlib_dir "%QLIB_DIR%" ^
    --include_fields "%INCLUDE_FIELDS%" ^
    --symbol_field_name "%SYMBOL_FIELD%" ^
    --date_field_name "%DATE_FIELD%"

echo.
echo [INFO] Data conversion finished!
pause