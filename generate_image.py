"""Async image generation via OpenAI API (gpt-image-1 / dall-e-3).

Usage:
    from generate_image import generate_image
    image_bytes = await generate_image("A sunset over mountains")
    image_bytes = await generate_image("Edit this image", image_bytes=uploaded, image_media_type="image/png")
"""

import base64
import os
from openai import AsyncOpenAI

# Map string aspect ratios to OpenAI size parameters
# OpenAI dall-e-3 supports: 1024x1024, 1024x1792, 1792x1024
# gpt-image-1 supports: 1024x1024, 1024x1536, 1536x1024, auto
SIZES = {
    "1:1": "1024x1024",
    "9:16": "1024x1536",   # Vertical (story)
    "16:9": "1536x1024",   # Horizontal (blog hero, review)
    "3:4": "1024x1536",
    "4:3": "1536x1024",
}


async def generate_image(
    prompt: str,
    *,
    image_bytes: bytes | None = None,
    image_media_type: str | None = None,
    aspect_ratio: str = "1:1",
    model: str = "gpt-image-1",
) -> bytes:
    """Generate an image using OpenAI's image generation API.
    
    If image_bytes is provided, uses the edit endpoint to modify the image.
    Otherwise, uses the generation endpoint.
    """
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    size = SIZES.get(aspect_ratio, "1024x1024")

    if image_bytes:
        # Use image edit endpoint
        # OpenAI expects the image as a file-like object
        import io
        image_file = io.BytesIO(image_bytes)
        image_file.name = "input.png"  # OpenAI needs a name attribute
        
        response = await client.images.edit(
            model=model,
            image=image_file,
            prompt=prompt,
            size=size,
        )
    else:
        # Use image generation endpoint
        response = await client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            n=1,
            response_format="b64_json",
        )

    # Extract image data
    image_data = response.data[0]
    
    if hasattr(image_data, 'b64_json') and image_data.b64_json:
        return base64.b64decode(image_data.b64_json)
    elif hasattr(image_data, 'url') and image_data.url:
        # If we got a URL instead of base64, download it
        import httpx
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(image_data.url)
            return resp.content
    else:
        raise RuntimeError("No image data in OpenAI response")
