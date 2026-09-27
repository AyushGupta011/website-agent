import os
import json
from enum import Enum
from typing import Optional, List, Type
from pydantic import BaseModel
import asyncio

# Note: We'll install groq and google-genai
try:
    from groq import AsyncGroq, APIStatusError, APITimeoutError, RateLimitError as GroqRateLimitError
except ImportError:
    pass

try:
    from google import genai
    from google.genai import types
    from google.genai.errors import APIError
except ImportError:
    pass

class TaskType(str, Enum):
    VISION_ANALYSIS = "vision_analysis"
    CODEGEN = "codegen"
    FIX_LOOP = "fix_loop"

class ProviderSpec(BaseModel):
    name: str            # "groq" | "gemini"
    model: str
    supports_vision: bool

ROUTING_TABLE: dict[TaskType, list[ProviderSpec]] = {
    TaskType.VISION_ANALYSIS: [
        ProviderSpec(name="groq", model="meta-llama/llama-4-maverick-17b-128e-instruct", supports_vision=True),
        ProviderSpec(name="gemini", model="gemini-3.7-flash", supports_vision=True),
    ],
    TaskType.CODEGEN: [
        ProviderSpec(name="groq", model="moonshotai/kimi-k2-instruct-0905", supports_vision=False),
        ProviderSpec(name="gemini", model="gemini-3.7-flash", supports_vision=False),
    ],
    TaskType.FIX_LOOP: [
        ProviderSpec(name="groq", model="openai/gpt-oss-120b", supports_vision=False),
        ProviderSpec(name="gemini", model="gemini-3.1-flash-lite", supports_vision=False),
    ],
}

class ProviderTimeoutError(Exception): pass
class ProviderServerError(Exception): pass
class RateLimitError(Exception): pass
class AllProvidersFailedError(Exception):
    def __init__(self, task_type: TaskType, last_error: Exception):
        super().__init__(f"All providers failed for task {task_type}. Last error: {last_error}")

class ModelRouter:
    """Tries each provider in ROUTING_TABLE[task_type] in order, falling back on failure."""
    def __init__(self):
        self.groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", "")) if os.environ.get("GROQ_API_KEY") else None
        self.gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))) if (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")) else None

    async def generate(
        self,
        task_type: TaskType,
        prompt: str,
        images: Optional[List[bytes]] = None,
        response_model: Optional[Type[BaseModel]] = None,
        max_provider_attempts: Optional[int] = None,
    ) -> str | BaseModel:
        chain = ROUTING_TABLE[task_type]
        last_error: Exception | None = None
        
        # Determine if we should attempt JSON parsing natively or rely on structured output
        
        for provider in chain[:max_provider_attempts]:
            try:
                # Add instructions for JSON output if response_model is provided
                augmented_prompt = prompt
                if response_model:
                    augmented_prompt += "\n\nReturn ONLY a valid JSON object matching the requested schema, no markdown fences, no commentary."
                
                raw = await self._call_provider(provider, augmented_prompt, images)
                
                if response_model:
                    try:
                        return self._validate(raw, response_model)
                    except Exception as e:
                        # Retry once with error appended
                        retry_prompt = augmented_prompt + f"\n\nThe previous attempt returned invalid JSON. Error: {str(e)}\nPrevious output:\n{raw}\nPlease fix the JSON."
                        raw = await self._call_provider(provider, retry_prompt, images)
                        return self._validate(raw, response_model)
                        
                return raw
            except (RateLimitError, ProviderTimeoutError, ProviderServerError) as e:
                print(f"[Router] Provider {provider.name} failed with {type(e).__name__}: {str(e)}. Falling back...")
                last_error = e
                continue
            except Exception as e:
                print(f"[Router] Unexpected error with provider {provider.name}: {str(e)}. Falling back...")
                last_error = e
                continue
                
        raise AllProvidersFailedError(task_type, last_error)

    def _validate(self, raw: str, response_model: Type[BaseModel]) -> BaseModel:
        # Strip markdown fences if present
        clean_raw = raw.strip()
        if clean_raw.startswith("```"):
            lines = clean_raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_raw = "\n".join(lines).strip()
        
        return response_model.model_validate_json(clean_raw)

    async def _call_provider(self, provider: ProviderSpec, prompt: str, images: Optional[List[bytes]]) -> str:
        if provider.name == "groq":
            return await self._call_groq(provider.model, prompt, images)
        elif provider.name == "gemini":
            return await self._call_gemini(provider.model, prompt, images)
        raise ValueError(f"unknown provider {provider.name}")

    async def _call_groq(self, model: str, prompt: str, images: Optional[List[bytes]]) -> str:
        if not self.groq_client:
            raise ProviderServerError("Groq client not initialized")
            
        messages = []
        content = [{"type": "text", "text": prompt}]
        
        if images:
            import base64
            for img_bytes in images:
                base64_image = base64.b64encode(img_bytes).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64_image}",
                    }
                })
        messages.append({"role": "user", "content": content})
        
        try:
            response = await self.groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
        except Exception as e: # Catch groq specific exceptions and map them
            error_str = str(e).lower()
            if "rate limit" in error_str or "429" in error_str:
                raise RateLimitError(str(e))
            elif "timeout" in error_str:
                raise ProviderTimeoutError(str(e))
            elif "50" in error_str: # 500, 502, 503, 504
                raise ProviderServerError(str(e))
            raise e
            
    async def _call_gemini(self, model: str, prompt: str, images: Optional[List[bytes]]) -> str:
        if not self.gemini_client:
            raise ProviderServerError("Gemini client not initialized")
            
        contents = []
        if images:
            for img_bytes in images:
                contents.append(
                    types.Part.from_bytes(
                        data=img_bytes,
                        mime_type='image/png'
                    )
                )
        contents.append(prompt)
        
        try:
            # Note: genai client is synchronous by default unless using async client. 
            # We'll use asyncio to run it in threadpool if it's sync, or use async if available.
            # The new genai SDK supports async via client.aio
            response = await self.gemini_client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.1
                )
            )
            return response.text
        except APIError as e:
            if e.code == 429:
                raise RateLimitError(str(e))
            elif e.code in [500, 502, 503, 504]:
                raise ProviderServerError(str(e))
            raise e
        except Exception as e:
            error_str = str(e).lower()
            if "timeout" in error_str:
                raise ProviderTimeoutError(str(e))
            raise e
