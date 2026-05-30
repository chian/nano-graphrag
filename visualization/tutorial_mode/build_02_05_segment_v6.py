from pathlib import Path
import shutil
import subprocess
import tempfile
from PIL import Image

ROOT = Path("/home/chia/repos/nano-graphrag/videos/instructional_gasl_fragments")
REVIEW = ROOT / "REVIEW_CURRENT"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
QUESTION = "What are the key factors that drive urban heat islands?"

SEQ = [
    ("card", "Why some answers are more trustworthy than others",
     "This segment shows how different systems handle the same question, and why organized evidence changes the answer.",
     4.0, None, None, None),
    ("question", "Question", QUESTION, 5.0, None, None, None),
    ("still", "Classic systems are precise and efficient",
     "They work best when the world already fits the slots they expect.",
     5.8, ROOT / "ASSETS/source_plates/stop_motion_parallel/classic_system_actor_v2.png", (0, 0, 1672, 941), None),
    ("still", "But some things do not fit anywhere obvious",
     "The dinosaur is tried against the system, and the system does not know what to do with it.",
     5.8, ROOT / "ASSETS/source_plates/stop_motion_parallel/classic_system_attempt_v1.png", (0, 0, 1672, 941), None),
    ("still", "When the fit fails, the uncertainty becomes visible",
     "That is the limit of rigid precision when the question outruns the categories.",
     4.8, ROOT / "ASSETS/source_plates/stop_motion_parallel/classic_system_actor_v2.png", (0, 480, 780, 941), None),
    ("video", "LLM-only can take the question in easily",
     "It does not need the world to arrive in fixed categories first.",
     5.3, ROOT / "ASSETS/runway/asset_sweep_v2/text_to_video/stop_motion_paper_prompt_enters_field_veo3_1_fast.mp4", None, 1.32),
    ("video", "But support still has to be assembled",
     "An appealing answer is not enough when the backing remains incomplete.",
     5.3, ROOT / "ASSETS/runway/asset_sweep_v2/text_to_video/stop_motion_paper_support_gaps_reveal_veo3_1_fast.mp4", None, 1.32),
    ("video", "RAG improves access by retrieving a targeted slice",
     "That is real progress over asking the model to ingest everything.",
     6.0, ROOT / "ASSETS/runway/final_segment_missing_beats_v1/rag_actor_v1_gen4_5.mp4", None, 1.00),
    ("still", "But a slice is still only a slice",
     "The selected support can still be partial, skewed, or missing key pieces.",
     4.8, ROOT / "ASSETS/source_plates/stop_motion_parallel/rag_actor_v1.png", (0, 0, 1672, 941), None),
    ("video", "GASL begins by making the evidence sortable",
     "It does not answer first. It organizes the material so the support can be inspected.",
     5.5, ROOT / "ASSETS/runway/gasl_realvideo_search_v1/state1_sort_begin_v2_i2v.mp4", None, 0.92),
    ("video", "Then the right pieces go into the right boxes",
     "The organization remains visible instead of disappearing behind the answer.",
     5.5, ROOT / "ASSETS/runway/gasl_realvideo_search_v1/state2_sorting_v2_i2v.mp4", None, 0.92),
    ("video", "Answer views make the support legible before the answer",
     "Only after that compilation step does the final answer arrive.",
     5.5, ROOT / "ASSETS/runway/gasl_realvideo_search_v1/state3_answerviews_v1_i2v.mp4", None, 0.92),
    ("card", "Organized evidence changes the answer",
     "Not a louder claim. A more scientific mode of work.",
     3.8, None, None, None),
]


