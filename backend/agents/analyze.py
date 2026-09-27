import base64
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

class NavigationSpec(BaseModel):
    logo_text: Optional[str] = None
    links: List[str] = []
    sticky: bool = False

class DesignSpec(BaseModel):
    title: str
    description: Optional[str] = None
    theme: ThemeSpec
    sections: List[SectionSpec]
    navigation: NavigationSpec

async def analyze(capture_result: CaptureResult, router: ModelRouter) -> DesignSpec:
    if capture_result.error:
        raise ValueError(f"Capture failed: {capture_result.error}")

    prompt = f"""
    Analyze the provided website screenshot and HTML content.
    Extracted colors from the page: {capture_result.colors}
    
    Please provide a detailed design specification matching the required JSON schema.
    Extract the text content, structure, and layout. 
    Use the extracted colors to define the ThemeSpec.
    Break the page down into logical sections.
    """
    
    # decode the screenshot for the router
    image_bytes = base64.b64decode(capture_result.screenshot)

    design_spec = await router.generate(
        task_type=TaskType.VISION_ANALYSIS,
        prompt=prompt,
        images=[image_bytes],
        response_model=DesignSpec,
        max_provider_attempts=2
    )
    
    return design_spec
