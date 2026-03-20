"""
Python FastAPI microservice for darts180 image generation.
Runs on port 5001, proxied by Express from /api/generate.
Uses OpenAI API (gpt-image-1) for image generation.

HYBRID TEXT OVERLAY APPROACH:
1. AI generates illustration-only (no text in image)
2. Post-processing adds inner margin
3. Pillow overlays title/subtitle text with exact centering using Oswald + DM Sans fonts
"""

import base64
import io
import os
import sys
import textwrap
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from PIL import Image, ImageDraw, ImageFont

from generate_image import generate_image

app = FastAPI()

# ─── Font paths ───────────────────────────────────────────────────────────────
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
OSWALD_BOLD = os.path.join(FONT_DIR, "Oswald-Bold.ttf")
DMSANS_MEDIUM = os.path.join(FONT_DIR, "DMSans-Medium.ttf")
DMSANS_REGULAR = os.path.join(FONT_DIR, "DMSans-Regular.ttf")

# ─── Brand colors ─────────────────────────────────────────────────────────────
BRAND_BLUE = "#0055a5"
BRAND_RED = "#eb0004"
COLOR_WHITE = "#FFFFFF"
COLOR_LIGHT = "#f5f5f5"

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

# Minimum inner margin in pixels
INNER_MARGIN = 30


def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def get_text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple:
    """Get the bounding box of text. Returns (width, height)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def find_font_size(draw: ImageDraw.ImageDraw, text: str, font_path: str,
                   max_width: int, max_size: int, min_size: int = 20) -> ImageFont.FreeTypeFont:
    """Find the largest font size that fits text within max_width."""
    for size in range(max_size, min_size - 1, -2):
        font = ImageFont.truetype(font_path, size)
        w, _ = get_text_bbox(draw, text, font)
        if w <= max_width:
            return font
    return ImageFont.truetype(font_path, min_size)


def wrap_text_to_width(draw: ImageDraw.ImageDraw, text: str, font_path: str,
                       max_width: int, font_size: int) -> tuple:
    """
    Wrap text to fit within max_width. Returns (lines, font).
    Reduces font size if even single words don't fit.
    """
    font = ImageFont.truetype(font_path, font_size)
    words = text.split()
    
    # Check if the text fits on one line
    full_w, _ = get_text_bbox(draw, text, font)
    if full_w <= max_width:
        return [text], font
    
    # Try wrapping into multiple lines
    lines = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        w, _ = get_text_bbox(draw, test_line, font)
        if w <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    
    # Verify each line fits; if not, reduce font size
    for line in lines:
        w, _ = get_text_bbox(draw, line, font)
        if w > max_width:
            # Reduce font size and retry
            new_size = max(font_size - 4, 16)
            if new_size < font_size:
                return wrap_text_to_width(draw, text, font_path, max_width, new_size)
            break
    
    return lines, font


def draw_text_with_shadow(draw: ImageDraw.ImageDraw, position: tuple, text: str,
                          font: ImageFont.FreeTypeFont, fill: str,
                          shadow_color: str = "#00000080", shadow_offset: int = 2):
    """Draw text with a subtle shadow for readability on any background."""
    x, y = position
    # Shadow
    shadow_rgb = hex_to_rgb(shadow_color[:7]) if shadow_color.startswith("#") else (0, 0, 0)
    shadow_alpha = int(shadow_color[7:9], 16) if len(shadow_color) > 7 else 128
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font,
              fill=(*shadow_rgb, shadow_alpha))
    # Main text
    fill_rgb = hex_to_rgb(fill) if fill.startswith("#") else fill
    draw.text((x, y), text, font=font, fill=fill_rgb)


def overlay_text_on_image(img: Image.Image, media_type: str,
                          title: str = "", subtitle: str = "",
                          cta: str = "", price: str = "") -> Image.Image:
    """
    Overlay title, subtitle, CTA, and price text on the image.
    Text is always centered horizontally and positioned appropriately for the media type.
    Uses Oswald Bold for titles and DM Sans for subtitles/body.
    """
    if not title and not subtitle and not cta:
        return img  # Nothing to overlay
    
    # Convert to RGBA for alpha compositing
    img = img.convert("RGBA")
    w, h = img.size
    
    # Create text overlay layer
    txt_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)
    
    # Safe zone margins (from edges)
    safe_margin = 60
    usable_width = w - 2 * safe_margin
    max_text_width = int(usable_width * 0.90)  # 90% of usable area
    
    # ─── Layout configuration per media type ──────────────────────────────
    if media_type == "blog_hero":
        # Blog hero: 1600x900 — title centered, large and bold
        title_max_size = 90
        subtitle_max_size = 36
        title_y_center = h * 0.42  # slightly above center
        
    elif media_type == "instagram_post":
        # Instagram post: 1080x1080 — title in upper third, CTA at bottom
        title_max_size = 72
        subtitle_max_size = 32
        title_y_center = h * 0.30
        
    elif media_type == "instagram_story":
        # Story: 1080x1920 vertical — title at top third, CTA at bottom
        title_max_size = 68
        subtitle_max_size = 30
        title_y_center = h * 0.20
        
    elif media_type == "product_review_media":
        # Product review: 1600x900 — title at top, product in center
        title_max_size = 80
        subtitle_max_size = 34
        title_y_center = h * 0.25
        
    else:
        title_max_size = 72
        subtitle_max_size = 32
        title_y_center = h * 0.40
    
    # ─── Draw semi-transparent background band behind text ────────────────
    # This ensures readability regardless of illustration
    
    current_y = title_y_center
    elements_height = 0
    
    # Pre-calculate total text block height
    title_lines = []
    title_font = None
    subtitle_font = None
    subtitle_lines = []
    cta_font = None
    
    if title:
        title_upper = title.upper()
        title_lines, title_font = wrap_text_to_width(
            draw, title_upper, OSWALD_BOLD, max_text_width, title_max_size
        )
        for line in title_lines:
            _, lh = get_text_bbox(draw, line, title_font)
            elements_height += lh + 8  # 8px line spacing
    
    if subtitle:
        subtitle_lines, subtitle_font = wrap_text_to_width(
            draw, subtitle, DMSANS_MEDIUM, max_text_width, subtitle_max_size
        )
        elements_height += 16  # gap between title and subtitle
        for line in subtitle_lines:
            _, lh = get_text_bbox(draw, line, subtitle_font)
            elements_height += lh + 4
    
    if price:
        elements_height += 20  # gap
        price_font = ImageFont.truetype(OSWALD_BOLD, min(title_max_size - 10, 70))
        _, ph = get_text_bbox(draw, price, price_font)
        elements_height += ph
    
    # Draw a semi-transparent dark band behind all text
    band_padding = 32
    band_top = int(title_y_center - elements_height / 2 - band_padding)
    band_bottom = int(title_y_center + elements_height / 2 + band_padding)
    
    # Ensure band stays within image
    band_top = max(0, band_top)
    band_bottom = min(h, band_bottom)
    
    # Semi-transparent dark overlay band for text readability
    band = Image.new("RGBA", (w, band_bottom - band_top), (0, 30, 70, 180))
    txt_layer.paste(band, (0, band_top))
    # Recreate draw after paste
    draw = ImageDraw.Draw(txt_layer)
    
    # ─── Draw title (centered) ────────────────────────────────────────────
    current_y = title_y_center - elements_height / 2
    
    if title and title_font:
        for line in title_lines:
            lw, lh = get_text_bbox(draw, line, title_font)
            x = (w - lw) / 2  # EXACT horizontal center
            draw_text_with_shadow(draw, (x, current_y), line, title_font, COLOR_WHITE)
            current_y += lh + 8
    
    # ─── Draw subtitle (centered) ─────────────────────────────────────────
    if subtitle and subtitle_font:
        current_y += 16  # gap
        for line in subtitle_lines:
            lw, lh = get_text_bbox(draw, line, subtitle_font)
            x = (w - lw) / 2
            draw_text_with_shadow(draw, (x, current_y), line, subtitle_font, COLOR_LIGHT,
                                  shadow_offset=1)
            current_y += lh + 4
    
    # ─── Draw price (centered, in red) ────────────────────────────────────
    if price:
        current_y += 20
        price_font = ImageFont.truetype(OSWALD_BOLD, min(title_max_size - 10, 70))
        price_upper = price.upper()
        pw, ph = get_text_bbox(draw, price_upper, price_font)
        x = (w - pw) / 2
        draw_text_with_shadow(draw, (x, current_y), price_upper, price_font, BRAND_RED)
        current_y += ph
    
    # ─── Draw CTA at bottom (centered) ────────────────────────────────────
    if cta and media_type in ("instagram_post", "instagram_story"):
        cta_size = 28 if media_type == "instagram_story" else 30
        cta_font = ImageFont.truetype(DMSANS_MEDIUM, cta_size)
        cta_upper = cta.upper()
        cw, ch = get_text_bbox(draw, cta_upper, cta_font)
        
        # Position CTA near bottom with safe margin
        cta_y = h - safe_margin - ch - 30
        cta_x = (w - cw) / 2
        
        # Draw CTA background pill
        pill_padding_x = 24
        pill_padding_y = 12
        pill_rect = [
            cta_x - pill_padding_x,
            cta_y - pill_padding_y,
            cta_x + cw + pill_padding_x,
            cta_y + ch + pill_padding_y,
        ]
        draw.rounded_rectangle(pill_rect, radius=8, fill=hex_to_rgb(BRAND_RED) + (230,))
        draw.text((cta_x, cta_y), cta_upper, font=cta_font, fill=hex_to_rgb(COLOR_WHITE))
    
    # Composite text layer onto image
    result = Image.alpha_composite(img, txt_layer)
    return result.convert("RGB")


def apply_inner_margin(generated_img_bytes: bytes, media_type: str) -> bytes:
    """
    Ensure the generated image has at least a 30px inner margin on all sides.
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

    return output_img


