"""独立核对浏览器下载的像素编辑 PDF；不调用产品桥接或编辑算法。"""
import hashlib
import json
import sys
from pathlib import Path

import pymupdf
from pypdf import PdfReader


def inspect(path):
    content = Path(path).read_bytes()
    reader = PdfReader(path)
    images = []
    for entry in reader.pages[0].images:
        image = entry.image.convert("RGBA")
        width, height = image.size
        images.append({
            "size": [width, height],
            "samples": [list(image.getpixel((int(width * x), int(height * y))))
                        for x, y in ((.25, .25), (.75, .25), (.25, .75), (.75, .75))],
            "pixelsSha256": hashlib.sha256(image.tobytes()).hexdigest(),
        })
    with pymupdf.open(path) as document:
        page = document[0]
        placements = []
        for image in page.get_images():
            placements.extend({"size": [image[2], image[3]], "rect": list(rect)}
                              for rect in page.get_image_rects(image[0]))
        # 两种PDF重写器的浮点序列化有微小差异，保留0.001pt精度比较布局；文字与样式字段不变。
        def precision(value):
            if isinstance(value, float):
                return round(value, 3)
            if isinstance(value, dict):
                return {key: precision(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [precision(item) for item in value]
            return value
        text_blocks = precision([block for block in page.get_text("dict")["blocks"] if block["type"] == 0])
        return {"sha256": hashlib.sha256(content).hexdigest(), "pages": len(reader.pages),
                "text": reader.pages[0].extract_text(), "images": images,
                "placements": placements, "textBlocks": text_blocks,
                "pageRect": list(page.rect)}


def verify(source, output, mode):
    assert mode in ("flip-h", "flip-v", "crop", "opacity"), mode
    assert source["pages"] == output["pages"] == 1
    assert source["pageRect"] == output["pageRect"]
    assert source["text"] == output["text"] == "Image bake fixture\n"
    assert source["textBlocks"] == output["textBlocks"], "正文样式或位置变化"
    assert len(source["images"]) == len(output["images"]) == 2
    red, blue, yellow, purple = ([220, 30, 30, 255], [31, 79, 216, 255],
                                  [230, 180, 20, 255], [150, 40, 170, 255])
    original = next(image for image in source["images"] if image["size"] == [8, 8])
    assert original["samples"] == [red, blue, yellow, purple], "来源四象限不匹配"
    other = next(image for image in source["images"] if image["size"] == [2, 2])
    assert other == next(image for image in output["images"] if image["size"] == [2, 2]), "未编辑图像变化"
    size = [300, 450] if mode == "crop" else [600, 450]
    actual = next(image for image in output["images"] if image["size"] == size)
    expected = {"flip-h": [blue, red, purple, yellow], "flip-v": [yellow, purple, red, blue],
                "crop": [red, red, yellow, yellow],
                "opacity": [color[:3] + [153] for color in (red, blue, yellow, purple)]}[mode]
    for pixel, wanted in zip(actual["samples"], expected):
        assert all(abs(value - target) <= 12 for value, target in zip(pixel, wanted)), (mode, pixel, wanted)
    before = next(item for item in source["placements"] if item["size"] == [8, 8])["rect"]
    after = next(item for item in output["placements"] if item["size"] == size)["rect"]
    expected_rect = before.copy()
    if mode == "crop":
        expected_rect[2] = before[0] + (before[2] - before[0]) / 2
    assert all(abs(value - target) < .05 for value, target in zip(after, expected_rect)), (after, expected_rect)
    assert (next(item for item in source["placements"] if item["size"] == [2, 2]) ==
            next(item for item in output["placements"] if item["size"] == [2, 2])), "未编辑图像位置变化"


if __name__ == "__main__":
    source, output = inspect(sys.argv[1]), inspect(sys.argv[2])
    mode = sys.argv[3]
    verify(source, output, mode)
    rejected = []
    # 未应用操作的来源、另一种操作的结果均不能被当成本次保存成功。
    for label, candidate, expected_mode in (("unchanged-source", source, mode),
                                             ("wrong-operation", output, "flip-v" if mode != "flip-v" else "flip-h")):
        try:
            verify(source, candidate, expected_mode)
        except (AssertionError, StopIteration):
            rejected.append(label)
        else:
            raise AssertionError(f"独立核验未拒绝 {label}")
    print(json.dumps({"ok": True, "mode": mode, "source": source, "output": output,
                      "rejectedFaults": rejected}, ensure_ascii=False))
