#!/usr/bin/env python
"""
Quick verification script to check if OCR dependencies are properly installed.
"""
import sys

print("=" * 60)
print("OCR Dependencies Verification")
print("=" * 60)

# Check PaddleOCR and PaddlePaddle
print("\n[1/2] Checking PaddleOCR and PaddlePaddle...")
try:
    import paddle
    print(f"   ✅ PaddlePaddle version: {paddle.__version__}")
    from paddleocr import PaddleOCR
    print("   ✅ PaddleOCR module imported successfully")
    print("   ✅ PaddleOCR and PaddlePaddle are ready!")
except ImportError as e:
    print(f"   ❌ Error: {e}")
    print("   Install with: pip install paddleocr paddlepaddle")
    sys.exit(1)

# Check Transformers (TrOCR)
print("\n[2/2] Checking Transformers (TrOCR)...")
try:
    import transformers
    print(f"   ✅ Transformers version: {transformers.__version__}")
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    print("   ✅ TrOCR modules imported successfully")
    print("   ✅ Transformers (TrOCR) is ready!")
except ImportError as e:
    print(f"   ❌ Error: {e}")
    print("   Install with: pip install transformers torch")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ All OCR dependencies are properly installed!")
print("=" * 60)
print("\nYou can now restart the application and both PaddleOCR and TrOCR should initialize.")

