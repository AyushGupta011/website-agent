import asyncio
from agents.router import ModelRouter, TaskType
from agents.analyze import DesignSpec, SectionSpec
import agents.generate as gen

async def test():
    router = ModelRouter()
    spec = DesignSpec(
        theme=type('Theme', (), {'primary_color': 'blue', 'secondary_color': 'white', 'background_color': 'white', 'text_color': 'black', 'font_family': 'Arial', 'border_radius': '8px'}),
        navigation=type('Nav', (), {'logo_text': 'Logo', 'links': [], 'sticky': False, 'ui_details': None}),
        sections=[]
    )
    section = SectionSpec(
        id='hero', type='hero',
        headline='Test Headline', subheadline='Sub', body='Body', items=[], image_urls=[], ui_details='Make it cool', html_reference=''
    )
    from pathlib import Path
    Path('generated/test').mkdir(parents=True, exist_ok=True)
    (Path('generated/test') / 'src' / 'components').mkdir(parents=True, exist_ok=True)
    
    comp = await gen.generate_section(section, spec, router, Path('generated/test'))
    print("Component:", comp)
    
    with open('generated/test/src/components/Hero.tsx', 'r') as f:
        print("Generated Code:\n", f.read())

if __name__ == '__main__':
    asyncio.run(test())