@app.post("/generate")
async def generate(request: Request):
    try:
        body = await request.json()
        prompt: str = body.get("prompt", "")
        media_type: str = body.get("mediaType", "blog_hero")
        image_data: Optional[str] = body.get("imageData")
        
        # Text overlay data (passed from Express)
        overlay_title: str = body.get("overlayTitle", "")
        overlay_subtitle: str = body.get("overlaySubtitle", "")
        overlay_cta: str = body.get("overlayCta", "")
        overlay_price: str = body.get("overlayPrice", "")

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

        # Generate image via AI (illustration only, no text)
        result_bytes = await generate_image(
            prompt,
            image_bytes=image_bytes,
            image_media_type=image_media_type,
            aspect_ratio=aspect_ratio,
            model="gpt-image-1",
        )

        # Step 1: Apply inner margin
        margined_img = apply_inner_margin(result_bytes, media_type)

        # Step 2: Overlay text programmatically (centered, Oswald + DM Sans)
        final_img = overlay_text_on_image(
            margined_img, media_type,
            title=overlay_title,
            subtitle=overlay_subtitle,
            cta=overlay_cta,
            price=overlay_price,
        )

        # Save as PNG bytes
        output = io.BytesIO()
        final_img.save(output, format="PNG", quality=95)
        final_bytes = output.getvalue()

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
