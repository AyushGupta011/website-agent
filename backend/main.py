import uuid
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

from agents.router import ModelRouter
from agents.capture import capture
from agents.analyze import analyze, DesignSpec
from agents.generate import generate_site
from agents.validate import validate_and_fix
from agents.preview import start_preview, get_preview_url
from agents.modify import modify_site
from agents.docs import write_design_md, write_skills_md

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = ModelRouter()

# In-memory state
sessions: Dict[str, Dict[str, Any]] = {}

class GenerateRequest(BaseModel):
    url: str

async def pipeline_worker(session_id: str, url: str):
    try:
        sessions[session_id]["status"] = "capturing"
        capture_result = await capture(url)
        if capture_result.error:
            raise Exception(f"Capture error: {capture_result.error}")
            
        sessions[session_id]["status"] = "analyzing"
        design_spec = await analyze(capture_result, router)
        sessions[session_id]["spec"] = design_spec
        
        # Generate design.md and skills.md blueprints
        sessions[session_id]["status"] = "writing_blueprints"
        from pathlib import Path
        output_dir = Path(f"generated/{session_id}")
        output_dir.mkdir(parents=True, exist_ok=True)
        design_content = write_design_md(design_spec, capture_result, output_dir)
        skills_content = write_skills_md(output_dir)
        print(f"[{session_id}] Written design.md and skills.md")
        
        sessions[session_id]["status"] = "generating"
        await generate_site(session_id, design_spec, router, capture_result)
        
        sessions[session_id]["status"] = "validating"
        await validate_and_fix(session_id, router)
        
        sessions[session_id]["status"] = "starting_preview"
        preview_url = await start_preview(session_id)
        
        sessions[session_id]["preview_url"] = preview_url
        sessions[session_id]["status"] = "complete"
    except Exception as e:
        import traceback
        traceback.print_exc()
        sessions[session_id]["status"] = "error"
        sessions[session_id]["error"] = traceback.format_exc()
        
async def modify_worker(session_id: str, instruction: str, image_bytes: bytes = None):
    try:
        sessions[session_id]["status"] = "modifying"
        spec = sessions[session_id]["spec"]
        
        mod_res = await modify_site(session_id, instruction, spec, router, image_bytes=image_bytes)
        
        if mod_res.structural_change and mod_res.updated_design_spec:
            sessions[session_id]["spec"] = mod_res.updated_design_spec
            
        sessions[session_id]["status"] = "validating_modifications"
        await validate_and_fix(session_id, router)
        
        sessions[session_id]["status"] = "restarting_preview"
        preview_url = await start_preview(session_id)
        
        sessions[session_id]["preview_url"] = preview_url
        sessions[session_id]["status"] = "complete"
    except Exception as e:
        import traceback
        traceback.print_exc()
        sessions[session_id]["status"] = "error"
        sessions[session_id]["error"] = traceback.format_exc()

@app.post("/generate")
async def generate_endpoint(req: GenerateRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "status": "pending",
        "url": req.url
    }
    background_tasks.add_task(pipeline_worker, session_id, req.url)
    return {"session_id": session_id}

@app.get("/status/{session_id}")
async def get_status(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]

@app.get("/preview/{session_id}")
async def get_preview(session_id: str):
    url = get_preview_url(session_id)
    if not url:
        raise HTTPException(status_code=404, detail="Preview not running")
    return {"preview_url": url}

@app.post("/modify/{session_id}")
async def modify_endpoint(
    session_id: str,
    background_tasks: BackgroundTasks,
    instruction: str = Form(...),
    image: Optional[UploadFile] = File(None),
):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    image_bytes = None
    if image:
        image_bytes = await image.read()
    
    background_tasks.add_task(modify_worker, session_id, instruction, image_bytes)
    return {"status": "modification_started"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
