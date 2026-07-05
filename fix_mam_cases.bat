@echo off
echo ========================================
echo Fixing MAM Cases - Registration Numbers and Classification
echo ========================================
echo.

echo Step 1: Generating registration numbers...
python manage.py backfill_registration_numbers
echo.

echo Step 2: Classifying MAM types...
python manage.py backfill_mam_types
echo.

echo ========================================
echo DONE! Please refresh your browser (Ctrl+Shift+R)
echo ========================================
pause
