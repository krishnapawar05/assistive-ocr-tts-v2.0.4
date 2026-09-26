#!/bin/bash
# Bash script to fix dependency conflicts (for Linux/Mac)
# Run: chmod +x fix_dependencies.sh && ./fix_dependencies.sh

echo "🔧 Fixing Python dependency conflicts..."

# Step 1: Remove corrupted numpy installation
echo ""
echo "1. Removing corrupted numpy installation..."
pip uninstall -y numpy 2>/dev/null
find ~/.local/lib/python*/site-packages -name "*umpy*" -type d -exec rm -rf {} + 2>/dev/null

# Step 2: Upgrade pip
echo ""
echo "2. Upgrading pip..."
python -m pip install --upgrade pip

# Step 3: Uninstall conflicting packages
echo ""
echo "3. Uninstalling conflicting packages..."
pip uninstall -y numpy scipy opencv-python TTS 2>/dev/null

# Step 4: Install numpy first (required by everything)
echo ""
echo "4. Installing numpy 1.22.0..."
pip install numpy==1.22.0

# Step 5: Install scipy compatible with numpy 1.22
echo ""
echo "5. Installing compatible scipy..."
pip install "scipy>=1.4.1,<1.12.0"

# Step 6: Install opencv-python compatible with numpy 1.22
echo ""
echo "6. Installing compatible opencv-python..."
pip install "opencv-python>=4.6.0,<4.12.0"

# Step 7: Install TTS
echo ""
echo "7. Installing TTS..."
pip install TTS==0.22.0

# Step 8: Install remaining requirements
echo ""
echo "8. Installing remaining requirements..."
pip install -r requirements.txt

echo ""
echo "✅ Dependency fix complete!"
echo ""
echo "Verifying installation..."
python -c "import numpy; import scipy; import cv2; import TTS; print(f'✅ numpy: {numpy.__version__}'); print(f'✅ scipy: {scipy.__version__}'); print(f'✅ opencv: {cv2.__version__}'); print(f'✅ TTS: {TTS.__version__}')"

