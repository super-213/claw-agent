"""Render the existing geometric house mark as PNGs. Requires Pillow locally."""
from pathlib import Path
from PIL import Image, ImageDraw


def render(size: int, maskable: bool = False) -> Image.Image:
    scale = 4
    canvas = Image.new('RGB', (size * scale, size * scale), '#2f6f73')
    draw = ImageDraw.Draw(canvas)
    inset = 0.15 if maskable else 0.05
    extent = size * scale * (1 - 2 * inset)
    offset = size * scale * inset

    def point(x, y):
        return offset + x / 128 * extent, offset + y / 128 * extent

    draw.polygon([point(30, 61.5), point(64, 33), point(98, 61.5), point(98, 105), point(30, 105)], fill='white')
    draw.rectangle([point(51, 73), point(77, 106)], fill='#2f6f73')
    draw.ellipse([point(70, 29), point(96, 55)], fill='#f2b84b')
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[1] / 'web-react' / 'public'
    for name, size, maskable in [('pwa-192.png', 192, False), ('pwa-512.png', 512, False), ('pwa-maskable-512.png', 512, True), ('apple-touch-icon.png', 180, False)]:
        render(size, maskable).save(target / name)
