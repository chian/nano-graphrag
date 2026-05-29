from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageFilter


FPS = 24
SIZE = (1280, 720)
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets" / "runway_plates"
GEN = ROOT / "generated" / "hybrid" / "opening_trial_v3"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


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


def draw_crown(draw: ImageDraw.ImageDraw, x: float, y: float, scale: float, opacity: int = 255) -> None:
    gold = (224, 180, 63, opacity)
    edge = (125, 86, 17, opacity)
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
    draw.polygon(pts, fill=gold, outline=edge, width=max(1, int(3 * scale)))
    for px, py in [(x - 42 * scale, y - 22 * scale), (x, y - 26 * scale), (x + 42 * scale, y - 22 * scale)]:
        draw.ellipse((px - 5 * scale, py - 5 * scale, px + 5 * scale, py + 5 * scale), fill=(245, 225, 155, opacity))


def draw_ripple(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, alpha: int) -> None:
    color = (190, 242, 255, alpha)
    draw.ellipse((cx - r, cy - r * 0.33, cx + r, cy + r * 0.33), outline=color, width=3)


def render_scene1():
    frames = GEN / "scene1_frames"
    frames.mkdir(parents=True, exist_ok=True)
    bg = Image.open(ASSETS / "01_eureka_myth_plate_v2.png").convert("RGBA")
    n = 5 * FPS
    for i in range(n):
        t = i / (n - 1)
        zoom = 1.0 + 0.05 * ease_out_cubic(t)
        frame = fit_crop(bg, SIZE, zoom=zoom, anchor=(0.48, 0.44)).convert("RGBA")
        overlay = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay, "RGBA")

        # highlight rim where overflow matters
        rim_pts = [(255, 430), (415, 413), (645, 413), (775, 426)]
        rim_alpha = 80 + int(90 * math.sin(min(1.0, t * 1.2) * math.pi))
        d.line(rim_pts, fill=(116, 209, 255, rim_alpha), width=5, joint="curve")

        # crown drop
        if t < 0.48:
            p = ease_out_cubic(t / 0.48)
            cx = 445
            cy = 150 + p * 230
            shadow = Image.new("RGBA", SIZE, (0, 0, 0, 0))
            ds = ImageDraw.Draw(shadow, "RGBA")
            draw_crown(ds, cx, cy + 8, 0.62, opacity=110)
            shadow = shadow.filter(ImageFilter.GaussianBlur(4))
            frame = Image.alpha_composite(frame, shadow)
            draw_crown(d, cx, cy, 0.62)
            d.line([(445, 125), (445, cy - 45)], fill=(255, 236, 170, 155), width=2)
        else:
            # impact flash
            impact_t = min(1.0, (t - 0.48) / 0.16)
            for j in range(3):
                rr = 30 + 55 * impact_t + j * 28
                draw_ripple(d, 443, 430, rr, max(0, 180 - j * 40 - int(impact_t * 80)))

        # overflow guides
        if t > 0.44:
            flow_t = min(1.0, (t - 0.44) / 0.56)
            xs = [235, 350, 515, 690]
            for idx, x in enumerate(xs):
                phase = max(0.0, flow_t - idx * 0.07)
                if phase <= 0:
                    continue
                y0 = 430 + 3 * math.sin(i / 4 + idx)
                y1 = 430 + 190 * ease_out_cubic(min(1.0, phase))
                d.line([(x, y0), (x - 6, y0 + 42), (x + 2, y1)], fill=(140, 219, 255, 180), width=6)
                d.line([(x, y0), (x - 2, y1)], fill=(220, 244, 255, 100), width=2)

        # small principle caption
        font = ImageFont.truetype(FONT_PATH, 28)
        box = (38, 36, 475, 118)
        d.rounded_rectangle(box, radius=18, fill=(9, 18, 27, 178), outline=(255, 255, 255, 30), width=1)
        d.text((58, 54), "Discovery begins when the effect becomes visible.", fill=(243, 237, 225, 235), font=font)

        out = Image.alpha_composite(frame, overlay).convert("RGB")
        out.save(frames / f"f_{i:04d}.png", quality=95)

    subprocess.run([
        "ffmpeg","-y","-framerate",str(FPS),"-i",str(frames / "f_%04d.png"),
        "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
        str(GEN / "01_archimedes_hybrid_v3.mp4")
    ], check=True)


