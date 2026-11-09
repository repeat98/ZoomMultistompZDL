import sys,json,base64
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,'build')
from decode_picture import decode_picture,read_image_info
from screen_image import Canvas
out=Path('graphics/effect-cover-explorations/stock-style')
names=['Stasis','Spool','Rooms']; bg=(16,18,24);fg=(180,230,255)
sheet=Image.new('RGB',(832,360),(31,35,40));d=ImageDraw.Draw(sheet)
d.text((16,10),'PE cover pixels — LCD proportions (approx. 1.4 pixel aspect), nearest-neighbor',fill='white')
html=['<meta charset="utf-8"><title>Native cover comparison</title><style>body{background:#202328;color:#eee;font:16px system-ui;padding:24px}main{display:flex;gap:24px}canvas{image-rendering:pixelated;width:256px;height:179px;border:3px solid #b4e6ff}img{image-rendering:pixelated}p{max-width:800px}</style><h1>Stock-style pilot — actual 128 × 64 pixels</h1><p>Top: the same drawCover function used by Patch Editor, at LCD proportions. Below: raw 1× bitmap (not physical LCD proportions). These are cover pixels only; firmware draws live values on the pedal.</p><main>']
for i,n in enumerate(names):
 px,_=decode_picture('dist/'+n+'.ZDL');info=read_image_info('dist/'+n+'.ZDL')
 assert len(px)==64 and all(len(r)==128 for r in px)
 im=Image.new('RGB',(128,64));im.putdata([fg if v else bg for r in px for v in r]);im.save(out/(n.lower()+'-native.png'))
 x=16+i*272;d.text((x,36),n,fill='white');sheet.paste(im.resize((256,179),Image.Resampling.NEAREST),(x,55))
 sheet.paste(im,(x,280))
 raw=bytes(sum(px[y][xb*8+b]<<(7-b) for b in range(8)) for y in range(64) for xb in range(16))
 html.append(f'<section><h2>{n}</h2><canvas width="128" height="64" data-bits="{base64.b64encode(raw).decode()}"></canvas><p>Native pixels</p><img src="{n.lower()}-native.png"></section>')
d.text((16,253),'Native bitmap — 1x (physical LCD size depends on the display)',fill='white')
sheet.save(out/'comparison.png')
src=Path('tools/patch_editor.html').read_text();start=src.index('function drawCover(');end=src.index('\n}',start)+2
html.append('</main><script>function tok(k,f){return f}\n'+src[start:end]+'\ndocument.querySelectorAll("canvas").forEach(c=>drawCover(c,c.dataset.bits));</script>')
(out/'index.html').write_text(''.join(html))
