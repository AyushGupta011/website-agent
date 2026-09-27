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
        
        # Parse error to find the offending file if possible, or just send the error log
        # TypeScript errors usually look like: src/components/Hero.tsx(10,5): error ...
        # Next.js build errors might point to files as well.
        
        match = re.search(r'([a-zA-Z0-9_/\\]+\.tsx?)\(', error_output)
        file_to_fix = match.group(1) if match else None
        
        if file_to_fix:
            file_path = Path(cwd) / file_to_fix
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    file_content = f.read()
            else:
                file_content = "// File not found or couldn't read"
        else:
            # If we can't detect the file, maybe it's page.tsx or we just provide the error and ask which file
            file_to_fix = "src/app/page.tsx" 
            file_path = Path(cwd) / file_to_fix
            with open(file_path, "r", encoding="utf-8") as f:
                file_content = f.read()

        prompt = f"""
        The Next.js build or type check failed. 
        
        Error output:
        {error_output[-2000:]}  # last 2000 chars
        
        File that might be causing the issue ({file_to_fix}):
        ```tsx
        {file_content}
        ```
        
        Please provide the fully corrected contents for this file. 
        Return ONLY the raw code, no markdown formatting, no explanations.
        """
        
        fixed_code = await router.generate(
            task_type=TaskType.FIX_LOOP,
            prompt=prompt,
            max_provider_attempts=2
        )
        
        # Clean markdown
        fixed_code = fixed_code.strip()
        if fixed_code.startswith("```"):
            lines = fixed_code.split("\n")
            if lines[0].startswith("```"): lines = lines[1:]
            if lines and lines[-1].startswith("```"): lines = lines[:-1]
            fixed_code = "\n".join(lines).strip()
            
        # Write back
        if file_path.exists():
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(fixed_code)
                
    # If we exhaust retries and still fail
    ret_tsc, out_tsc, err_tsc = await run_command("npx tsc --noEmit", cwd)
    ret_build, out_build, err_build = await run_command("npx next build", cwd)
    
    if ret_tsc == 0 and ret_build == 0:
        return True
        
    error_output = (out_tsc + "\n" + err_tsc + "\n" + out_build + "\n" + err_build)
    raise Exception(f"Validation failed after {max_retries} retries. Last error:\n{error_output}")
