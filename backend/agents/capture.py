import asyncio
import base64
from collections import Counter
from pydantic import BaseModel
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

class CaptureResult(BaseModel):
    url: str
    screenshot: str  # Base64 encoded PNG
    html: str
    images: List[str]
    styles: List[Dict[str, str]]
    colors: List[str]
    error: Optional[str] = None

async def capture(url: str) -> CaptureResult:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={'width': 1280, 'height': 800},
            )
            
            try:
                await page.goto(url, wait_until="networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                # Fallback
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    await browser.close()
                    return CaptureResult(url=url, screenshot="", html="", images=[], styles=[], colors=[], error=f"Navigation failed: {e}")

            # Cap resolution by resizing viewport for the screenshot if page is too tall?
            # We'll just take a full page screenshot, Playwright can handle it.
            # But the prompt says "capped in resolution to control vision-call token cost".
            # Let's evaluate script to cap body height, or just take viewport screenshot.
            # "Full-page screenshot... capped in resolution"
            # We can scale it down in python or just restrict the height in playwright.
            
            # Let's take a screenshot of max height 2000px
            await page.evaluate("() => { document.body.style.maxHeight = '2000px'; document.body.style.overflow = 'hidden'; }")
            screenshot_bytes = await page.screenshot(full_page=True, type='png')
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')

            # Extract <body> without scripts
            html = await page.evaluate('''() => {
                const clone = document.body.cloneNode(true);
                const scripts = clone.querySelectorAll('script');
                scripts.forEach(s => s.remove());
                return clone.outerHTML;
            }''')

            # Extract images
            images = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('img')).map(img => img.src).filter(Boolean);
            }''')

            # Extract styles for sampled elements (nav, header, section, footer, headings)
            style_data = await page.evaluate('''() => {
                const elements = document.querySelectorAll('nav, header, section, footer, h1, h2, h3, a.btn, button, .hero, .cta');
                const result = [];
                const maxElements = 40;
                let count = 0;
                for (const el of elements) {
                    if (count >= maxElements) break;
                    const style = window.getComputedStyle(el);
                    if (style.display !== 'none' && style.visibility !== 'hidden') {
                        result.push({
                            tag: el.tagName,
                            className: el.className,
                            backgroundColor: style.backgroundColor,
                            color: style.color,
                            fontFamily: style.fontFamily,
                            fontSize: style.fontSize,
                            padding: style.padding,
                            borderRadius: style.borderRadius
                        });
                        count++;
                    }
                }
                return result;
            }''')

            # Compute dominant colors
            color_counter = Counter()
            for s in style_data:
                bg = s.get('backgroundColor')
                color = s.get('color')
                # Ignore transparent/rgba(0,0,0,0)
                if bg and bg != 'rgba(0, 0, 0, 0)' and bg != 'transparent':
                    color_counter[bg] += 2  # Weight backgrounds more
                if color and color != 'rgba(0, 0, 0, 0)' and color != 'transparent':
                    color_counter[color] += 1
            
            top_colors = [color for color, count in color_counter.most_common(5)]

            await browser.close()
            return CaptureResult(
                url=url,
                screenshot=screenshot_b64,
                html=html,
                images=list(set(images)),
                styles=style_data,
                colors=top_colors
            )
            
    except Exception as e:
        return CaptureResult(url=url, screenshot="", html="", images=[], styles=[], colors=[], error=str(e))
