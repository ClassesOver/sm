"""用真实分享组件验证长链接、有效期和按钮在弹窗内完整显示。"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="http://127.0.0.1:5176/reports/v1/editor/assets/")
    parser.add_argument("--output", type=Path, default=Path("/tmp/report-share-layout"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as api:
        executable = Path(api.chromium.executable_path)
        if not executable.exists():
            executable = next((Path.home() / ".cache/ms-playwright").glob("chromium-*/chrome-linux/chrome"))
        browser = await api.chromium.launch(executable_path=str(executable), headless=True)
        try:
            for width in (546, 375, 320):
                page = await browser.new_page(viewport={"width": width, "height": 700}, locale="zh-CN",
                                              reduced_motion="reduce")
                await page.route(args.frontend, lambda route: route.fulfill(
                    content_type="text/html", body='<html><head><meta charset="utf-8"></head><body></body></html>'))
                await page.goto(args.frontend)
                await page.evaluate("""async base => {
                    await import(base+'src/style.css');
                    const {createSharePanel}=await import(base+'src/share.ts');
                    Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{}}});
                    const url='http://air.dingyi-china.cn:33046/reports/v1/editor/open/'+ 'a'.repeat(100);
                    window.sharePanel=createSharePanel(document.body,async()=>({openUrl:url,expiresAt:'2026-11-22T07:34:18Z'}));
                    window.sharePanel.open();
                }""", args.frontend)
                await page.locator('[data-share="create"]').click()
                await page.wait_for_function("document.querySelector('[data-share=copy]').disabled === false && document.querySelector('[data-share=url]').value.length > 0")
                await page.evaluate("window.sharePanel.close(); window.sharePanel.open(); document.activeElement.blur()")
                await page.screenshot(path=str(args.output / f"share-{width}.png"), full_page=True)
                bounds = await page.evaluate("""() => {
                    const box=document.querySelector('.panel-body');
                    const style=getComputedStyle(box), rect=box.getBoundingClientRect();
                    const right=rect.right-parseFloat(style.paddingRight)-parseFloat(style.borderRightWidth);
                    return {right, children:[...box.querySelectorAll('.share-link-row, [data-share=copy], .share-link-footer, [data-share=create]')].map(x=>({className:x.className,right:x.getBoundingClientRect().right})),
                        expiry:document.querySelector('[data-share=expires]').getBoundingClientRect().toJSON(),
                        note:document.querySelector('[data-share=renew-note]').getBoundingClientRect().toJSON(),
                        viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth};
                }""")
                assert all(child["right"] <= bounds["right"] + 1 for child in bounds["children"]), bounds
                assert bounds["scrollWidth"] <= bounds["viewport"], bounds
                assert bounds["note"]["top"] >= bounds["expiry"]["bottom"] - 1, bounds
                print(f"分享弹窗 {width}px：链接和按钮均在容器内，无横向溢出")
                await page.close()
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
