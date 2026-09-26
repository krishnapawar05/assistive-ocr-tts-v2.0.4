# PowerShell script to fix dependency conflicts
# Run this script to clean up and reinstall dependencies properly

Write-Host "🔧 Fixing Python dependency conflicts..." -ForegroundColor Cyan

# Step 1: Remove corrupted numpy installation
Write-Host "`n1. Removing corrupted numpy installation..." -ForegroundColor Yellow
pip uninstall -y numpy 2>$null
Remove-Item -Path "$env:LOCALAPPDATA\Programs\Python\Python310\Lib\site-packages\*-umpy*" -ErrorAction SilentlyContinue
Remove-Item -Path "$env:LOCALAPPDATA\Programs\Python\Python310\Lib\site-packages\*-umpy.dist-info" -Recurse -ErrorAction SilentlyContinue

# Step 2: Upgrade pip
Write-Host "`n2. Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip

# Step 3: Uninstall conflicting packages
Write-Host "`n3. Uninstalling conflicting packages..." -ForegroundColor Yellow
pip uninstall -y numpy scipy opencv-python TTS 2>$null

# Step 4: Install numpy first (required by everything)
Write-Host "`n4. Installing numpy 1.22.0..." -ForegroundColor Yellow
pip install numpy==1.22.0

# Step 5: Install scipy compatible with numpy 1.22
Write-Host "`n5. Installing compatible scipy..." -ForegroundColor Yellow
pip install "scipy>=1.4.1,<1.12.0"

# Step 6: Install opencv-python compatible with numpy 1.22
Write-Host "`n6. Installing compatible opencv-python..." -ForegroundColor Yellow
pip install "opencv-python>=4.6.0,<4.12.0"

# Step 7: Install TTS
Write-Host "`n7. Installing TTS..." -ForegroundColor Yellow
pip install TTS==0.22.0

# Step 8: Install remaining requirements
Write-Host "`n8. Installing remaining requirements..." -ForegroundColor Yellow
pip install -r requirements.txt

Write-Host "`n✅ Dependency fix complete!" -ForegroundColor Green
Write-Host "`nVerifying installation..." -ForegroundColor Cyan
python -c "import numpy; import scipy; import cv2; import TTS; print(f'✅ numpy: {numpy.__version__}'); print(f'✅ scipy: {scipy.__version__}'); print(f'✅ opencv: {cv2.__version__}'); print(f'✅ TTS: {TTS.__version__}')"

