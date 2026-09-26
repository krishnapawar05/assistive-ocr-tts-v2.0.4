@echo off
REM Install missing OCR dependencies for PaddleOCR and TrOCR
echo Installing OCR dependencies...
echo.

echo [1/2] Installing PaddleOCR and PaddlePaddle...
python -m pip install paddleocr paddlepaddle
if %errorlevel% neq 0 (
    echo ERROR: Failed to install PaddleOCR dependencies
    pause
    exit /b 1
)
echo.

echo [2/2] Installing Transformers and PyTorch for TrOCR...
python -m pip install transformers torch torchvision
if %errorlevel% neq 0 (
    echo ERROR: Failed to install TrOCR dependencies
    pause
    exit /b 1
)
echo.

echo ========================================
echo Installation complete!
echo ========================================
echo.
echo Please restart the application for changes to take effect.
pause

