import os
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
    structural_change: bool
    updated_design_spec: Optional[DesignSpec] = None

async def modify_site(session_id: str, instruction: str, current_spec: DesignSpec, router: ModelRouter) -> ModificationResponse:
    cwd = Path(f"generated/{session_id}/src")
    
    # Gather file tree and contents
    files_content = ""
    for root, _, files in os.walk(cwd):
        for file in files:
            if file.endswith(('.tsx', '.ts')):
                filepath = Path(root) / file
                rel_path = filepath.relative_to(cwd.parent)
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                files_content += f"\n--- {rel_path} ---\n{content}\n"

    prompt = f"""
    The user wants to modify the generated Next.js website.
    
    Instruction: "{instruction}"
    
    Current Design Spec:
    {current_spec.model_dump_json(indent=2)}
    
    Current Files:
    {files_content}
    
    Analyze the instruction. Determine which files need to be changed to fulfill it.
    If the instruction is structural (e.g., "add a testimonials section"), set structural_change to true and provide the fully updated_design_spec.
    Return the fully updated contents for ONLY the files that need changing in updated_files.
    """
    
    response = await router.generate(
        task_type=TaskType.CODEGEN,
        prompt=prompt,
        response_model=ModificationResponse,
        max_provider_attempts=2
    )
    
    assert isinstance(response, ModificationResponse)
    
    # Apply modifications
    for mod in response.updated_files:
        file_path = Path(f"generated/{session_id}") / mod.filepath
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(mod.content)
            
    return response
