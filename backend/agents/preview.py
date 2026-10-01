import asyncio
import socket
from typing import Dict
import psutil

# Track preview processes: session_id -> (process, port)
active_previews: Dict[str, tuple[asyncio.subprocess.Process, int]] = {}

def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def kill_process_tree(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass

async def start_preview(session_id: str) -> str:
    cwd = f"generated/{session_id}"
    
    # Kill existing preview for this session if any
    if session_id in active_previews:
        proc, _ = active_previews[session_id]
        kill_process_tree(proc.pid)
        del active_previews[session_id]
        
    port = get_free_port()
    
    # Start next dev
    process = await asyncio.create_subprocess_shell(
        f"npx next dev -p {port}",
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    active_previews[session_id] = (process, port)
    
    # Wait for the server to be fully ready by polling it
    import urllib.request
    
    def ping():
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}")
            return resp.getcode() == 200
        except Exception:
            return False

    for _ in range(30):
        is_ready = await asyncio.to_thread(ping)
        if is_ready:
            break
        await asyncio.sleep(1)
        
    return f"http://localhost:{port}"

def get_preview_url(session_id: str) -> str | None:
    if session_id in active_previews:
        _, port = active_previews[session_id]
        return f"http://localhost:{port}"
    return None
