import base64
import json
from typing import Literal, List, Optional
from pydantic import BaseModel
from .router import ModelRouter, TaskType
from .capture import CaptureResult

class ThemeSpec(BaseModel):
    primary_color: str
    secondary_color: str
    background_color: str
    text_color: str
    font_family: str
    border_radius: Literal["none", "sm", "md", "lg"]

class SectionItem(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    image_hint: Optional[str] = None

class SectionSpec(BaseModel):
    id: str
    type: Literal["navbar", "hero", "features", "testimonials",
                   "pricing", "cta", "footer", "gallery", "contact", "generic"]
    headline: Optional[str] = None
    subheadline: Optional[str] = None
    body: Optional[str] = None
    items: List[SectionItem] = []
    layout: Literal["centered", "left-right", "grid", "stacked"]
    image_urls: List[str] = []
    ui_details: Optional[str] = None
    html_reference: Optional[str] = None

class NavigationSpec(BaseModel):
    logo_text: Optional[str] = None
    links: List[str] = []
    sticky: bool = False
    ui_details: Optional[str] = None

class DesignSpec(BaseModel):
    title: str
    description: Optional[str] = None
    theme: ThemeSpec
    sections: List[SectionSpec]
    navigation: NavigationSpec

async def analyze(capture_result: CaptureResult, router: ModelRouter) -> DesignSpec:
    if capture_result.error:
        raise ValueError(f"Capture failed: {capture_result.error}")

    # Build gradient/animation info if available
    extra_data = ""
    if hasattr(capture_result, 'gradients') and capture_result.gradients:
        extra_data += f"\nCSS Gradients found: {capture_result.gradients[:10]}"
    if hasattr(capture_result, 'animations') and capture_result.animations:
        extra_data += f"\nCSS Animations/Transitions: {json.dumps(capture_result.animations[:10])}"
    if hasattr(capture_result, 'box_shadows') and capture_result.box_shadows:
        extra_data += f"\nBox Shadows: {capture_result.box_shadows[:10]}"

    # Per-section HTML chunks for richer context
    section_html_chunks = ""
    for i, sec in enumerate(capture_result.sections):
        section_html_chunks += f"\n--- Viewport {i+1} HTML ---\n{sec.html_chunk[:1000]}\n"

    prompt = f"""You are an expert web designer analyzing a website to create a PIXEL-PERFECT clone.

WEBSITE URL: {capture_result.url}

I am providing you with viewport screenshots taken by scrolling down the ENTIRE page from top to bottom.

=== EXTRACTED DATA ===
Dominant Colors (rgb/hex): {capture_result.colors}
Fonts Used: {capture_result.fonts}
Image URLs: {capture_result.images[:15]}
Background Images: {capture_result.background_images[:5]}
{extra_data}

Computed Styles:
{json.dumps(capture_result.styles, indent=1)[:2000]}

=== HTML CHUNKS ===
{section_html_chunks[:3000]}

=== FULL HTML (truncated) ===
{capture_result.full_html[:4000]}

=== CRITICAL INSTRUCTIONS ===

1. ANALYZE every screenshot from top to bottom. You see the ENTIRE website scrolled.

2. YOUR SECTIONS ARRAY MUST INCLUDE ALL OF THE FOLLOWING (if they exist on the page):
   - A "navbar" section (REQUIRED if there is a navigation bar visible)
   - A "hero" section  
   - ALL middle sections (features, pricing, testimonials, gallery, CTA, etc.)
   - A "footer" section (REQUIRED if there is a footer visible)
   You MUST generate AT LEAST 6-10 sections for a typical website. Do NOT skip any visible section!

3. For EACH section, extract with extreme precision:
   - `headline`, `subheadline`, `body`: Read the EXACT text from the screenshots. Character-for-character accuracy!
   - `items`: Every card, feature box, testimonial, pricing tier — extract title and description EXACTLY
   - `image_urls`: Map the correct image URLs from the extracted list to each section
   - `ui_details`: This is the MOST IMPORTANT field. Write a detailed paragraph describing:
     * Background: exact color hex/rgb, or gradient (linear-gradient direction and stops)
     * Text: exact font sizes (text-sm, text-lg, text-4xl etc), font weights (font-bold, font-extrabold), colors
     * Layout: flex direction, grid columns, gap sizes, max-width, centering
     * Spacing: exact padding and margins (py-16, px-8, gap-6, etc.)
     * Borders, shadows, rounded corners (rounded-lg, shadow-xl, border-b)
     * Button styles: background color, text color, border-radius, padding, hover state
     * Any visible animations: fade-in on scroll, sliding, hover scale effects
     * Icon usage: what kind of icons, where they appear
   - `html_reference`: Copy the most relevant HTML snippet (max 300 chars)

4. THEME: Extract the EXACT colors as rgb() or hex values. Convert any oklab/oklch to rgb.
   - primary_color: the main accent/brand color (buttons, links, highlighted text)
   - secondary_color: the secondary accent
   - background_color: the main page background
   - text_color: the main body text color
   
5. NAVIGATION: Fill in logo_text, all link names, sticky true/false, and detailed ui_details.

6. ABSOLUTE RULES:
   - NEVER use placeholder text like "Welcome to Our Site" or "Lorem ipsum"
   - NEVER skip the navbar or footer
   - NEVER combine two visually distinct sections into one
   - Use rgb() or hex for ALL colors, never oklab() or oklch()
   - KEEP descriptions concise. DO NOT generate overly verbose JSON, as it will be truncated.

Return ONLY a valid JSON object matching the required schema.
"""

    # Prepare images for the vision model
    image_list = []
    for section in capture_result.sections:
        img_bytes = base64.b64decode(section.screenshot_b64)
        image_list.append(img_bytes)

    design_spec = await router.generate(
        task_type=TaskType.VISION_ANALYSIS,
        prompt=prompt,
        images=image_list,
        response_model=DesignSpec
    )

    return design_spec
