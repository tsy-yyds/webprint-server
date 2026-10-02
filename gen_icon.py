# -*- coding: utf-8 -*-
"""生成 PWA 应用图标 icon.png（512x512，蓝底白色打印机）"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'web', 'icon.png')
S = 512
BLUE = (37, 99, 235)
LIGHT = (219, 234, 254)

img = Image.new('RGB', (S, S), BLUE)
d = ImageDraw.Draw(img)

# 打印机机身
d.rounded_rectangle([120, 210, 392, 430], radius=24, fill='white')
# 顶部纸仓
d.rounded_rectangle([155, 120, 357, 220], radius=18, fill='white')
# 纸仓中的纸
d.rectangle([185, 145, 327, 160], fill=BLUE)
d.rectangle([185, 170, 327, 185], fill=BLUE)
# 出纸口（机身下方深色口）
d.rounded_rectangle([142, 356, 370, 400], radius=12, fill=LIGHT)
# 控制区
d.ellipse([205, 255, 241, 291], fill=BLUE)
d.rounded_rectangle([262, 265, 330, 281], radius=8, fill=BLUE)
# 底座
d.rounded_rectangle([100, 430, 412, 462], radius=14, fill='white')
# 信号弧线
d.arc([120, 60, 200, 140], start=200, end=340, fill='white', width=12)
d.arc([170, 10, 250, 90], start=200, end=340, fill='white', width=12)

img.save(OUT)
print('OK:', OUT)
