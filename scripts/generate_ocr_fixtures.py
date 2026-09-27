"""Generate deterministic synthetic OCR fixtures into tests/fixtures/ocr/.

These images test that each engine FUNCTIONS (loads, reads, reports confidence). They are
not evidence of real-world accuracy: real classroom captures are still needed for that.

Latin text is drawn with Pillow. Hindi/Kannada need complex-script shaping, which this Pillow
build lacks (no raqm), so on Windows they are drawn with .NET GDI+ via PowerShell (Nirmala UI).

Run from repo root:  .venv/Scripts/python.exe scripts/generate_ocr_fixtures.py
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "fixtures", "ocr")
W, H = 1280, 720

# id, category, text, language, font, size, style
LATIN = [
    ("room_204", "signs", "Room 204", "en", "arialbd.ttf", 110, "clean"),
    ("exit_inverted", "signs", "EXIT", "en", "arialbd.ttf", 140, "inverted"),
    ("sentence", "printed", "The quick brown fox jumps over the lazy dog", "en", "arial.ttf", 48, "clean"),
    ("chapter_numbers", "printed", "Chapter 7 Page 132", "en", "arial.ttf", 60, "clean"),
    ("low_contrast", "printed", "Exit on the left", "en", "arial.ttf", 64, "low_contrast"),
    ("blurred", "printed", "Library closes at 5 PM", "en", "arial.ttf", 56, "blur"),
    ("greenboard", "classroom", "Photosynthesis\nLight energy to chemical energy", "en", "arial.ttf", 46, "board"),
    ("whiteboard", "classroom", "Homework due Friday\nRead pages 40 to 45", "en", "arial.ttf", 50, "whiteboard"),
    ("hand_meet", "handwritten", "Meet me at noon", "en", "Inkfree.ttf", 72, "clean"),
    ("hand_notes", "handwritten", "Revise chapter three", "en", "segoesc.ttf", 60, "clean"),
    ("blank", "degraded", "", "en", "arial.ttf", 40, "clean"),
    ("dark", "degraded", "Room 204", "en", "arialbd.ttf", 110, "dark"),
]

INDIC = [
    ("hindi_room", "multilingual", "कमरा संख्या 204", "hi"),
    ("hindi_welcome", "multilingual", "स्वागत है", "hi"),
    ("kannada_room", "multilingual", "ಕೊಠಡಿ ಸಂಖ್ಯೆ 204", "kn"),
    ("kannada_welcome", "multilingual", "ಸ್ವಾಗತ", "kn"),
]

# Scenes with NO text but text-like shapes (wall clock, light switch, chair slats, window grille).
# A camera frame like this made full-frame TrOCR invent "0 2 . 0 0", which was then spoken (ADR 0007).
# id -> objects (name, *geometry in px) drawn on a plain wall
SCENES = {
    "scene_clock_switch": (("clock", 780, 45, 18), ("switch", 590, 220)),
    "scene_room": (("clock", 300, 120, 18), ("switch", 590, 220), ("chair", 350, 460, 330, 260),
                   ("grille", 1010, 120, 60, 320)),
}

STYLES = {
    "clean": ((255, 255, 255), (0, 0, 0)),
    "blur": ((255, 255, 255), (0, 0, 0)),
    "inverted": ((20, 20, 20), (245, 245, 245)),
    "low_contrast": ((170, 170, 170), (120, 120, 120)),
    "board": ((30, 60, 30), (235, 235, 235)),
    "whiteboard": ((238, 240, 236), (20, 40, 140)),
    "dark": ((6, 6, 6), (14, 14, 14)),
}


def render_latin(text, font_file, size, style):
    bg, fg = STYLES[style]
    img = Image.new("RGB", (W, H), bg)
    if text:
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(font_file, size)
        box = draw.multiline_textbbox((0, 0), text, font=font, spacing=16)
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.multiline_text(((W - tw) // 2 - box[0], (H - th) // 2 - box[1]), text, font=font, fill=fg,
                            spacing=16, align="center")
    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    if style == "blur":
        frame = cv2.GaussianBlur(frame, (9, 9), 3)
    return frame


def render_scene(sid, objects):
    rng = np.random.default_rng(sum(map(ord, sid)))  # deterministic per scene
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (150, 205, 225)  # pale yellow wall (BGR)
    img = np.clip(img.astype(np.float32) + np.linspace(-15, 15, W)[None, :, None]
                  + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)

    def clock(cx, cy, r):
        cv2.circle(img, (cx, cy), r, (245, 245, 245), -1)
        cv2.circle(img, (cx, cy), r, (60, 60, 60), 3)
        for k in range(12):
            a = k * np.pi / 6
            p1 = (int(cx + 0.8 * r * np.sin(a)), int(cy - 0.8 * r * np.cos(a)))
            p2 = (int(cx + 0.95 * r * np.sin(a)), int(cy - 0.95 * r * np.cos(a)))
            cv2.line(img, p1, p2, (30, 30, 30), 2)
        cv2.line(img, (cx, cy), (cx + int(0.5 * r), cy - int(0.2 * r)), (20, 20, 20), 3)
        cv2.line(img, (cx, cy), (cx - int(0.1 * r), cy - int(0.7 * r)), (20, 20, 20), 2)

    def switch(x, y):
        cv2.rectangle(img, (x, y), (x + 60, y + 44), (240, 240, 240), -1)
        cv2.rectangle(img, (x, y), (x + 60, y + 44), (150, 150, 150), 1)
        for k in range(3):
            cv2.rectangle(img, (x + 8 + k * 17, y + 12), (x + 18 + k * 17, y + 24), (60, 60, 60), -1)

    def chair(x, y, w, h):
        cv2.rectangle(img, (x, y), (x + w, y + h), (40, 80, 190), -1)
        for i in range(1, 6):
            for j in range(4):
                cx, cy = x + i * (w // 6), y + 20 + j * (h - 40) // 4
                cv2.rectangle(img, (cx - 6, cy - 6), (cx + 6, cy + 6), (235, 235, 235), -1)

    def grille(x, y, w, h):
        cv2.rectangle(img, (x, y), (x + w, y + h), (200, 200, 200), -1)
        for gx in range(x, x + w, 16):
            cv2.line(img, (gx, y), (gx, y + h), (90, 90, 90), 3)
        for gy in range(y, y + h, 16):
            cv2.line(img, (x, gy), (x + w, gy), (90, 90, 90), 3)

    draw = {"clock": clock, "switch": switch, "chair": chair, "grille": grille}
    for name, *geometry in objects:
        draw[name](*geometry)
    return img


PS_RENDER = r"""
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap 1280, 720
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::White)
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$font = New-Object System.Drawing.Font('Nirmala UI', 72)
$fmt = New-Object System.Drawing.StringFormat
$fmt.Alignment = 'Center'; $fmt.LineAlignment = 'Center'
$rect = New-Object System.Drawing.RectangleF 0, 0, 1280, 720
$g.DrawString($env:SVA_TEXT, $font, [System.Drawing.Brushes]::Black, $rect, $fmt)
$bmp.Save($env:SVA_OUT, [System.Drawing.Imaging.ImageFormat]::Png)
"""


def render_indic(text, out_path):
    env = dict(os.environ, SVA_TEXT=text, SVA_OUT=out_path)
    subprocess.run(["powershell", "-NoProfile", "-Command", PS_RENDER], env=env, check=True)


def main():
    manifest = []
    for sid, cat, text, lang, font, size, style in LATIN:
        rel = f"{cat}/{sid}.png"
        os.makedirs(os.path.join(OUT, cat), exist_ok=True)
        cv2.imwrite(os.path.join(OUT, rel), render_latin(text, font, size, style))
        manifest.append({"id": sid, "path": rel, "category": cat, "language": lang,
                         "text": text.replace("\n", " "), "style": style, "synthetic": True})
    for sid, objects in SCENES.items():
        rel = f"scenes/{sid}.png"
        os.makedirs(os.path.join(OUT, "scenes"), exist_ok=True)
        cv2.imwrite(os.path.join(OUT, rel), render_scene(sid, objects))
        manifest.append({"id": sid, "path": rel, "category": "scenes", "language": "en", "text": "",
                         "style": "no_text", "synthetic": True, "objects": [o[0] for o in objects]})
    if os.name == "nt":
        for sid, cat, text, lang in INDIC:
            rel = f"{cat}/{sid}.png"
            os.makedirs(os.path.join(OUT, cat), exist_ok=True)
            render_indic(text, os.path.join(OUT, rel))
            manifest.append({"id": sid, "path": rel, "category": cat, "language": lang, "text": text,
                             "style": "clean", "synthetic": True})
    else:
        print("Skipping Hindi/Kannada fixtures: rendering needs Windows GDI+", file=sys.stderr)
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"note": "Synthetic images for engine functionality tests only; not accuracy evidence.",
                   "fixtures": manifest}, f, indent=2, ensure_ascii=False)
    print(f"wrote {len(manifest)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
