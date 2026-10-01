import asyncio
import base64
import io
import re
from collections import Counter
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from PIL import Image

class SectionCapture(BaseModel):
    """One viewport-sized screenshot + its corresponding HTML chunk."""
    screenshot_b64: str   # base64 JPEG
    html_chunk: str       # cleaned HTML for that scroll region
    scroll_y: int         # where on the page this was taken

class CaptureResult(BaseModel):
    url: str
    sections: List[SectionCapture]      # per-viewport screenshots
    full_html: str                       # full cleaned <body> HTML
    images: List[str]
    styles: List[Dict[str, Any]]
    colors: List[str]
    fonts: List[str]
    background_images: List[str]
    gradients: List[str] = []
    animations: List[Dict[str, str]] = []
    box_shadows: List[str] = []
    hover_styles: List[Dict[str, str]] = []
    error: Optional[str] = None

def _resize_screenshot(screenshot_bytes: bytes, max_width: int = 1024) -> str:
    """Resize & compress a screenshot, return base64 JPEG."""
    img = Image.open(io.BytesIO(screenshot_bytes))
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

async def capture(url: str) -> CaptureResult:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 800})

            # --- Navigate ---
            try:
                await page.goto(url, wait_until="networkidle", timeout=45000)
            except PlaywrightTimeoutError:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    await browser.close()
                    return CaptureResult(url=url, sections=[], full_html="", images=[], styles=[], colors=[], fonts=[], background_images=[], error=f"Navigation failed: {e}")

            # Wait a bit for lazy-loaded content / animations
            await asyncio.sleep(2)

            # --- Dismiss cookie banners / popups ---
            for selector in [
                "button:has-text('Accept')", "button:has-text('Got it')",
                "button:has-text('Close')", "button:has-text('OK')",
                "[class*='cookie'] button", "[class*='consent'] button",
                "[class*='popup'] button[class*='close']",
            ]:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=500):
                        await btn.click()
                        await asyncio.sleep(0.3)
                except:
                    pass

            # --- Get page dimensions ---
            page_height = await page.evaluate("() => document.body.scrollHeight")
            viewport_h = 800

            # --- Scroll & capture viewport-by-viewport ---
            section_captures: List[SectionCapture] = []
            max_screenshots = 10  # cap to control token budget, increased for better coverage
            step = max(viewport_h, page_height // max_screenshots)

            scroll_positions = list(range(0, page_height, step))
            if len(scroll_positions) > max_screenshots:
                scroll_positions = scroll_positions[:max_screenshots]

            for y in scroll_positions:
                await page.evaluate(f"window.scrollTo(0, {y})")
                await asyncio.sleep(0.5)  # let animations / lazy-load settle

                shot = await page.screenshot(type="jpeg", quality=75)
                b64 = _resize_screenshot(shot, max_width=1024)

                # Extract visible elements' outerHTML in current viewport
                html_chunk = await page.evaluate("""(scrollY) => {
                    const vh = window.innerHeight;
                    const top = scrollY;
                    const bot = scrollY + vh;
                    const els = document.querySelectorAll('nav, header, section, main, article, div, footer');
                    const seen = new Set();
                    let html = '';
                    for (const el of els) {
                        const r = el.getBoundingClientRect();
                        const elTop = r.top + window.scrollY;
                        const elBot = r.bottom + window.scrollY;
                        if (elBot > top && elTop < bot && !seen.has(el)) {
                            // Only grab top-level visible blocks (skip deeply nested)
                            if (el.parentElement && seen.has(el.parentElement)) continue;
                            seen.add(el);
                            // Clean clone: remove scripts, style tags, svg innards
                            const clone = el.cloneNode(true);
                            clone.querySelectorAll('script, style, noscript').forEach(s => s.remove());
                            // Truncate very long text nodes
                            html += clone.outerHTML.substring(0, 3000) + '\\n';
                        }
                        if (html.length > 8000) break;
                    }
                    return html.substring(0, 8000);
                }""", y)

                section_captures.append(SectionCapture(
                    screenshot_b64=b64,
                    html_chunk=html_chunk,
                    scroll_y=y
                ))

            # --- Full body HTML (cleaned, truncated) ---
            full_html = await page.evaluate("""() => {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('script, style, noscript, iframe').forEach(s => s.remove());
                // Remove all inline styles to save tokens
                clone.querySelectorAll('[style]').forEach(el => el.removeAttribute('style'));
                let html = clone.innerHTML;
                // Truncate to ~15k chars
                return html.substring(0, 15000);
            }""")

            # --- Extract images (no data URIs) ---
            images = await page.evaluate("""() => {
                const srcs = new Set();
                document.querySelectorAll('img').forEach(img => {
                    if (img.src && !img.src.startsWith('data:')) srcs.add(img.src);
                    if (img.dataset.src) srcs.add(img.dataset.src);
                });
                // Also grab background images from CSS
                document.querySelectorAll('*').forEach(el => {
                    const bg = getComputedStyle(el).backgroundImage;
                    if (bg && bg !== 'none') {
                        const match = bg.match(/url\\(['\"']?([^'\"\\)]+)['\"']?\\)/);
                        if (match && !match[1].startsWith('data:')) srcs.add(match[1]);
                    }
                });
                return Array.from(srcs).slice(0, 40);
            }""")

            # --- Extract background images separately ---
            bg_images = await page.evaluate("""() => {
                const bgs = new Set();
                document.querySelectorAll('*').forEach(el => {
                    const bg = getComputedStyle(el).backgroundImage;
                    if (bg && bg !== 'none') {
                        const match = bg.match(/url\\(['\"']?([^'\"\\)]+)['\"']?\\)/);
                        if (match && !match[1].startsWith('data:')) bgs.add(match[1]);
                    }
                });
                return Array.from(bgs).slice(0, 10);
            }""")

            # --- Extract computed styles, gradients, box-shadows, animations, hover states ---
            extracted_data = await page.evaluate("""() => {
                function colorToRgb(color) {
                    if (!color || color === 'rgba(0, 0, 0, 0)' || color === 'transparent' || color === 'none') return color;
                    const d = document.createElement('div');
                    d.style.display = 'none';
                    d.style.color = color;
                    document.body.appendChild(d);
                    const rgb = window.getComputedStyle(d).color;
                    document.body.removeChild(d);
                    return rgb;
                }

                const selectors = 'nav, header, section, footer, main, h1, h2, h3, h4, p, a, button, [class*="hero"], [class*="cta"], [class*="card"]';
                const elements = document.querySelectorAll(selectors);
                const result = [];
                const gradients = new Set();
                const boxShadows = new Set();
                const animations = [];
                
                let count = 0;
                for (const el of elements) {
                    if (count >= 40) break;
                    const s = window.getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden') continue;
                    const o = {};
                    
                    let bg = s.backgroundColor;
                    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') o.bg = colorToRgb(bg);
                    
                    let color = s.color;
                    if (color && color !== 'rgba(0, 0, 0, 0)') o.color = colorToRgb(color);
                    
                    if (s.fontSize) o.fs = s.fontSize;
                    if (s.fontWeight && s.fontWeight !== '400') o.fw = s.fontWeight;
                    if (s.fontFamily) o.ff = s.fontFamily.split(',')[0].replace(/['\"]/g, '').trim();
                    if (s.padding && s.padding !== '0px') o.p = s.padding;
                    if (s.margin && s.margin !== '0px') o.m = s.margin;
                    if (s.borderRadius && s.borderRadius !== '0px') o.br = s.borderRadius;
                    if (s.gap && s.gap !== 'normal') o.gap = s.gap;
                    if (s.display === 'flex' || s.display === 'grid') o.display = s.display;
                    if (s.flexDirection && s.display === 'flex') o.fd = s.flexDirection;
                    if (s.justifyContent && s.justifyContent !== 'normal') o.jc = s.justifyContent;
                    if (s.alignItems && s.alignItems !== 'normal') o.ai = s.alignItems;
                    
                    // typography
                    if (s.letterSpacing && s.letterSpacing !== 'normal') o.ls = s.letterSpacing;
                    if (s.lineHeight && s.lineHeight !== 'normal') o.lh = s.lineHeight;
                    if (s.textTransform && s.textTransform !== 'none') o.tt = s.textTransform;
                    
                    // gradients
                    if (s.backgroundImage && s.backgroundImage !== 'none') {
                        if (s.backgroundImage.includes('linear-gradient') || s.backgroundImage.includes('radial-gradient')) {
                            gradients.add(s.backgroundImage);
                        }
                    }
                    
                    // box-shadow
                    if (s.boxShadow && s.boxShadow !== 'none') {
                        boxShadows.add(s.boxShadow);
                    }
                    
                    // animations & transitions
                    let animObj = {};
                    let hasAnim = false;
                    if (s.animationName && s.animationName !== 'none') {
                        animObj.animationName = s.animationName;
                        animObj.animationDuration = s.animationDuration;
                        hasAnim = true;
                    }
                    if (s.transitionProperty && s.transitionProperty !== 'all' && s.transitionProperty !== 'none') {
                        animObj.transitionProperty = s.transitionProperty;
                        animObj.transitionDuration = s.transitionDuration;
                        animObj.transitionTimingFunction = s.transitionTimingFunction;
                        hasAnim = true;
                    }
                    if (hasAnim) {
                        animObj.selector = el.className ? '.' + el.className.split(' ').join('.') : el.tagName.toLowerCase();
                        animations.push(animObj);
                    }

                    if (Object.keys(o).length > 1) {
                        o.tag = el.tagName;
                        o.cls = el.className?.toString().substring(0, 80) || '';
                        result.push(o);
                        count++;
                    }
                }
                
                // hover states
                const hover_styles = [];
                try {
                    for (const sheet of document.styleSheets) {
                        try {
                            for (const rule of sheet.cssRules) {
                                if (rule.selectorText && rule.selectorText.includes(':hover')) {
                                    hover_styles.push({
                                        selector: rule.selectorText,
                                        cssText: rule.style.cssText
                                    });
                                }
                            }
                        } catch(e) {}
                    }
                } catch(e) {}

                return {
                    styles: result,
                    gradients: Array.from(gradients),
                    boxShadows: Array.from(boxShadows),
                    animations: animations,
                    hoverStyles: hover_styles.slice(0, 40)
                };
            }""")

            style_data = extracted_data.get("styles", [])
            gradients = extracted_data.get("gradients", [])
            box_shadows = extracted_data.get("boxShadows", [])
            animations = extracted_data.get("animations", [])
            hover_styles = extracted_data.get("hoverStyles", [])

            # --- Dominant colors ---
            color_counter = Counter()
            for s in style_data:
                bg = s.get("bg")
                color = s.get("color")
                if bg and bg != "rgba(0, 0, 0, 0)" and bg != "transparent":
                    color_counter[bg] += 2
                if color and color != "rgba(0, 0, 0, 0)" and color != "transparent":
                    color_counter[color] += 1
            top_colors = [c for c, _ in color_counter.most_common(8)]

            # --- Fonts ---
            font_counter = Counter()
            for s in style_data:
                ff = s.get("ff")
                if ff:
                    font_counter[ff] += 1
            top_fonts = [f for f, _ in font_counter.most_common(3)]

            await browser.close()

            return CaptureResult(
                url=url,
                sections=section_captures,
                full_html=full_html,
                images=list(set(images)),
                styles=style_data,
                colors=top_colors,
                fonts=top_fonts,
                background_images=bg_images,
                gradients=gradients,
                animations=animations,
                box_shadows=box_shadows,
                hover_styles=hover_styles,
            )

    except Exception as e:
        return CaptureResult(url=url, sections=[], full_html="", images=[], styles=[], colors=[], fonts=[], background_images=[], error=str(e))
