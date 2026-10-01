"""
Generates design.md (per-site blueprint) and skills.md (static codegen rules)
from capture data and the analyzed DesignSpec.

These files are written into the generated project folder so the codegen agent
can reference them as structured context.
"""
import json
from pathlib import Path
from .capture import CaptureResult
from .analyze import DesignSpec


def write_design_md(spec: DesignSpec, capture: CaptureResult, output_dir: Path) -> str:
    """
    Generates design.md — the per-website blueprint that describes every
    section, color, font, image, and layout detail extracted from the original site.
    """
    sections_md = ""
    for i, section in enumerate(spec.sections, 1):
        items_md = ""
        if section.items:
            for item in section.items:
                items_md += f"  - **{item.title or 'Untitled'}**: {item.description or ''}\n"

        images_md = ""
        if section.image_urls:
            for img in section.image_urls:
                images_md += f"  - `{img}`\n"

        sections_md += f"""
### Section {i}: `{section.id}` (type: `{section.type}`)

| Property     | Value |
|--------------|-------|
| Layout       | `{section.layout}` |
| Headline     | {section.headline or '—'} |
| Subheadline  | {section.subheadline or '—'} |

**Body Text:**
{section.body or '—'}

**Items/Cards:**
{items_md or '  - (none)'}

**Image URLs:**
{images_md or '  - (none)'}

**UI Details (pixel-perfect notes):**
{section.ui_details or '(none captured)'}

**HTML Reference:**
```html
{section.html_reference[:800] if section.html_reference else '(none)'}
```

---
"""

    # Styles table
    styles_md = ""
    if capture.styles:
        styles_md = "| Tag | Class | BG | Color | Font | Size | Weight | Padding | Radius | Layout |\n"
        styles_md += "|-----|-------|----|-------|------|------|--------|---------|--------|--------|\n"
        for s in capture.styles[:20]:
            styles_md += f"| {s.get('tag','')} | {s.get('cls','')[:30]} | {s.get('bg','')} | {s.get('color','')} | {s.get('ff','')} | {s.get('fs','')} | {s.get('fw','')} | {s.get('p','')} | {s.get('br','')} | {s.get('display','')} {s.get('fd','')} |\n"

    content = f"""# Design Blueprint — {spec.title}

> Auto-generated from `{capture.url}`  
> This file is the single source of truth for the codegen agent.

## 1. Site Metadata

| Property    | Value |
|-------------|-------|
| Title       | {spec.title} |
| Description | {spec.description or '—'} |
| URL         | {capture.url} |

## 2. Theme

| Token            | Value |
|------------------|-------|
| Primary Color    | `{spec.theme.primary_color}` |
| Secondary Color  | `{spec.theme.secondary_color}` |
| Background Color | `{spec.theme.background_color}` |
| Text Color       | `{spec.theme.text_color}` |
| Font Family      | `{spec.theme.font_family}` |
| Border Radius    | `{spec.theme.border_radius}` |

**Dominant Colors (extracted):** {', '.join(f'`{c}`' for c in capture.colors)}

**Fonts (extracted):** {', '.join(f'`{f}`' for f in capture.fonts)}

## 3. Navigation

| Property  | Value |
|-----------|-------|
| Logo Text | {spec.navigation.logo_text or '—'} |
| Links     | {', '.join(spec.navigation.links) if spec.navigation.links else '—'} |
| Sticky    | {'Yes' if spec.navigation.sticky else 'No'} |

**Nav UI Details:**
{spec.navigation.ui_details or '(none)'}

## 4. Sections

{sections_md}

## 5. Extracted Computed Styles

{styles_md or '(no styles extracted)'}

## 6. All Image URLs

{chr(10).join(f'- `{img}`' for img in capture.images[:20]) if capture.images else '(none)'}

## 7. Background Images

{chr(10).join(f'- `{img}`' for img in capture.background_images[:10]) if capture.background_images else '(none)'}

## 8. Viewport Screenshots

{len(capture.sections)} viewport screenshots were captured by scrolling down the page.
Each screenshot covers ~800px of vertical content.
"""

    design_path = output_dir / "design.md"
    with open(design_path, "w", encoding="utf-8") as f:
        f.write(content)

    return content