def ff(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_card(title, subtitle, out, dur):
    ff([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x0A0D14:s=1280x720:d={dur}",
        "-vf",
        f"drawtext=fontfile={FONT_B}:text='{title}':x=(w-text_w)/2:y=270:fontsize=36:fontcolor=white,"
        f"drawtext=fontfile={FONT_R}:text='{subtitle}':x=(w-text_w)/2:y=340:fontsize=21:fontcolor=0xE8E1D7",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    ])


def make_question(out, dur):
    src = ROOT / "ASSETS/source_plates/stop_motion_parallel/classic_system_attempt_v1.png"
    img = Image.open(src).crop((0, 180, 450, 700))
    temp = out.with_suffix(".png")
    img.save(temp)
    vf = (
        f"zoompan=z='min(zoom+0.0001,1.02)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(dur*30)}:s=1280x720:fps=30,"
        f"drawbox=x=60:y=80:w=1160:h=110:color=0x000000@0.32:t=fill,"
        f"drawtext=fontfile={FONT_B}:text='Question':x=90:y=98:fontsize=28:fontcolor=0xF8AB70,"
        f"drawtext=fontfile={FONT_R}:text='{QUESTION}':x=90:y=140:fontsize=28:fontcolor=white"
    )
    ff(["ffmpeg", "-y", "-loop", "1", "-i", str(temp), "-vf", vf, "-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out)])
    temp.unlink(missing_ok=True)


def stylize_video(src, title, subtitle, out, dur, speed):
    vf = (
        f"setpts={speed}*PTS,scale=1280:720,"
        f"drawbox=x=40:y=52:w=1200:h=70:color=0x000000@0.32:t=fill,"
        f"drawtext=fontfile={FONT_R}:text='Question':x=60:y=76:fontsize=24:fontcolor=0xF8AB70,"
        f"drawtext=fontfile={FONT_R}:text='{QUESTION}':x=170:y=76:fontsize=24:fontcolor=white,"
        f"drawbox=x=22:y=626:w=1236:h=70:color=0x000000@0.45:t=fill,"
        f"drawtext=fontfile={FONT_B}:text='{title}':x=44:y=642:fontsize=26:fontcolor=white,"
        f"drawtext=fontfile={FONT_R}:text='{subtitle}':x=44:y=672:fontsize=18:fontcolor=0xE8E1D7"
    )
    ff(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(src), "-vf", vf, "-t", str(dur), "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out)])


def still_to_video(src, title, subtitle, out, dur, crop):
    im = Image.open(src)
    if crop:
        im = im.crop(crop)
    temp = out.with_suffix(".png")
    im.save(temp)
    vf = (
        f"zoompan=z='min(zoom+0.00045,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(dur*30)}:s=1280x720:fps=30,"
        f"drawbox=x=40:y=52:w=1200:h=70:color=0x000000@0.32:t=fill,"
        f"drawtext=fontfile={FONT_R}:text='Question':x=60:y=76:fontsize=24:fontcolor=0xF8AB70,"
        f"drawtext=fontfile={FONT_R}:text='{QUESTION}':x=170:y=76:fontsize=24:fontcolor=white,"
        f"drawbox=x=22:y=626:w=1236:h=70:color=0x000000@0.45:t=fill,"
        f"drawtext=fontfile={FONT_B}:text='{title}':x=44:y=642:fontsize=26:fontcolor=white,"
        f"drawtext=fontfile={FONT_R}:text='{subtitle}':x=44:y=672:fontsize=18:fontcolor=0xE8E1D7"
    )
    ff(["ffmpeg", "-y", "-loop", "1", "-i", str(temp), "-vf", vf, "-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out)])
    temp.unlink(missing_ok=True)


def main():
    work = Path(tempfile.mkdtemp(prefix="segment0205v6_"))
    try:
        parts = []
        for i, (kind, title, sub, dur, src, crop, speed) in enumerate(SEQ, start=1):
            out = work / f"p{i:02d}.mp4"
            if kind == "card":
                make_card(title, sub, out, dur)
            elif kind == "question":
                make_question(out, dur)
            elif kind == "video":
                stylize_video(src, title, sub, out, dur, speed)
            else:
                still_to_video(src, title, sub, out, dur, crop)
            parts.append(out)
        concat = work / "list.txt"
        concat.write_text("".join(f"file '{p}'\n" for p in parts))
        final = ROOT / "02_05_sequential_parallel_final_v6.mp4"
        ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(final)])
        review = REVIEW / "01_02_05_parallel_final_v6.mp4"
        shutil.copy2(final, review)
        (REVIEW / "README.md").write_text("1. 01_02_05_parallel_final_v6.mp4\n")
    finally:
        shutil.rmtree(work)


if __name__ == "__main__":
    main()
