import os
import re
import json
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
    CRITICAL THEME CONSTRAINTS (use EXACT values, not approximations):
    - Primary Color: {spec.theme.primary_color}
    - Secondary Color: {spec.theme.secondary_color}
    - Background Color: {spec.theme.background_color}
    - Text Color: {spec.theme.text_color}
    - Font Family: {spec.theme.font_family}
    - Border Radius: {spec.theme.border_radius}
    
    Use these as Tailwind arbitrary values: e.g. bg-[{spec.theme.primary_color}], text-[{spec.theme.text_color}], font-['{spec.theme.font_family}']
    """

async def generate_section(section: SectionSpec, spec: DesignSpec, router: ModelRouter, output_dir: Path):
    # Convert section.id (e.g., 'design-showcase') to PascalCase ('DesignShowcase')
    parts = re.split(r'[-_]', section.id)
    component_name = "".join(p.capitalize() for p in parts if p)
    
    # Read skills.md rules
    skills_path = output_dir / "skills.md"
    skills_content = ""
    if skills_path.exists():
        with open(skills_path, "r", encoding="utf-8") as f:
            skills_content = f.read()
    
    # Include HTML reference if available
    html_ref = ""
    if section.html_reference:
        html_ref = f"""
    ORIGINAL HTML REFERENCE (use this to match the exact structure):
    ```html
    {section.html_reference[:1500]}
    ```
    """
    
    prompt = f"""You are a world-class React/Tailwind CSS developer. Your task is to create a PIXEL-PERFECT clone of one section of a website.

=== STRICT RULES ===
{skills_content[:3000]}

=== SECTION: {section.type.upper()} ===
Component Name: {component_name}

--- EXACT TEXT CONTENT (copy these character-for-character) ---
Headline: {section.headline or 'None — omit this element'}
Subheadline: {section.subheadline or 'None — omit this element'}
Body Text: {section.body or 'None — omit this element'}

Items/Cards (render ALL of these):
{json.dumps([dict(title=item.title, desc=item.description, img=item.image_hint) for item in section.items], indent=2) if section.items else '(none)'}

Image URLs — YOU MUST USE THESE EXACT URLs (do NOT use placeholder images):
{json.dumps(section.image_urls, indent=2) if section.image_urls else '(no images for this section)'}

--- VISUAL DESIGN SPEC (match every detail) ---
{section.ui_details or 'Use theme colors and make it professional'}

{html_ref}

{"--- NAVIGATION DATA ---" + chr(10) + "Logo: " + str(spec.navigation.logo_text) + chr(10) + "Links: " + str(spec.navigation.links) + chr(10) + "Sticky: " + str(spec.navigation.sticky) + chr(10) + "Style: " + str(spec.navigation.ui_details or 'Clean, modern navbar with logo on left and links on right') + chr(10) + "IMPORTANT: Include a mobile hamburger menu using useState." if section.type == 'navbar' else ''}

{"--- FOOTER DATA ---" + chr(10) + "Include all footer links, copyright text, and social media icons. Use lucide-react for icons." if section.type == 'footer' else ''}

--- THEME COLORS (use as Tailwind arbitrary values) ---
Primary: {spec.theme.primary_color}  → use as bg-[{spec.theme.primary_color}] or text-[{spec.theme.primary_color}]
Secondary: {spec.theme.secondary_color}
Background: {spec.theme.background_color}
Text: {spec.theme.text_color}
Font: {spec.theme.font_family}
Border Radius: {spec.theme.border_radius}

--- ANIMATION REQUIREMENTS ---
- Add framer-motion entrance animations to every section:
  * Headings: fade-in + slide-up (y: 30 → 0, opacity: 0 → 1, duration: 0.6s)
  * Cards/Items: staggered fade-in (each child delayed by 0.1s)
  * Images: fade-in with scale (scale: 0.95 → 1)
- Use `whileInView` with `viewport={{ once: true }}` so animations trigger on scroll
- Add hover effects on cards: `whileHover={{ y: -5, transition: {{ duration: 0.2 }} }}`
- Add hover effects on buttons: `whileHover={{ scale: 1.05 }}`
- Import: `import {{ motion }} from "framer-motion";`
- MUST add `"use client";` on the very first line when using motion

