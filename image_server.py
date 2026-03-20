"""
Python FastAPI microservice for darts180 image generation.
Runs on port 5001, proxied by Express from /api/generate.
Uses OpenAI API (gpt-image-1) for image generation.
After generation, enforces a minimum 20px inner margin.
"""

import base64
import io
import os
import sys
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from PIL import Image

from generate_image import generate_image

app = FastAPI()

# Aspect ratio mapping for media types
ASPECT_RATIOS = {
    "instagram_post": "1:1",
    "instagram_story": "9:16",
    "blog_hero": "16:9",
    "product_review_media": "16:9",
}

# Target output sizes for each media type
TARGET_SIZES = {
    "instagram_post": (1080, 1080),
    "instagram_story": (1080, 1920),
    "blog_hero": (1600, 900),
    "product_review_media": (1600, 900),
}

# Minimum inner margin in pixels (matches the 60px safe zone in prompts)
INNER_MARGIN = 30


def apply_inner_margin(generated_img_bytes: bytes, media_type: str) -> bytes:
    """
    Ensure the generated image has at least a 20px inner margin on all sides.
    The generated content is scaled down slightly and centered, with the
    edge pixels extended outward to fill the margin area seamlessly.
    """
    img = Image.open(io.BytesIO(generated_img_bytes)).convert("RGB")
    w, h = img.size

    target_w, target_h = TARGET_SIZES.get(media_type, (w, h))
    margin = INNER_MARGIN

    # Calculate the inner area where content should live
    inner_w = target_w - 2 * margin
    inner_h = target_h - 2 * margin

    # Resize the generated image to fit within the inner area
    img_resized = img.resize((inner_w, inner_h), Image.LANCZOS)

    # Sample the average color from each edge strip (2px deep) of the resized image
    # to create a natural-looking margin fill
    def avg_color_strip(image, box):
        """Get the average color from a region of the image."""
        strip = image.crop(box)
        pixels = list(strip.getdata())
        if not pixels:
            return (128, 128, 128)
        r = sum(p[0] for p in pixels) // len(pixels)
        g = sum(p[1] for p in pixels) // len(pixels)
        b = sum(p[2] for p in pixels) // len(pixels)
        return (r, g, b)

    # Get dominant edge colors from each side
    top_color = avg_color_strip(img_resized, (0, 0, inner_w, min(4, inner_h)))
    bottom_color = avg_color_strip(img_resized, (0, max(0, inner_h - 4), inner_w, inner_h))
    left_color = avg_color_strip(img_resized, (0, 0, min(4, inner_w), inner_h))
    right_color = avg_color_strip(img_resized, (max(0, inner_w - 4), 0, inner_w, inner_h))

    # Blend into a single background color for the margin
    bg_r = (top_color[0] + bottom_color[0] + left_color[0] + right_color[0]) // 4
    bg_g = (top_color[1] + bottom_color[1] + left_color[1] + right_color[1]) // 4
    bg_b = (top_color[2] + bottom_color[2] + left_color[2] + right_color[2]) // 4
    bg_color = (bg_r, bg_g, bg_b)

    # Create the output canvas with the background color
    output_img = Image.new("RGB", (target_w, target_h), bg_color)

    # Paste the resized content centered with the margin
    output_img.paste(img_resized, (margin, margin))

    # Save as PNG
    output = io.BytesIO()
    output_img.save(output, format="PNG", quality=95)
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
            model="gpt-image-1",
        )

        # Apply inner margin (20px on all sides)
        final_bytes = apply_inner_margin(result_bytes, media_type)

        result_b64 = base64.b64encode(final_bytes).decode()
        return JSONResponse(
            content={"image": f"data:image/png;base64,{result_b64}", "success": True}
        )

    except Exception as e:
        print(f"Error generating image: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return JSONResponse(
            status_code=500,
            content={"error": "Erreur lors de la génération de l'image.", "details": str(e)}
        )


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001)
