import asyncio
import os
import re
from pathlib import Path
from .router import ModelRouter, TaskType

async def run_command(cmd: str, cwd: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()

async def validate_and_fix(session_id: str, router: ModelRouter, max_retries: int = 3):
    cwd = f"generated/{session_id}"
    
    # 1. Install dependencies (if not already installed)
    if not os.path.exists(f"{cwd}/node_modules"):
        print(f"[{session_id}] Running npm install...")
        ret, out, err = await run_command("npm install", cwd)
        if ret != 0:
            raise Exception(f"npm install failed: {err}")
            
    # Add lucide-react just in case the AI used it
    await run_command("npm install lucide-react", cwd)
            
    # Fix loop
    for attempt in range(max_retries):
        print(f"[{session_id}] Validation attempt {attempt+1}/{max_retries}...")
        
        # 2. Type check
        ret_tsc, out_tsc, err_tsc = await run_command("npx tsc --noEmit", cwd)
        
        # 3. Build check
        ret_build, out_build, err_build = await run_command("npx next build", cwd)
        
        if ret_tsc == 0 and ret_build == 0:
            print(f"[{session_id}] Validation passed!")
            return True
            
        error_output = ""
        if ret_tsc != 0:
            error_output += out_tsc + "\n" + err_tsc
        if ret_build != 0:
            error_output += out_build + "\n" + err_build
            
        print(f"[{session_id}] Validation failed. Requesting fix...")
        
        # Parse error to find the offending files
        # Look for all .tsx files mentioned
        file_matches = re.findall(r'([a-zA-Z0-9_/\\]+\.tsx?)', error_output)
        
        # Deduplicate and filter out node_modules
        unique_files = list(set([f for f in file_matches if "node_modules" not in f]))
        
        # Default to page.tsx if nothing found
        if not unique_files:
            unique_files = ["src/app/page.tsx"]
            
        files_content = ""
        for f in unique_files:
            # Clean up the path, sometimes it has absolute path, make it relative to cwd
            # e.g. C:/.../generated/xyz/src/components/Promo.tsx -> src/components/Promo.tsx
            rel_path = f
            if session_id in f:
                rel_path = f.split(session_id)[-1].strip("\\/")
            
            p = Path(cwd) / rel_path
            if p.exists():
                with open(p, "r", encoding="utf-8") as file_obj:
                    files_content += f"\n--- {rel_path} ---\n```tsx\n{file_obj.read()}\n```\n"

        prompt = f"""
        The Next.js build or type check failed. 
        
        Error output:
        {error_output[-2000:]}  # last 2000 chars
        
        Files that might be causing the issue:
        {files_content}
        
        Please provide the fully corrected contents for the file(s) that caused the error.
        If you need to fix multiple files, wrap EACH file's code in a markdown block prefixed with the filename, like this:
        
        ### src/components/Broken.tsx
        ```tsx
        export default function Broken() {{ return <div />; }}
        ```
        """
        
        fixed_code = await router.generate(
            task_type=TaskType.FIX_LOOP,
            prompt=prompt,
            max_provider_attempts=2
        )
        
        # Parse multiple files from LLM response
        # We look for ### filename followed by ```...```
        pattern = r"###\s*([^\n]+)\s*```[a-zA-Z]*\n(.*?)```"
        matches = re.findall(pattern, fixed_code, re.DOTALL)
        
        if matches:
            for filepath, content in matches:
                filepath = filepath.strip()
                content = content.strip()
                p = Path(cwd) / filepath
                if p.exists():
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(content)
        else:
            # Fallback if the AI just outputted a single block without ### filename
            match_code = re.search(r"```[a-zA-Z]*\n(.*?)```", fixed_code, re.DOTALL)
            if match_code:
                content = match_code.group(1).strip()
                # Just write to the first unique file we found
                if unique_files:
                    f_to_write = unique_files[0]
                    if session_id in f_to_write:
                        f_to_write = f_to_write.split(session_id)[-1].strip("\\/")
                    p = Path(cwd) / f_to_write
                    if p.exists():
                        with open(p, "w", encoding="utf-8") as f:
                            f.write(content)
                
    # If we exhaust retries and still fail
    ret_tsc, out_tsc, err_tsc = await run_command("npx tsc --noEmit", cwd)
    ret_build, out_build, err_build = await run_command("npx next build", cwd)
    
    if ret_tsc == 0 and ret_build == 0:
        return True
        
    error_output = (out_tsc + "\n" + err_tsc + "\n" + out_build + "\n" + err_build)
    raise Exception(f"Validation failed after {max_retries} retries. Last error:\n{error_output}")
