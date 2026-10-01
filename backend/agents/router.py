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

try:
    from openai import AsyncOpenAI
    import openai
except ImportError:
    pass

class TaskType(str, Enum):
    VISION_ANALYSIS = "vision_analysis"
    CODEGEN = "codegen"
    FIX_LOOP = "fix_loop"

class ProviderSpec(BaseModel):
    name: str            # "groq" | "gemini" | "nvidia"
    model: str
    supports_vision: bool

ROUTING_TABLE: dict[TaskType, list[ProviderSpec]] = {
    TaskType.VISION_ANALYSIS: [
        ProviderSpec(name="gemini", model="gemini-2.5-pro", supports_vision=True),
        ProviderSpec(name="gemini", model="gemini-2.5-flash", supports_vision=True),
        ProviderSpec(name="nvidia", model="moonshotai/kimi-k3", supports_vision=True),
        ProviderSpec(name="nvidia", model="meta/muse-glimmer-30b", supports_vision=True),
        ProviderSpec(name="nvidia", model="nvidia/ising-calibration-1.5-31b", supports_vision=True),
        ProviderSpec(name="gemini", model="gemini-3.5-flash-lite", supports_vision=True),
    ],
    TaskType.CODEGEN: [
        ProviderSpec(name="groq", model="llama3-70b-8192", supports_vision=False),
        ProviderSpec(name="nvidia", model="z-ai/glm-5.3", supports_vision=False),
        ProviderSpec(name="nvidia", model="deepseek-ai/deepseek-v4.1-flash", supports_vision=False),
        ProviderSpec(name="nvidia", model="nvidia/nemotron-parse-2.0", supports_vision=False),
        ProviderSpec(name="gemini", model="gemini-2.5-pro", supports_vision=False),
     
        ProviderSpec(name="gemini", model="gemini-2.5-flash", supports_vision=False),
        ProviderSpec(name="groq", model="openai/gpt-oss-20b", supports_vision=False),
        ProviderSpec(name="groq", model="qwen/qwen3.8-27b", supports_vision=False),
    ],
    TaskType.FIX_LOOP: [
        ProviderSpec(name="groq", model="llama3-70b-8192", supports_vision=False),
        ProviderSpec(name="nvidia", model="z-ai/glm-5.3", supports_vision=False),
        ProviderSpec(name="nvidia", model="deepseek-ai/deepseek-v4.1-flash", supports_vision=False),
        ProviderSpec(name="nvidia", model="nvidia/nemotron-parse-2.0", supports_vision=False),
        ProviderSpec(name="gemini", model="gemini-2.5-pro", supports_vision=False),
        ProviderSpec(name="groq", model="llama-3.1-70b-versatile", supports_vision=False),
        ProviderSpec(name="gemini", model="gemini-2.5-flash", supports_vision=False),
        ProviderSpec(name="groq", model="llama3-70b-8192", supports_vision=False),
        ProviderSpec(name="groq", model="openai/gpt-oss-20b", supports_vision=False),
        ProviderSpec(name="groq", model="qwen/qwen3.8-27b", supports_vision=False),
        
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
        self.nvidia_client = AsyncOpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=os.environ.get("NVIDIA_API_KEY", ""), timeout=90.0) if os.environ.get("NVIDIA_API_KEY") else None

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
        
        for provider in chain[:max_provider_attempts]:
            # Add up to 5 retries for 503/429 errors per provider
            retries = 5
            for attempt in range(retries):
                try:
                    augmented_prompt = prompt
                    if response_model:
                        schema_json = response_model.model_json_schema()
                        augmented_prompt += f"\n\nReturn ONLY a valid JSON object matching this schema:\n{json.dumps(schema_json, indent=2)}\nNo markdown fences, no commentary."
                    
                    # Limit images and text for Groq to avoid token limits
                    images_to_send = images
                    if provider.name == "groq":
                        # Only apply aggressive truncation for VISION tasks
                        # The qwen vision model has a 7000 ITPM limit
                        # The gpt-oss codegen models have much higher limits
                        if task_type == TaskType.VISION_ANALYSIS:
                            # Truncate prompt safely, preserving schema
                            schema_part = ""
                            base_prompt = augmented_prompt
                            if response_model:
                                schema_json = response_model.model_json_schema()
                                schema_str = f"\n\nReturn ONLY a valid JSON object matching this schema:\n{json.dumps(schema_json, indent=2)}\nNo markdown fences, no commentary."
                                if augmented_prompt.endswith(schema_str):
                                    base_prompt = augmented_prompt[:-len(schema_str)]
                                    schema_part = schema_str
                            
                            # Truncate base prompt to ~3500 chars to be ultra safe
                            if len(base_prompt) > 3500:
                                base_prompt = base_prompt[:3200] + "\n...[TRUNCATED]"
                                
                            augmented_prompt = base_prompt + schema_part
                            
                            # Qwen vision model consumes ~6000 tokens for ANY image.
                            # Send ZERO images for the fallback.
                            images_to_send = []
                        else:
                            # For CODEGEN/FIX_LOOP, just strip images (not needed)
                            images_to_send = []

                    raw = await self._call_provider(provider, augmented_prompt, images_to_send)
                    
                    if response_model:
                        try:
                            return self._validate(raw, response_model)
                        except Exception as e:
                            retry_prompt = augmented_prompt + f"\n\nThe previous attempt returned invalid JSON. Error: {str(e)}\nPrevious output:\n{raw}\nPlease fix the JSON."
                            raw = await self._call_provider(provider, retry_prompt, images_to_send)
                            return self._validate(raw, response_model)
                            
                    return raw
                except (RateLimitError, ProviderServerError) as e:
                    error_str = str(e).lower()
                    # Do not retry if we hit a hard daily quota limit
                    if "quota exceeded" in error_str and "free_tier_requests" in error_str:
                        print(f"[Router] {provider.name} hard quota exceeded. Falling back immediately...")
                        last_error = e
                        break
                        
                    if attempt < retries - 1:
                        # Exponential backoff: 5s, 10s, 20s, 40s
                        wait_time = 5 * (2 ** attempt)
                        print(f"[Router] {provider.name} failed with {type(e).__name__} ({str(e)}). Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        print(f"[Router] {provider.name} exhausted retries. Falling back...")
                        last_error = e
                        break
                except ProviderTimeoutError as e:
                    print(f"[Router] Provider {provider.name} timed out. Falling back...")
                    last_error = e
                    break
                except Exception as e:
                    print(f"[Router] Unexpected error with provider {provider.name}: {type(e).__name__} {str(e)}. Falling back...")
                    last_error = e
                    break
                
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
        elif provider.name == "nvidia":
            return await self._call_nvidia(provider.model, prompt, images)
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
                max_tokens=8000,
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
                        mime_type='image/jpeg'
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
                    temperature=0.1,
                    max_output_tokens=8192,
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

    async def _call_nvidia(self, model: str, prompt: str, images: Optional[List[bytes]]) -> str:
        if not self.nvidia_client:
            raise ProviderServerError("NVIDIA client not initialized")
            
        messages = []
        content = [{"type": "text", "text": prompt}]
        
        if images:
            import base64
            for img_bytes in images:
                base64_image = base64.b64encode(img_bytes).decode("utf-8")
                # Ensure correct MIME type, assuming image/png or image/jpeg, NIM typically supports base64 image_url
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                    }
                })
        messages.append({"role": "user", "content": content})
        
        try:
            response = await self.nvidia_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=8192,
            )
            return response.choices[0].message.content or ""
        except openai.RateLimitError as e:
            raise RateLimitError(str(e))
        except openai.APITimeoutError as e:
            raise ProviderTimeoutError(str(e))
        except openai.APIError as e:
            raise ProviderServerError(str(e))
        except Exception as e:
            raise ProviderServerError(str(e))

