import asyncio
import os
from agents.router import ModelRouter, TaskType

async def test():
    router = ModelRouter()
    prompt = "Write a React component for a Navbar. Make it at least 20 lines long. Wrap in ```tsx ... ```"
    
    try:
        res = await router.generate(TaskType.CODEGEN, prompt)
        print("RESULT:")
        print(res)
    except Exception as e:
        print("ERROR:", e)

if __name__ == '__main__':
    asyncio.run(test())