def bubble(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int], tail: tuple[int, int], font):
    x0, y0, x1, y1 = rect
    draw.rounded_rectangle(rect, radius=22, fill=(255, 255, 255, 238), outline=(20, 20, 20, 220), width=3)
    tx, ty = tail
    if tx < x0:
        pts = [(x0 + 28, y1 - 18), (x0 + 52, y1 - 18), tail]
    elif tx > x1:
        pts = [(x1 - 52, y1 - 18), (x1 - 28, y1 - 18), tail]
    else:
        pts = [(tx - 14, y1 - 12), (tx + 14, y1 - 12), tail]
    draw.polygon(pts, fill=(255, 255, 255, 238), outline=(20, 20, 20, 220))
    draw.multiline_text((x0 + 18, y0 + 14), text, fill=(10, 10, 10, 255), font=font, spacing=2)


def render_scene2():
    frames = GEN / "scene2_frames"
    frames.mkdir(parents=True, exist_ok=True)
    bg = Image.open(ASSETS / "02_wegener_bubbles_plate_v3.png").convert("RGBA")
    n = 8 * FPS
    font = ImageFont.truetype(FONT_PATH, 31)
    small = ImageFont.truetype(FONT_PATH, 26)
    for i in range(n):
        t = i / (n - 1)
        zoom = 1.0 + 0.03 * ease_out_cubic(t)
        frame = fit_crop(bg, SIZE, zoom=zoom, anchor=(0.5, 0.46)).convert("RGBA")
        overlay = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay, "RGBA")

        # subtle spotlight on Wegener
        glow = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        dg = ImageDraw.Draw(glow, "RGBA")
        dg.ellipse((530, 70, 880, 470), fill=(255, 234, 170, 42))
        glow = glow.filter(ImageFilter.GaussianBlur(36))
        frame = Image.alpha_composite(frame, glow)

        # Wegener's claim bubble
        if t < 0.26:
            a = int(255 * ease_out_cubic(min(1.0, t / 0.08)))
            bubble(d, "It all fits!", (785, 110, 1095, 190), (875, 222), small)

        # audience responses
        if 0.22 < t < 0.50:
            bubble(d, "Fool!", (48, 132, 252, 210), (168, 268), font)
        if 0.46 < t < 0.76:
            bubble(d, "Continents don't move!", (908, 138, 1244, 246), (1130, 318), small)
        if t > 0.70:
            bubble(d, "No basis in reality.", (54, 478, 412, 566), (274, 620), small)

        # scene framing title
        box = (38, 36, 460, 114)
        d.rounded_rectangle(box, radius=18, fill=(9, 18, 27, 176), outline=(255, 255, 255, 30), width=1)
        d.text((58, 53), "A strong claim can still fail to persuade.", fill=(243, 237, 225, 235), font=ImageFont.truetype(FONT_PATH, 28))

        out = Image.alpha_composite(frame, overlay).convert("RGB")
        out.save(frames / f"f_{i:04d}.png", quality=95)

    subprocess.run([
        "ffmpeg","-y","-framerate",str(FPS),"-i",str(frames / "f_%04d.png"),
        "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
        str(GEN / "02_wegener_hybrid_v3.mp4")
    ], check=True)


def stitch_review():
    review = ROOT.parents[1] / "videos" / "instructional_gasl_fragments" / "review"
    review.mkdir(parents=True, exist_ok=True)
    concat = GEN / "concat_v3.txt"
    paths = [
        GEN / "01_archimedes_hybrid_v3.mp4",
        GEN / "02_wegener_hybrid_v3.mp4",
        ROOT / "generated" / "runway" / "opening_trial_v2" / "03_tharp_compilation_v1_gen4_turbo.mp4",
    ]
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in paths))
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),
        "-c:v","libx264","-preset","veryfast","-crf","22","-pix_fmt","yuv420p",
        str(review / "01_opening_hybrid_trial_v3.mp4")
    ], check=True)


def main():
    GEN.mkdir(parents=True, exist_ok=True)
    render_scene1()
    render_scene2()
    stitch_review()


if __name__ == "__main__":
    main()
