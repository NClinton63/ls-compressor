"""Generate the LS Compressor application icon and its platform variants."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw

BACKGROUND_COLOR = (36, 36, 41, 255)
TEAL_COLOR = (95, 138, 140, 255)
DARK_COLOR = (26, 26, 30, 255)
SOURCE_SIZE = 1024
BACKGROUND_RADIUS = 200
OUTER_CIRCLE_RADIUS = 340
INNER_CIRCLE_RADIUS = 240
CENTER_DOT_RADIUS = 100


def _centered_box(center: int, radius: int) -> tuple[int, int, int, int]:
    """Return an ellipse bounding box centered at ``center`` with ``radius``."""
    return (center - radius, center - radius, center + radius, center + radius)


def create_icon_image(size: int) -> Image.Image:
    """Render the LS Compressor icon at ``size`` x ``size`` pixels."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    scale = size / SOURCE_SIZE
    radius = int(BACKGROUND_RADIUS * scale)
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=radius,
        fill=BACKGROUND_COLOR,
    )

    center = size // 2
    outer = int(OUTER_CIRCLE_RADIUS * scale)
    inner = int(INNER_CIRCLE_RADIUS * scale)
    dot = int(CENTER_DOT_RADIUS * scale)

    draw.ellipse(_centered_box(center, outer), fill=TEAL_COLOR)
    draw.ellipse(_centered_box(center, inner), fill=DARK_COLOR)
    draw.ellipse(_centered_box(center, dot), fill=TEAL_COLOR)

    return image


def write_svg(path: Path) -> None:
    """Write a vector source for the LS Compressor icon."""
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SOURCE_SIZE} {SOURCE_SIZE}">
  <rect
    width="{SOURCE_SIZE}"
    height="{SOURCE_SIZE}"
    rx="{BACKGROUND_RADIUS}"
    fill="#242429"
  />
  <circle
    cx="{SOURCE_SIZE // 2}"
    cy="{SOURCE_SIZE // 2}"
    r="{OUTER_CIRCLE_RADIUS}"
    fill="#5f8a8c"
  />
  <circle
    cx="{SOURCE_SIZE // 2}"
    cy="{SOURCE_SIZE // 2}"
    r="{INNER_CIRCLE_RADIUS}"
    fill="#1a1a1e"
  />
  <circle
    cx="{SOURCE_SIZE // 2}"
    cy="{SOURCE_SIZE // 2}"
    r="{CENTER_DOT_RADIUS}"
    fill="#5f8a8c"
  />
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def generate_pngs(sizes: Sequence[int]) -> dict[int, Image.Image]:
    """Render the icon at each requested size and return a size-to-image map."""
    base = create_icon_image(SOURCE_SIZE)
    result: dict[int, Image.Image] = {SOURCE_SIZE: base}
    for size in sizes:
        if size == SOURCE_SIZE:
            continue
        result[size] = base.resize(
            (size, size),
            Image.Resampling.LANCZOS,
        )
    return result


def generate_ico(pngs: dict[int, Image.Image], path: Path) -> None:
    """Write a multi-resolution Windows ``.ico`` file from the supplied PNGs."""
    ordered_sizes = [size for size in (256, 128, 64, 48, 32, 24, 16) if size in pngs]
    images = [pngs[size].convert("RGBA") for size in ordered_sizes]
    if not images:
        raise ValueError("No icon sizes provided for .ico output")
    images[0].save(
        path,
        format="ICO",
        append_images=images[1:],
        sizes=[(size, size) for size in ordered_sizes],
    )


def generate_icns(
    pngs: dict[int, Image.Image],
    output_path: Path,
    iconset_dir: Path | None = None,
) -> None:
    """Build a macOS ``.icns`` file from the supplied PNGs using ``iconutil``."""
    if sys.platform != "darwin":
        raise RuntimeError(".icns generation is only supported on macOS")

    if iconutil_path := shutil.which("iconutil"):
        iconutil = Path(iconutil_path)
    else:
        raise FileNotFoundError("iconutil is required to build .icns files")

    work_dir = Path(iconset_dir) if iconset_dir else Path(tempfile.mkdtemp())
    iconset = work_dir / "AppIcon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)

    required = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for size, name in required:
        if size not in pngs:
            raise ValueError(f"Missing required icon size {size}px for .icns")
        pngs[size].save(iconset / name, format="PNG")

    try:
        subprocess.run(
            [str(iconutil), "-c", "icns", str(iconset), "-o", str(output_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        if iconset_dir is None:
            shutil.rmtree(iconset, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the application icon assets from the source geometry."""
    parser = argparse.ArgumentParser(description="Generate LS Compressor icon assets")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets",
        help="directory to write generated icon files",
    )
    args = parser.parse_args(argv)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
    pngs = generate_pngs(sizes)

    write_svg(output_dir / "icon.svg")
    pngs[SOURCE_SIZE].save(output_dir / "icon.png", format="PNG")
    generate_ico(pngs, output_dir / "icon.ico")

    if sys.platform == "darwin":
        generate_icns(pngs, output_dir / "icon.icns")
    else:
        print("Skipping .icns generation: iconutil is only available on macOS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
