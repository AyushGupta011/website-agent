import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from openai import AsyncOpenAI
async def main():
    client = AsyncOpenAI(base_url='https://integrate.api.nvidia.com/v1', api_key=os.environ.get('NVIDIA_API_KEY'))
    print("Testing deepseek-ai/deepseek-v4.1-flash (image)...")
    try:
        res = await client.chat.completions.create(model='deepseek-ai/deepseek-v4.1-flash', messages=[{'role': 'user', 'content': 'hello'}])
        print("Success!", res.id)
    except Exception as e:
        print("ERROR:", str(e))
        
asyncio.run(main())
