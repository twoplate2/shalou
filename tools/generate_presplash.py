"""生成 presplash.png (1080x1920 启动屏) — 与 BG_COLOR 一致的纯色背景 + 居中小沙漏"""
from PIL import Image, ImageDraw

W, H = 1080, 1920
BG = (253, 246, 227, 255)
GLASS = (234, 243, 248, 255)
SAND = (217, 163, 96, 255)
WOOD = (139, 111, 71, 255)
WOOD_OUT = (90, 74, 48, 255)
GLASS_OUT = (102, 102, 102, 255)


def main():
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img)

    cx = W // 2
    cy = H // 2
    half_h = 380
    top_y = cy - half_h
    bot_y = cy + half_h
    neck_y = cy
    top_w = 230
    neck_w = 18

    glass = [
        (cx - top_w, top_y), (cx + top_w, top_y),
        (cx + neck_w, neck_y),
        (cx + top_w, bot_y), (cx - top_w, bot_y),
        (cx - neck_w, neck_y),
    ]
    d.polygon(glass, fill=GLASS, outline=GLASS_OUT)

    # 上半满沙
    d.polygon([
        (cx - top_w, top_y), (cx + top_w, top_y),
        (cx + neck_w, neck_y), (cx - neck_w, neck_y),
    ], fill=SAND)

    # 木盖
    cap_h = 44
    cap_w = top_w + 40
    d.rectangle((cx - cap_w, top_y - cap_h, cx + cap_w, top_y),
                fill=WOOD, outline=WOOD_OUT, width=3)
    d.rectangle((cx - cap_w, bot_y, cx + cap_w, bot_y + cap_h),
                fill=WOOD, outline=WOOD_OUT, width=3)

    img.save("presplash.png", optimize=True)
    print("presplash.png", img.size)


if __name__ == "__main__":
    main()
