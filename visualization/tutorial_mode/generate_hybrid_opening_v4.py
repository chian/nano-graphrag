from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps


FPS = 24
SIZE = (1280, 720)
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets" / "runway_plates"
GEN = ROOT / "generated" / "hybrid" / "opening_trial_v4"
FONT_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def ease_out_cubic(t: float) -> float:
    return 1 - pow(1 - t, 3)


def fit_crop(img: Image.Image, size: tuple[int, int], zoom: float = 1.0, anchor=(0.5, 0.5)) -> Image.Image:
    tw, th = size
    iw, ih = img.size
    scale = max(tw / iw, th / ih) * zoom
    nw, nh = int(iw * scale), int(ih * scale)
    img2 = img.resize((nw, nh), Image.Resampling.LANCZOS)
    ax, ay = anchor
    left = int((nw - tw) * ax)
    top = int((nh - th) * ay)
    return img2.crop((left, top, left + tw, top + th))


def stylize_down(img: Image.Image) -> Image.Image:
    base = img.convert("RGB")
    # flatten detail
    small = base.resize((640, 360), Image.Resampling.BILINEAR)
    blown = small.resize(base.size, Image.Resampling.NEAREST)
    poster = ImageOps.posterize(blown, 3)
    edges = poster.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda x: 255 if x > 28 else 0)
    edges = ImageOps.invert(edges).filter(ImageFilter.GaussianBlur(0.6))
    poster_rgba = poster.convert("RGBA")
    outline = Image.new("RGBA", base.size, (0, 0, 0, 0))
    outline.putalpha(ImageOps.invert(edges).point(lambda x: min(255, int(x * 0.55))))
    return Image.blend(poster_rgba, outline, 0.22)


def draw_crown(draw: ImageDraw.ImageDraw, x: float, y: float, scale: float) -> None:
    fill = (243, 197, 74, 255)
    outline = (37, 20, 8, 255)
    pts = [
        (x - 58 * scale, y + 18 * scale),
        (x - 42 * scale, y - 22 * scale),
        (x - 18 * scale, y + 4 * scale),
        (x, y - 26 * scale),
        (x + 18 * scale, y + 4 * scale),
        (x + 42 * scale, y - 22 * scale),
        (x + 58 * scale, y + 18 * scale),
        (x + 58 * scale, y + 34 * scale),
        (x - 58 * scale, y + 34 * scale),
    ]
    draw.polygon(pts, fill=fill, outline=outline, width=max(1, int(4 * scale)))
    for px, py in [(x - 42 * scale, y - 22 * scale), (x, y - 26 * scale), (x + 42 * scale, y - 22 * scale)]:
        draw.ellipse((px - 6 * scale, py - 6 * scale, px + 6 * scale, py + 6 * scale), fill=(255, 231, 153, 255), outline=outline)


def draw_cartoon_overflow(draw: ImageDraw.ImageDraw, t: float, frame_idx: int) -> None:
    xs = [225, 340, 510, 680]
    for idx, x in enumerate(xs):
        phase = max(0.0, t - idx * 0.08)
        if phase <= 0:
            continue
        y0 = 430
        y1 = 430 + 178 * ease_out_cubic(min(1.0, phase))
        pts = [(x, y0), (x - 10, y0 + 34), (x + 8 * math.sin(frame_idx / 4 + idx), y1)]
        draw.line(pts, fill=(22, 34, 48, 255), width=10)
        draw.line(pts, fill=(147, 230, 255, 255), width=6)
        draw.ellipse((pts[-1][0] - 10, pts[-1][1] - 6, pts[-1][0] + 10, pts[-1][1] + 6), fill=(147, 230, 255, 255), outline=(22, 34, 48, 255))


def render_scene1():
    frames = GEN / "scene1_frames"
    frames.mkdir(parents=True, exist_ok=True)
    bg = Image.open(ASSETS / "01_eureka_myth_plate_v2.png").convert("RGBA")
    font = ImageFont.truetype(FONT_BOLD, 30)
    n = 5 * FPS
    for i in range(n):
        t = i / (n - 1)
        frame = fit_crop(bg, SIZE, zoom=1.01 + 0.02 * ease_out_cubic(t), anchor=(0.48, 0.44))
        frame = stylize_down(frame)
        overlay = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay, "RGBA")

        # crown drop
        if t < 0.46:
            p = ease_out_cubic(t / 0.46)
            cx = 452
            cy = 138 + p * 248
            draw_crown(d, cx, cy, 0.68)
            d.line([(cx, 116), (cx, cy - 48)], fill=(37, 20, 8, 160), width=2)
        else:
            impact = min(1.0, (t - 0.46) / 0.18)
            # cartoony splash rings
            for j in range(3):
                rr = 26 + 50 * impact + j * 24
                bbox = (442 - rr, 430 - rr * 0.28, 442 + rr, 430 + rr * 0.28)
                d.ellipse(bbox, outline=(22, 34, 48, max(0, 255 - j * 55 - int(impact * 60))), width=6)
                d.ellipse((bbox[0]+2,bbox[1]+2,bbox[2]-2,bbox[3]-2), outline=(147, 230, 255, max(0, 220 - j * 45 - int(impact * 60))), width=3)

        if t > 0.42:
            draw_cartoon_overflow(d, min(1.0, (t - 0.42) / 0.58), i)

        # simple caption matched to the lower-res style
        box = (34, 32, 508, 114)
        d.rounded_rectangle(box, radius=16, fill=(246, 230, 185, 220), outline=(37, 20, 8, 255), width=3)
        d.text((56, 54), "The effect has to be visible.", fill=(37, 20, 8, 255), font=font)

        out = Image.alpha_composite(frame, overlay).convert("RGB")
        out.save(frames / f"f_{i:04d}.png", quality=95)

    subprocess.run([
        "ffmpeg","-y","-framerate",str(FPS),"-i",str(frames / "f_%04d.png"),
        "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
        str(GEN / "01_archimedes_hybrid_v4.mp4")
    ], check=True)


