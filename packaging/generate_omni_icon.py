"""Render the Omni logo mark into the app icon set (.ico + PNG sizes).

Purpose: turns the committed logo geometry (apps/ui/src/components/
omni-mark.tsx — one ring, six segments: r=38, stroke 11, dasharray
29.8/9.99, rotated -8deg, ink #0A0A0A) into the icon files Tauri and
PyInstaller consume. Build-time tool only — Pillow is an analysis/build
dependency, never a runtime one (run via `uv run --no-project --with
pillow python packaging/generate_omni_icon.py`).
Pipeline position: run manually (or in CI) before `tauri build` /
`pyinstaller`; outputs land in apps/ui/src-tauri/icons/ and packaging/.

No security surface: pure local rendering, no input, no network.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

# --- Exact geometry from omni-mark.tsx (viewBox 0 0 100 100) ----------------
VIEWBOX = 100.0
CENTER = 50.0
RADIUS = 38.0
STROKE = 11.0
DASH_ON = 29.8
DASH_OFF = 9.99
ROTATION_DEG = -8.0
INK = (10, 10, 10, 255)  # --ink: #0A0A0A
SEGMENTS = 6

# Render supersampled then downscale for clean anti-aliased arcs.
SUPERSAMPLE = 1024

REPO_ROOT = Path(__file__).resolve().parent.parent
TAURI_ICONS_DIR = REPO_ROOT / "apps" / "ui" / "src-tauri" / "icons"
PACKAGING_DIR = REPO_ROOT / "packaging"


def render_mark(canvas_px: int) -> Image.Image:
    """Render the six-segment ring at `canvas_px` square, transparent bg."""
    scale = SUPERSAMPLE / VIEWBOX
    image = Image.new("RGBA", (SUPERSAMPLE, SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # SVG dasharray walks the circumference from angle 0 (3 o'clock, going
    # clockwise in screen coords) with the whole circle rotated -8deg.
    circumference = 2.0 * math.pi * RADIUS
    dash_angle_on = (DASH_ON / circumference) * 360.0
    dash_angle_off = (DASH_OFF / circumference) * 360.0

    # PIL arcs: bounding box of the CENTERLINE circle; width strokes evenly
    # about it only if we use the outer circle box and matching width.
    outer_r = (RADIUS + STROKE / 2.0) * scale
    inner_r = (RADIUS - STROKE / 2.0) * scale
    center = CENTER * scale
    box = (center - outer_r, center - outer_r, center + outer_r, center + outer_r)
    width_px = round(outer_r - inner_r)

    start = ROTATION_DEG
    for _ in range(SEGMENTS):
        draw.arc(box, start=start, end=start + dash_angle_on, fill=INK, width=width_px)
        start += dash_angle_on + dash_angle_off

    return image.resize((canvas_px, canvas_px), Image.LANCZOS)


def main() -> None:
    """Write the Tauri icon set + the PyInstaller .ico."""
    TAURI_ICONS_DIR.mkdir(parents=True, exist_ok=True)

    # Tauri PNG set (transparent background, per Tauri icon conventions).
    render_mark(32).save(TAURI_ICONS_DIR / "32x32.png")
    render_mark(128).save(TAURI_ICONS_DIR / "128x128.png")
    render_mark(256).save(TAURI_ICONS_DIR / "128x128@2x.png")
    render_mark(512).save(TAURI_ICONS_DIR / "icon.png")

    # Multi-size .ico shared by the Tauri bundle and the engine exe resource.
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base = render_mark(256)
    base.save(TAURI_ICONS_DIR / "icon.ico", sizes=ico_sizes)
    base.save(PACKAGING_DIR / "omni-engine.ico", sizes=ico_sizes)

    print(f"wrote icons to {TAURI_ICONS_DIR} and {PACKAGING_DIR / 'omni-engine.ico'}")


if __name__ == "__main__":
    main()
