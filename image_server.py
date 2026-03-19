"""
Python FastAPI microservice for darts180 image generation.
Runs on port 5001, proxied by Express from /api/generate.
Uses pplx.python.sdks.llm_api for image generation.
After generation, composites the real darts180 logo onto the image.
"""

import base64
import io
import os
import sys
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from PIL import Image, ImageDraw, ImageFilter

from generate_image import generate_image

app = FastAPI()

# ── Paths to logo files ──────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_LIGHT_BG = os.path.join(SCRIPT_DIR, "logo-light.jpg")  # Black DARTS + blue 180 — best on light bg
LOGO_DARK_BG = os.path.join(SCRIPT_DIR, "logo-dark.jpg")    # All-blue version — used with backdrop on dark bg

# Aspect ratio mapping for media types
ASPECT_RATIOS = {
    "instagram_post": "1:1",
    "instagram_story": "9:16",
    "blog_hero": "16:9",
    "product_review_media": "16:9",
}

# Logo target widths relative to image width — discreet but readable
LOGO_WIDTH_RATIO = {
    "instagram_post": 0.25,       # ~270px on 1080
    "instagram_story": 0.25,      # ~270px on 1080
    "blog_hero": 0.14,            # ~224px on 1600
    "product_review_media": 0.14, # ~224px on 1600
}

LOGO_PADDING_RATIO = 0.02  # 2% from edges


def detect_background_brightness(img: Image.Image) -> float:
    """Sample the top-left region to determine if the background is light or dark."""
    w, h = img.size
    sample_w = max(int(w * 0.25), 1)
    sample_h = max(int(h * 0.10), 1)
    region = img.crop((0, 0, sample_w, sample_h))
    gray = region.convert("L")
    pixels = list(gray.getdata())
    return sum(pixels) / len(pixels) if pixels else 128


def make_logo_transparent(logo_path: str) -> Image.Image:
    """Load a JPG logo and make the white background transparent."""
    logo = Image.open(logo_path).convert("RGBA")
    w, h = logo.size
    pixels = logo.load()

    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            min_ch = min(r, g, b)
            avg = (r + g + b) / 3

            if min_ch > 245 and avg > 250:
                pixels[x, y] = (r, g, b, 0)
            elif min_ch > 220 and avg > 230:
                fade = int(255 * (1.0 - (min_ch - 220) / 35.0))
                pixels[x, y] = (r, g, b, max(0, min(255, fade)))

    return logo


def create_backdrop(logo_w: int, logo_h: int, corner_radius: int = 8) -> Image.Image:
    """
    Create a subtle semi-transparent white rounded-rect backdrop
    to place behind the logo on dark backgrounds.
    """
    pad_x = int(logo_w * 0.08)
    pad_y = int(logo_h * 0.15)
    bw = logo_w + 2 * pad_x
    bh = logo_h + 2 * pad_y

    backdrop = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(backdrop)

    # Semi-transparent white rounded rectangle
    r = corner_radius
    draw.rounded_rectangle(
        [(0, 0), (bw - 1, bh - 1)],
        radius=r,
        fill=(255, 255, 255, 180),  # ~70% opaque white
    )

    return backdrop, pad_x, pad_y


def composite_logo(generated_img_bytes: bytes, media_type: str) -> bytes:
    """
    Overlay the darts180 logo onto the generated image.
    On dark backgrounds, adds a subtle white backdrop behind the logo.
    Always uses the light-bg logo (it has the full DARTS180.FR text).
    """
    img = Image.open(io.BytesIO(generated_img_bytes)).convert("RGBA")
    w, h = img.size

    brightness = detect_background_brightness(img)
    is_dark_bg = brightness < 140
    print(f"[logo] bg brightness={brightness:.0f}, dark={is_dark_bg}", file=sys.stderr)

    # Always use the light-bg logo (has full DARTS180.FR wordmark)
    logo_rgba = make_logo_transparent(LOGO_LIGHT_BG)

    # Resize logo to target width
    ratio = LOGO_WIDTH_RATIO.get(media_type, 0.15)
    target_logo_w = int(w * ratio)
    logo_aspect = logo_rgba.width / logo_rgba.height
    target_logo_h = int(target_logo_w / logo_aspect)
    logo_resized = logo_rgba.resize(
        (target_logo_w, target_logo_h), Image.LANCZOS
    )

    # Position
    pad = int(w * LOGO_PADDING_RATIO)
    pos_x = pad
    pos_y = pad

    if is_dark_bg:
        # Add a subtle white backdrop behind the logo
        backdrop, bpad_x, bpad_y = create_backdrop(
            target_logo_w, target_logo_h,
            corner_radius=max(4, int(target_logo_h * 0.12)),
        )
        # Place backdrop first
        backdrop_x = pos_x - bpad_x
        backdrop_y = pos_y - bpad_y
        # Ensure backdrop doesn't go negative
        backdrop_x = max(0, backdrop_x)
        backdrop_y = max(0, backdrop_y)
        img.paste(backdrop, (backdrop_x, backdrop_y), backdrop)
        # Adjust logo position to center on backdrop
        pos_x = backdrop_x + bpad_x
        pos_y = backdrop_y + bpad_y

    # Paste logo
    img.paste(logo_resized, (pos_x, pos_y), logo_resized)

    # Save as PNG
    output = io.BytesIO()
    img.convert("RGB").save(output, format="PNG", quality=95)
    return output.getvalue()


@app.post("/generate")
async def generate(request: Request):
    try:
        body = await request.json()
        prompt: str = body.get("prompt", "")
        media_type: str = body.get("mediaType", "blog_hero")
        image_data: Optional[str] = body.get("imageData")

        if not prompt:
            return JSONResponse(
                status_code=400, content={"error": "Missing prompt"}
            )

        aspect_ratio = ASPECT_RATIOS.get(media_type, "1:1")

        image_bytes = None
        image_media_type = None
        if image_data:
            if "," in image_data:
                header, b64 = image_data.split(",", 1)
                if "image/jpeg" in header or "image/jpg" in header:
                    image_media_type = "image/jpeg"
                elif "image/png" in header:
                    image_media_type = "image/png"
                elif "image/webp" in header:
                    image_media_type = "image/webp"
                else:
                    image_media_type = "image/png"
            else:
                b64 = image_data
                image_media_type = "image/png"
            image_bytes = base64.b64decode(b64)

        # Generate image via AI
        result_bytes = await generate_image(
            prompt,
            image_bytes=image_bytes,
            image_media_type=image_media_type,
            aspect_ratio=aspect_ratio,
            model="nano_banana_2",
        )

        # Composite the real logo
        final_bytes = composite_logo(result_bytes, media_type)

        result_b64 = base64.b64encode(final_bytes).decode()
        return JSONResponse(
            content={"image": f"data:image/png;base64,{result_b64}", "success": True}
        )

    except Exception as e:
        print(f"Error generating image: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001)