def speech_bubble(layer: Image.Image, text: str, rect: tuple[int, int, int, int], mouth: tuple[int, int], align: str = "left") -> None:
    x0, y0, x1, y1 = rect
    draw = ImageDraw.Draw(layer, "RGBA")
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow, "RGBA")
    # richer bubble styling
    ds.rounded_rectangle((x0+6, y0+8, x1+6, y1+8), radius=26, fill=(0, 0, 0, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    layer.alpha_composite(shadow)

    fill = (255, 251, 241, 245)
    outline = (84, 62, 38, 255)
    draw.rounded_rectangle(rect, radius=26, fill=fill, outline=outline, width=3)

    mx, my = mouth
    # better-tail geometry from speaker mouth to nearest bubble edge
    if mx < x0:
        p1, p2 = (x0 + 34, y1 - 24), (x0 + 58, y1 - 18)
    elif mx > x1:
        p1, p2 = (x1 - 58, y1 - 18), (x1 - 34, y1 - 24)
    else:
        p1, p2 = (mx - 12, y1 - 10), (mx + 12, y1 - 10)
    draw.polygon([p1, p2, mouth], fill=fill, outline=outline)

    font = ImageFont.truetype(FONT_BOLD if len(text) < 10 else FONT_SANS, 28 if len(text) < 20 else 24)
    tw = x0 + 18
    draw.multiline_text((tw, y0 + 16), text, fill=(30, 23, 17, 255), font=font, spacing=3, align=align)


def render_scene2():
    frames = GEN / "scene2_frames"
    frames.mkdir(parents=True, exist_ok=True)
    bg = Image.open(ASSETS / "02_wegener_bubbles_plate_v3.png").convert("RGBA")
    title_font = ImageFont.truetype(FONT_BOLD, 28)
    n = 8 * FPS
    for i in range(n):
        t = i / (n - 1)
        frame = fit_crop(bg, SIZE, zoom=1.0 + 0.02 * ease_out_cubic(t), anchor=(0.5, 0.46)).convert("RGBA")
        overlay = Image.new("RGBA", SIZE, (0, 0, 0, 0))

        # title card
        d = ImageDraw.Draw(overlay, "RGBA")
        box = (36, 32, 438, 112)
        d.rounded_rectangle(box, radius=18, fill=(255, 249, 237, 220), outline=(84, 62, 38, 255), width=3)
        d.text((58, 54), "A claim can be clear and still not land.", fill=(37, 20, 8, 255), font=title_font)

        # Wegener claim bubble, tail to his mouth
        if t < 0.28:
            speech_bubble(overlay, "It all fits!", (790, 104, 1100, 190), (884, 241), align="center")

        # Better-positioned audience bubbles with mouth anchoring
        if 0.24 < t < 0.54:
            speech_bubble(overlay, "Fool!", (62, 122, 238, 206), (112, 332), align="center")
        if 0.44 < t < 0.80:
            speech_bubble(overlay, "Continents don't move!", (874, 126, 1242, 228), (1110, 520), align="center")
        if t > 0.70:
            speech_bubble(overlay, "No basis\nin reality.", (52, 470, 312, 578), (86, 385), align="center")

        out = Image.alpha_composite(frame, overlay).convert("RGB")
        out.save(frames / f"f_{i:04d}.png", quality=95)

    subprocess.run([
        "ffmpeg","-y","-framerate",str(FPS),"-i",str(frames / "f_%04d.png"),
        "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
        str(GEN / "02_wegener_hybrid_v4.mp4")
    ], check=True)


def stitch_review():
    review = ROOT.parents[1] / "videos" / "instructional_gasl_fragments" / "review"
    review.mkdir(parents=True, exist_ok=True)
    concat = GEN / "concat_v4.txt"
    paths = [
        GEN / "01_archimedes_hybrid_v4.mp4",
        GEN / "02_wegener_hybrid_v4.mp4",
        ROOT / "generated" / "runway" / "opening_trial_v2" / "03_tharp_compilation_v1_gen4_turbo.mp4",
    ]
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in paths))
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),
        "-c:v","libx264","-preset","veryfast","-crf","22","-pix_fmt","yuv420p",
        str(review / "01_opening_hybrid_trial_v4.mp4")
    ], check=True)


def main():
    GEN.mkdir(parents=True, exist_ok=True)
    render_scene1()
    render_scene2()
    stitch_review()


if __name__ == "__main__":
    main()