--- OUTPUT FORMAT & CRITICAL RULES ---
1. You MUST use the exact text, colors, and images provided above.
2. DO NOT use placeholder text like "Welcome to Our Platform" or "Replace with actual markup".
3. DO NOT output comments telling me to write the code. YOU must write the FULL, complete, final React component code.
4. If you output a generic boilerplate instead of a pixel-perfect clone, the build will fail.
5. Return ONLY the component code wrapped in ```tsx ... ``` fences. No explanations.
"""
    
    # Try up to 2 attempts to get valid code
    for attempt in range(2):
        code = await router.generate(
            task_type=TaskType.CODEGEN,
            prompt=prompt if attempt == 0 else prompt + "\n\nIMPORTANT: You MUST output the complete React component code. Do NOT ask questions. Do NOT request more information. Generate the best component you can with the information provided. Wrap your code in ```tsx ... ``` fences."
        )
        
        # Extract code from markdown fences
        code = code.strip()
        match = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*\n(.*?)```", code, re.DOTALL)
        if match:
            code = match.group(1).strip()
        else:
            # No code fences — check if the response itself looks like code
            if "export " in code or "import " in code or "function " in code or "const " in code:
                # It's raw code without fences, use it as-is
                pass
            else:
                # Model returned a question or garbage — retry
                print(f"[Generate] Attempt {attempt+1}: Model returned non-code for {component_name}, retrying...")
                continue
        
        # Check if code is substantial (not an empty shell)
        code_lines = [l for l in code.split('\n') if l.strip() and not l.strip().startswith('//') and not l.strip().startswith('import')]
        if len(code_lines) < 5:
            print(f"[Generate] Attempt {attempt+1}: Code too short for {component_name} ({len(code_lines)} lines), retrying...")
            continue
        
        # Safety: ensure it has a default export
        if "export default" not in code:
            code = f'export default function {component_name}() {{\n  return (\n    <section>\n      {code}\n    </section>\n  );\n}}'
        
        # Safety: add "use client" if it uses hooks or framer-motion
        if ("useState" in code or "useEffect" in code or "framer-motion" in code or "motion." in code) and '"use client"' not in code and "'use client'" not in code:
            code = '"use client";\n' + code
            
        file_path = output_dir / "src" / "components" / f"{component_name}.tsx"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
            
        return component_name
    
    # If we exhausted retries, generate a minimal but visible placeholder
    print(f"[Generate] WARNING: Could not generate real code for {component_name}, creating placeholder")
    placeholder = f'''"use client";
export default function {component_name}() {{
  return (
    <section className="py-16 px-8 bg-[{spec.theme.background_color}]">
      <div className="max-w-6xl mx-auto text-center">
        <h2 className="text-3xl font-bold text-[{spec.theme.text_color}]">{section.headline or component_name}</h2>
        {f'<p className="mt-4 text-lg text-gray-600">{section.subheadline}</p>' if section.subheadline else ''}
        {f'<p className="mt-2 text-gray-500">{section.body}</p>' if section.body else ''}
      </div>
    </section>
  );
}}'''
    file_path = output_dir / "src" / "components" / f"{component_name}.tsx"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(placeholder)
        
    return component_name

async def generate_page(spec: DesignSpec, section_components: List[str], router: ModelRouter, output_dir: Path):
    imports = "\n".join([f'import {comp} from "@/components/{comp}";' for comp in section_components])
    components_jsx = "\n".join([f'      <{comp} />' for comp in section_components])
    
    page_code = f"""
import React from 'react';
{imports}

export default function Page() {{
  return (
    <main className="min-h-screen bg-[{spec.theme.background_color}] text-[{spec.theme.text_color}]" style={{{{ fontFamily: "'{spec.theme.font_family}', sans-serif" }}}}>
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
        sans: ["{spec.theme.font_family}", "system-ui", "sans-serif"],
      }}
    }},
  }},
  plugins: [],
}};
export default config;
"""
    with open(output_dir / "tailwind.config.ts", "w", encoding="utf-8") as f:
        f.write(config.strip())

async def generate_next_config(output_dir: Path):
    config = """
/** @type {import('next').NextConfig} */
const nextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
"""
    with open(output_dir / "next.config.mjs", "w", encoding="utf-8") as f:
        f.write(config.strip())

async def generate_global_css(spec: DesignSpec, output_dir: Path):
    """Generate globals.css with Google Font import if applicable."""
    font = spec.theme.font_family
    # Build a Google Fonts import URL for common fonts
    google_font = font.replace(" ", "+")
    css = f"""@import url('https://fonts.googleapis.com/css2?family={google_font}:wght@300;400;500;600;700;800;900&display=swap');

@tailwind base;
@tailwind components;
@tailwind utilities;

* {{
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}}

body {{
  font-family: '{font}', system-ui, sans-serif;
  background-color: {spec.theme.background_color};
  color: {spec.theme.text_color};
}}

html {{
  scroll-behavior: smooth;
}}
"""
    css_path = output_dir / "src" / "app" / "globals.css"
    with open(css_path, "w", encoding="utf-8") as f:
        f.write(css)

async def generate_site(session_id: str, spec: DesignSpec, router: ModelRouter, capture_result=None):
    output_dir = await scaffold_project(session_id)
    
    # If design.md / skills.md were already written by main.py, they survive scaffold
    # because scaffold only copies sandbox_template. But since scaffold does rmtree,
    # we need to re-write them here if capture_result is available.
    if capture_result:
        from .docs import write_design_md, write_skills_md
        write_design_md(spec, capture_result, output_dir)
        write_skills_md(output_dir)
    
    # Generate sections
    components = []
    
    for section in spec.sections:
        comp_name = await generate_section(section, spec, router, output_dir)
        components.append(comp_name)
        
    await generate_page(spec, components, router, output_dir)
    await generate_tailwind_config(spec, output_dir)
    await generate_next_config(output_dir)
    await generate_global_css(spec, output_dir)
    
    return str(output_dir)
