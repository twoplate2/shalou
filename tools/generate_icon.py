"""生成 icon.png (1024x1024 启动器图标) — 米黄圆角方形 + 居中沙漏剪影"""
from PIL import Image, ImageDraw

W = 1024
PADDING = 60
CORNER = 180

BG = (253, 246, 227, 255)        # #fdf6e3
GLASS = (234, 243, 248, 255)     # #eaf3f8
SAND = (217, 163, 96, 255)       # #d9a360
SAND_DARK = (184, 128, 64, 255)  # #b88040
WOOD = (139, 111, 71, 255)       # #8b6f47
WOOD_OUT = (90, 74, 48, 255)
GLASS_OUT = (102, 102, 102, 255)


def round_rect_mask(size, radius):
    img = Image.new("L", size, 0)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return img


def main():
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bg = Image.new("RGBA", (W, W), BG)
    img.paste(bg, mask=round_rect_mask((W, W), CORNER))

    d = ImageDraw.Draw(img)
    cx = W // 2
    top_y = PADDING + 80
    bot_y = W - PADDING - 80
    neck_y = (top_y + bot_y) // 2
    top_w = 290
    neck_w = 22

    # 玻璃
    glass = [
        (cx - top_w, top_y), (cx + top_w, top_y),
        (cx + neck_w, neck_y),
        (cx + top_w, bot_y), (cx - top_w, bot_y),
        (cx - neck_w, neck_y),
    ]
    d.polygon(glass, fill=GLASS, outline=GLASS_OUT)

    # 上半沙(满到 70%)
    fill_top = top_y + int((neck_y - top_y) * 0.30)
    t = (fill_top - top_y) / max(1, neck_y - top_y)
    w_top = int(top_w * (1 - t) + neck_w * t)
    d.polygon([
        (cx - w_top, fill_top), (cx + w_top, fill_top),
        (cx + neck_w, neck_y), (cx - neck_w, neck_y),
    ], fill=SAND)

    # 下半沙堆(填到 30%)
    fill_bot = bot_y - int((bot_y - neck_y) * 0.30 * 0.75)
    tt = (bot_y - fill_bot) / max(1, bot_y - neck_y)
    w_bot = int(top_w * (1 - tt) + neck_w * tt)
    d.polygon([
        (cx - top_w, bot_y), (cx + top_w, bot_y),
        (cx + w_bot, fill_bot), (cx - w_bot, fill_bot),
    ], fill=SAND)

    # 颈部一束沙流
    stream_h = neck_y + 60
    d.polygon([
        (cx - 6, neck_y), (cx + 6, neck_y),
        (cx + 4, stream_h), (cx - 4, stream_h),
    ], fill=SAND_DARK)

    # 木盖
    cap_h = 56
    cap_w = top_w + 50
    d.rectangle((cx - cap_w, top_y - cap_h, cx + cap_w, top_y), fill=WOOD, outline=WOOD_OUT, width=3)
    d.rectangle((cx - cap_w, bot_y, cx + cap_w, bot_y + cap_h), fill=WOOD, outline=WOOD_OUT, width=3)

    img.save("icon.png", optimize=True)
    print("icon.png", img.size)


if __name__ == "__main__":
    main()
