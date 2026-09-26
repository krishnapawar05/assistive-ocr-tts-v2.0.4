#!/bin/bash
# Install missing OCR dependencies for PaddleOCR and TrOCR

echo "Installing OCR dependencies..."
echo ""

echo "[1/2] Installing PaddleOCR and PaddlePaddle..."
python -m pip install paddleocr paddlepaddle
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install PaddleOCR dependencies"
    exit 1
fi
echo ""

echo "[2/2] Installing Transformers and PyTorch for TrOCR..."
python -m pip install transformers torch torchvision
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install TrOCR dependencies"
    exit 1
fi
echo ""

echo "========================================"
echo "Installation complete!"
echo "========================================"
echo ""
echo "Please restart the application for changes to take effect."

