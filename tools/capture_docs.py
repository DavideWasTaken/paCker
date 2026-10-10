"""Capture real viewer screenshots from stored, independently validated layouts."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python'))
from packer_adapter.validation import validate


def capture(url,output):
    from playwright.sync_api import sync_playwright
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    layouts={name:ROOT/'examples'/filename for name,filename in (
        ('mixed','viewer-mixed-layout.json'),('free3d','viewer-free3d-layout.json'))}
    for path in layouts.values():
        document=json.loads(path.read_text(encoding='utf-8'))
        errors=validate(document['request'],document['result'])
        if errors:
            raise ValueError(f'{path}: {errors}')
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(args=['--use-gl=angle','--use-angle=swiftshader'])
        try:
            page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
            page.goto(url)
            page.wait_for_function("document.querySelector('#message').textContent.includes('Layout ready.')")

            def load(name):
                page.locator('#file').set_input_files(str(layouts[name]))
                page.wait_for_function("document.querySelector('#association').textContent.startsWith('VERIFIED')")
                page.locator('#data-panel').evaluate('el => el.open=false')
                page.wait_for_timeout(350)  # Allow OrbitControls damping to settle.

            load('mixed')
            page.screenshot(path=str(output/'overview.png'))
            page.locator('.box-card').first.click()
            bounds=page.locator('#canvas').bounding_box()
            x=bounds['x']+bounds['width']*.55;y=bounds['y']+bounds['height']*.5
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+60,y+10,steps=8);page.mouse.up()
            page.wait_for_timeout(650)
            page.screenshot(path=str(output/'box-rotated.png'))
            page.locator('#faithful').uncheck()
            page.locator('#explode').evaluate("el => {el.value='65';el.dispatchEvent(new Event('input',{bubbles:true}));}")
            page.wait_for_timeout(350)
            page.screenshot(path=str(output/'box-exploded.png'))
            load('free3d')
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+55,y,steps=8);page.mouse.up()
            page.wait_for_timeout(650)
            page.screenshot(path=str(output/'free3d.png'))
        finally:
            browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8765')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'docs/images')
    args=parser.parse_args()
    capture(args.url,args.output_dir)
