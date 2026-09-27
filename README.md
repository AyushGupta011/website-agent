# AI-Powered Website Cloning Agent

This project is an AI-powered agent that takes a public website URL, analyzes its UI, and generates a new React/Next.js implementation using natural language modifications. 

## Features
- **Provider-agnostic Architecture:** Uses a central Model Router to failover between Groq (Primary) and Google Gemini (Fallback).
- **Vision Analysis:** Extracts structure, layout, typography, and color schemes via headless Chromium (Playwright).
- **Intelligent Generation:** Modular, section-by-section Next.js component code generation for easy, targeted modifications.
- **Auto-Fix Loop:** Compiles generated code (via `tsc` and `next build`) and uses a cheaper LLM to self-correct any build/type errors.
- **Natural Language Modifications:** Supports iterative adjustments via an interactive chat interface.

## Tech Stack
- **Backend:** Python 3.11+, FastAPI, Pydantic v2
- **Scraping:** Playwright (Python)
- **Primary LLM (Groq):** `meta-llama/llama-4-maverick-17b-128e-instruct` (Vision), `moonshotai/kimi-k2-instruct-0905` (Codegen), `openai/gpt-oss-120b` (Fix Loop)
- **Fallback LLM (Gemini):** `gemini-3.7-flash` (Vision & Codegen), `gemini-3.1-flash-lite` (Fix Loop)
- **Frontend / Output UI:** Next.js 14, Tailwind CSS, TypeScript

## Architecture Diagram

```mermaid
flowchart TD
    URL[User URL] --> Capture[Capture Agent (Playwright)]
    Capture --> Analyze[Analyze Agent (Vision Model)]
    Analyze --> DesignSpec[(DesignSpec JSON)]
    DesignSpec --> Generate[Codegen Agent (Text Model)]
    Generate --> Validate[Validation/Fix Agent (Compiler)]
    Validate -- Errors --> Generate
    Validate -- Success --> Preview[Preview Server]
    Preview --> Modify[Modification Agent]
    Modify --> Validate
    
    subgraph Model Router
        Groq[Groq API]
        Gemini[Gemini API Fallback]
    end
    
    Analyze -.-> Model Router
    Generate -.-> Model Router
    Modify -.-> Model Router
```

## Setup Instructions

### Prerequisites
- Node.js & npm (for Next.js compilation & UI)
- Python 3.11+ (for the agent backend)
- `GROQ_API_KEY` and `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) environment variables.

### 1. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# Set API Keys
export GROQ_API_KEY="your_groq_key"
export GEMINI_API_KEY="your_gemini_key"

# Run FastAPI Server
python main.py
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

The frontend will run on `http://localhost:3000`. Enter a URL and watch the agent analyze and clone it!

## Key Implementation Decisions
- **Model Router:** A single bottleneck (`agents/router.py`) abstracts away provider SDKs (Groq and Gemini). All requests are routed through here. If Groq rate-limits or fails, the router falls back to Gemini seamlessly.
- **Targeted Fallbacks:** The router maps specific tasks to specific models (Vision, Codegen, Fix Loop).
- **Style Consistency:** The `DesignSpec.theme` tokens are enforced as a hard prompt constraint during each per-section codegen step. This prevents visual drifting even if a fallback model is invoked mid-generation.
- **Section-by-Section Codegen:** Code generation is split by section (Hero, Navbar, Footer, etc.). This makes generations faster, context windows smaller, and enables cheap localized edits later.
- **Bounded Fix-Loop:** The compiler validation loop is capped at 3 retries, ensuring the system fails gracefully rather than infinitely looping and burning tokens.

## Limitations
- **Visual Exactness:** The agent creates a *structural and thematic clone* (layout, colors, component composition) rather than a pixel-perfect replica.
- **Image Assets:** Uses placeholder images rather than downloading and serving the original site's assets.
- **Single-page focus:** This MVP is built for landing pages and single-page compositions. Complex interactive SPAs will only be captured as static initial states.
