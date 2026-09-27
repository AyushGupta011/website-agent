import os
import shutil
from pathlib import Path
from typing import List
from .router import ModelRouter, TaskType
from .analyze import DesignSpec, SectionSpec

async def scaffold_project(session_id: str) -> Path:
    base_dir = Path(f"generated/{session_id}")
    if base_dir.exists():
        shutil.rmtree(base_dir)
        
    shutil.copytree("sandbox_template", base_dir, ignore=shutil.ignore_patterns('node_modules', '.git', '.next'))
    
    # Ensure components dir exists
    (base_dir / "src" / "components").mkdir(parents=True, exist_ok=True)
    return base_dir

def get_theme_prompt(spec: DesignSpec) -> str:
    return f"""
    CRITICAL THEME CONSTRAINTS:
    Use exactly these Tailwind tokens; do not invent your own palette or type scale.
    - Primary Color: {spec.theme.primary_color}
    - Secondary Color: {spec.theme.secondary_color}
    - Background Color: {spec.theme.background_color}
    - Text Color: {spec.theme.text_color}
    - Font Family: {spec.theme.font_family}
    - Border Radius: {spec.theme.border_radius} (use rounded-{spec.theme.border_radius})
    
    Use placeholder images (e.g. https://via.placeholder.com/150) where necessary if no image URLs are provided.
    """

async def generate_section(section: SectionSpec, spec: DesignSpec, router: ModelRouter, output_dir: Path):
    prompt = f"""
    Create a React (Next.js App Router) component for this section.
    
    Section Details:
    ID: {section.id}
    Type: {section.type}
    Headline: {section.headline}
    Subheadline: {section.subheadline}
    Body: {section.body}
    Layout: {section.layout}
    Items: {section.items}
    Image URLs: {section.image_urls}
    
    Navigation Spec (use this if section type is navbar):
    Logo Text: {spec.navigation.logo_text}
    Links: {spec.navigation.links}
    Sticky: {spec.navigation.sticky}
    
    {get_theme_prompt(spec)}
    
    Requirements:
    1. Write ONLY the code for a functional React component using Tailwind CSS. 
    2. Export it as default.
    3. Include necessary imports (like lucide-react for icons if needed).
    4. Make it fully responsive.
    5. Do not include markdown formatting or explanation, just the raw code.
    """
    
    code = await router.generate(
        task_type=TaskType.CODEGEN,
        prompt=prompt,
        max_provider_attempts=2
    )
    
    # Clean markdown if present
    code = code.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        if lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].startswith("```"): lines = lines[:-1]
        code = "\n".join(lines).strip()
        
    file_path = output_dir / "src" / "components" / f"{section.id.capitalize()}.tsx"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
        
    return f"{section.id.capitalize()}"

async def generate_page(spec: DesignSpec, section_components: List[str], router: ModelRouter, output_dir: Path):
    imports = "\n".join([f'import {comp} from "@/components/{comp}";' for comp in section_components])
    components_jsx = "\n".join([f'      <{comp} />' for comp in section_components])
    
    page_code = f"""
import React from 'react';
{imports}

export default function Page() {{
  return (
    <main className="min-h-screen bg-[{spec.theme.background_color}] text-[{spec.theme.text_color}] font-sans">
{components_jsx}
    </main>
  );
}}
"""
    with open(output_dir / "src" / "app" / "page.tsx", "w", encoding="utf-8") as f:
        f.write(page_code.strip())

async def generate_tailwind_config(spec: DesignSpec, output_dir: Path):
    config = f"""
import type {{ Config }} from "tailwindcss";

const config: Config = {{
  content: [
    "./src/pages/**/*.{{js,ts,jsx,tsx,mdx}}",
    "./src/components/**/*.{{js,ts,jsx,tsx,mdx}}",
    "./src/app/**/*.{{js,ts,jsx,tsx,mdx}}",
  ],
  theme: {{
    extend: {{
      colors: {{
        primary: "{spec.theme.primary_color}",
        secondary: "{spec.theme.secondary_color}",
        background: "{spec.theme.background_color}",
        foreground: "{spec.theme.text_color}",
      }},
      fontFamily: {{
        sans: ["{spec.theme.font_family}", "sans-serif"],
      }}
    }},
  }},
  plugins: [],
}};
export default config;
"""
    with open(output_dir / "tailwind.config.ts", "w", encoding="utf-8") as f:
        f.write(config.strip())

async def generate_site(session_id: str, spec: DesignSpec, router: ModelRouter):
    output_dir = await scaffold_project(session_id)
    
    # Generate sections concurrently? Or sequentially to avoid rate limits
    components = []
    
    # Let's generate navbar first if it exists, otherwise just generate in order
    for section in spec.sections:
        comp_name = await generate_section(section, spec, router, output_dir)
        components.append(comp_name)
        
    await generate_page(spec, components, router, output_dir)
    await generate_tailwind_config(spec, output_dir)
    
    return str(output_dir)
