# Runway setup and first-shot package for the GASL opening fragment

This guide is intentionally scoped to the **tutorial workspace only**. It does
not modify the shared demo pipeline. The goal is to get just enough Runway API
in place to prototype the first three opening shots:

1. Eureka myth shot
2. Wegener claim / stylized ridicule shot
3. Tharp compilation-at-the-desk shot

## Why Runway first

For this project, Runway is a strong fit because we need:

- image-to-video continuity from designed still plates
- repeatable shot generation in a hybrid pipeline
- a public API and SDK we can script against

Runway’s docs currently state:

- API auth uses a Bearer token
- the SDK expects the env var `RUNWAYML_API_SECRET`
- image-to-video uses the `/v1/image_to_video` endpoint
- the API version header must be `2024-11-06`

## Account and billing setup

1. Create or log in to a Runway account.
2. Open the Runway developer / API portal.
3. Add billing and purchase the minimum starting credits.
   - Runway’s setup docs say a **minimum payment of $10** is required to get
     started with the API.
4. Create an API key.
5. Keep the key ready for local environment configuration.

## Local environment variable

Use the exact env var expected by the official SDK:

```bash
export RUNWAYML_API_SECRET="your_runway_api_key_here"
```

If you want it persistent for the repo session:

```bash
echo 'export RUNWAYML_API_SECRET="your_runway_api_key_here"' >> ~/.bashrc
source ~/.bashrc
```

## Local Python package

When we are ready to call the API from this repo:

```bash
cd /home/chia/repos/nano-graphrag
.venv/bin/pip install runwayml
```

## Minimal connectivity test

Python:

```python
from runwayml import RunwayML

client = RunwayML()  # reads RUNWAYML_API_SECRET
print("Client created")
```

curl:

```bash
curl https://api.dev.runwayml.com/v1/image_to_video \
  -H "Authorization: Bearer $RUNWAYML_API_SECRET" \
  -H "Content-Type: application/json" \
  -H "X-Runway-Version: 2024-11-06" \
  -d '{
    "model": "gen4.5",
    "promptText": "A subtle test shot",
    "ratio": "1280:720",
    "duration": 5,
    "promptImage": [
      {
        "uri": "https://samplelib.com/lib/preview/jpeg/sample-city-park-400x300.jpg",
        "position": "first"
      }
    ]
  }'
```

## Shot strategy

We should **not** ask Runway to generate an entire finished instructional scene
from text only. For the opening fragment, we should use a hybrid method:

- design still plates ourselves
- feed those plates into Runway image-to-video
- ask Runway mainly for motion, camera, atmosphere, and temporal progression
- keep exact explanatory overlays in our own compositor

That gives us better continuity and more direct control over the tutorial.

## First three shot specs

### Shot 01: Eureka myth

Purpose:
- establish the popular myth of discovery as sudden insight

Input asset:
- one designed still plate: cartoon Archimedes-style silhouette, bath/tile
  background, bright idea flare, room for later title safe area

Runway mode:
- image-to-video

Model:
- `gen4.5` first, with `gen4_turbo` as fallback

Duration:
- 5 seconds

Aspect:
- `1280:720`

Prompt:
```text
A stylized editorial animation. The scene begins still, then a sudden spark of
insight flashes above the thinker. The character jolts upright with delighted
surprise, water ripples outward, and the camera performs a quick push-in to
heighten the mythic “eureka” feeling. Motion is clean, readable, and graphic,
with no extra characters or visual clutter.
```

Prompt notes:
- We want a **symbolic** result, not a realistic historical reconstruction.
- Ask for one strong action, not a long sequence.

Acceptance criteria:
- readable silhouette
- one clear insight gesture
- no surreal extra limbs or scene drift
- space remains usable for later overlays

### Shot 02: Wegener claim and ridicule

Purpose:
- make the bold-claim mode emotionally legible

Input asset:
- one designed still plate: Wegener portrait/figure at a podium, lecture hall,
  audience, puzzle-fit continent motif behind him

Runway mode:
- image-to-video

Model:
- `gen4.5`

Duration:
- 8 seconds

Aspect:
- `1280:720`

Prompt:
```text
A stylized editorial lecture scene. The speaker stands at the podium with calm,
bold confidence as the audience shifts from skepticism to exaggerated ridicule.
A few comic projectiles arc through the foreground like a visual metaphor rather
than literal realism. The camera begins with a respectful medium shot, then
slides slightly to reveal dismissive audience reactions. The motion should feel
sharp, readable, and theatrical rather than chaotic.
```

Prompt notes:
- ridicule should be **stylized**, not slapstick chaos
- we want visible audience skepticism, not a brawl
- a slight camera slide is better than frantic movement

Acceptance criteria:
- Wegener remains the visual anchor
- ridicule reads immediately
- audience remains recognizable as an audience
- no excessive scene deformation

### Shot 03: Tharp compilation at the desk

Purpose:
- shift into disciplined accumulation and compilation

Input asset:
- one designed still plate: Marie Tharp at a drafting table with profile strips,
  contour paper, earthquake dots, layered map materials

Runway mode:
- image-to-video

Model:
- `gen4.5`

Duration:
- 10 seconds

Aspect:
- `1280:720`

Prompt:
```text
A careful editorial animation of a scientist compiling evidence at a drafting
table. Paper strips slide into alignment one after another, contour marks build
in successive passes, and the camera drifts slowly across the table as the
structure becomes clearer. The motion is patient, cumulative, and precise. The
scene should feel methodical and legible, not magical or abrupt.
```

Prompt notes:
- the key word is **cumulative**
- we want layered alignment, not one instant reveal
- camera motion should be slower than the Wegener shot

Acceptance criteria:
- multiple successive compilation beats
- evidence becomes more organized over time
- desk scene remains stable and readable
- the result can later bridge into our own compiled-map animation

## Review workflow

For each shot:

1. generate 3–5 variants
2. select the cleanest motion, not the flashiest
3. freeze final frame candidates when useful for the next shot
4. bring clips back into our compositor for overlays and sequencing

## What I need from you

When your Runway account is ready, I need only:

- confirmation that the account is active
- the API key placed in `RUNWAYML_API_SECRET`

Then I can start with the three-shot trial immediately.
