import os
import re
import json
import base64
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional
from .router import ModelRouter, TaskType
from .analyze import DesignSpec

class FileModification(BaseModel):
    filepath: str
    content: str
    
class ModificationResponse(BaseModel):
    updated_files: List[FileModification]
    structural_change: bool = False
    updated_design_spec: Optional[DesignSpec] = None

async def modify_site(
    session_id: str,
    instruction: str,
    current_spec: DesignSpec,
    router: ModelRouter,
    image_bytes: Optional[bytes] = None,
) -> ModificationResponse:
    cwd = Path(f"generated/{session_id}/src")
    
    # Gather file tree and contents (truncated to save tokens)
    files_content = ""
    for root, _, files in os.walk(cwd):
        for file in files:
            if file.endswith(('.tsx', '.ts', '.css')):
                filepath = Path(root) / file
                rel_path = filepath.relative_to(cwd.parent)
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Truncate individual files to 2000 chars to save tokens
                if len(content) > 2000:
                    content = content[:2000] + "\n// ... truncated ..."
                files_content += f"\n--- {rel_path} ---\n{content}\n"
    
    # Truncate total files content
    if len(files_content) > 12000:
        files_content = files_content[:12000] + "\n\n... (more files truncated) ..."

    image_instruction = ""
    if image_bytes:
        image_instruction = """
An image has been provided by the user as a visual reference.
Study the image carefully and use it to guide your modifications.
Match the colors, layout, typography, and spacing you see in the image.
"""

    # Compact design spec (remove nulls to save tokens)
    spec_compact = current_spec.model_dump(exclude_none=True)
    spec_json = json.dumps(spec_compact, indent=1)
    if len(spec_json) > 3000:
        spec_json = spec_json[:3000] + "\n..."

    prompt = f"""You are an expert React/Tailwind developer modifying a generated Next.js website.

User Instruction: "{instruction}"
{image_instruction}

Current Theme:
- Primary: {current_spec.theme.primary_color}, Secondary: {current_spec.theme.secondary_color}
- Background: {current_spec.theme.background_color}, Text: {current_spec.theme.text_color}
- Font: {current_spec.theme.font_family}, Border Radius: {current_spec.theme.border_radius}

Current Sections: {[s.id + '(' + s.type + ')' for s in current_spec.sections]}

Current Files:
{files_content}

RULES:
1. Analyze the instruction. Determine which files need to be changed.
2. Do NOT use `next/image` — use standard `<img>` tags.
3. Use Tailwind CSS arbitrary values for exact colors: bg-[#hex], text-[rgba(...)].
4. Keep framer-motion animations. Add "use client" if using hooks or motion.
5. Return ONLY the files that need changing in updated_files.
6. Each file must have complete, working code — not a diff.
7. Set structural_change to false unless adding/removing entire sections.

Return a JSON matching the required schema. Keep responses concise — output ONLY changed files.
"""
    
    # If user provided an image, use vision model
    images = None
    task_type = TaskType.CODEGEN
    if image_bytes:
        images = [image_bytes]
        task_type = TaskType.VISION_ANALYSIS

    # Try up to 2 attempts
    for attempt in range(2):
        try:
            response = await router.generate(
                task_type=task_type,
                prompt=prompt if attempt == 0 else prompt + "\n\nPREVIOUS ATTEMPT FAILED — the JSON was truncated. Return a SHORTER response. Only modify the minimum number of files needed. Keep file contents brief.",
                images=images,
                response_model=ModificationResponse
            )
            
            assert isinstance(response, ModificationResponse)
            
            # Apply modifications
            for mod in response.updated_files:
                file_path = Path(f"generated/{session_id}") / mod.filepath
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(mod.content)
                    
            return response
        except Exception as e:
            if attempt == 0:
                print(f"[Modify] Attempt 1 failed: {e}. Retrying with shorter prompt...")
                # Truncate files even more aggressively for retry
                files_content = files_content[:6000]
                continue
            raise