def write_skills_md(output_dir: Path) -> str:
    """
    Generates skills.md — static rules and best practices the codegen agent
    must follow when generating React/Tailwind components from the design blueprint.
    """
    content = """# Skills — Codegen Agent Rules

> These rules govern how the AI code generator turns `design.md` into React components.
> Every generated component MUST comply with ALL rules below.

## 1. Component Structure

- Each section from `design.md` becomes ONE React component file in `src/components/`.
- File name: `{SectionId}.tsx` where `SectionId` is the capitalized section id.
- Every component MUST use `export default function ComponentName() { ... }`.
- If the component uses React hooks (`useState`, `useEffect`) or `framer-motion`,
  it MUST start with `"use client";` on the very first line.

## 2. Styling — Tailwind CSS with Arbitrary Values

- Use **Tailwind CSS** for all styling. No inline `style={{}}` except for `fontFamily`.
- When exact color values are known (hex, rgba), use Tailwind arbitrary values:
  - `bg-[#1a1a2e]`, `text-[rgba(255,255,255,0.8)]`, `border-[#333]`
- When exact spacing is known, use arbitrary values:
  - `p-[20px]`, `gap-[32px]`, `mt-[80px]`
- When exact font details are known:
  - `text-[18px]`, `font-[700]`, `leading-[1.6]`, `tracking-[0.02em]`
- **Never approximate** a known value with a generic Tailwind class.
  - ❌ `bg-blue-500` when the actual color is `#2563eb`
  - ✅ `bg-[#2563eb]`

## 3. Content Fidelity

- Use the **EXACT text** from `design.md` — headlines, subheadlines, body, card titles.
- **NEVER** substitute with placeholder text like "Lorem ipsum", "Welcome to Our Site",
  "We build amazing products", etc.
- If a text field is `—` or empty in `design.md`, omit that element entirely.

## 4. Images

- Use standard `<img>` tags. **Never** use `next/image` (causes unconfigured host errors).
- Use the actual image URLs from `design.md` Section → Image URLs.
- If no image URL is available, use a solid color `<div>` matching the theme as placeholder:
  ```tsx
  <div className="w-full h-64 bg-[#1a1a2e] rounded-lg" />
  ```
- For background images, use Tailwind's `bg-[url('...')]` or inline `backgroundImage`.

## 5. Layout Matching

- Match the exact layout described in `UI Details`:
  - If it says "3-column grid", use `grid grid-cols-3`.
  - If it says "flex row with gap-8", use `flex flex-row gap-8`.
  - If it says "centered with max-w-6xl", use `max-w-6xl mx-auto`.
- Read the `Extracted Computed Styles` table in `design.md` for exact
  padding, border-radius, flex direction, and gap values.

## 6. Animations & Interactions

- Use `framer-motion` for entrance animations (fade-in, slide-up).
- Typical pattern:
  ```tsx
  import { motion } from "framer-motion";
  
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    whileInView={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.6 }}
    viewport={{ once: true }}
  >
  ```
- Use `lucide-react` for any icons (menu, arrow, check, etc.).

## 7. Responsive Design

- All components must be responsive.
- Use Tailwind responsive prefixes: `md:`, `lg:`, `xl:`.
- Mobile: single column, stacked layout.
- Desktop: match the exact column count and layout from `UI Details`.

## 8. Navigation

- If the section type is `navbar`, read the Navigation spec from `design.md`.
- Include all nav links. Add a mobile hamburger menu using `useState`.
- If `sticky: true`, use `sticky top-0 z-50`.

## 9. Forbidden Patterns

- ❌ `import Image from "next/image"` — causes build errors.
- ❌ Generic placeholder text — always use real content.
- ❌ `export const Component` — must be `export default function`.
- ❌ Hardcoded `className="text-blue-500"` when exact hex is available.
- ❌ Missing `"use client"` when using hooks or framer-motion.

## 10. Output Format

- Wrap the entire component code in ```tsx ... ``` markdown fences.
- No conversational text, explanations, or commentary outside the code block.
"""

    skills_path = output_dir / "skills.md"
    with open(skills_path, "w", encoding="utf-8") as f:
        f.write(content)

    return content
