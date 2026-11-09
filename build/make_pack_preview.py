"""Render all release covers from actual ZDL bytes, at LCD pixel proportions."""
import json,math,sys
from pathlib import Path
from PIL import Image,ImageDraw
from decode_picture import decode_picture,read_image_info
from lcd_geometry import PIXEL_ASPECT
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'graphics/effect-cover-explorations/full-pack'
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 files=sorted((ROOT/'dist').glob('*.ZDL'));cols=4;cellw=272;cellh=219
 sheet=Image.new('RGB',(cols*cellw+16,math.ceil(len(files)/cols)*cellh+40),(22,26,31));d=ImageDraw.Draw(sheet)
 d.text((16,12),'22 effect covers | Native 128x64 artwork | Approximate LCD proportions | No simulated values',fill='white')
 html=['<!doctype html><meta charset="utf-8"><title>22 native effect covers</title><style>body{background:#161a1f;color:#b4e6ff;font:14px system-ui;padding:24px}main{display:flex;gap:20px;flex-wrap:wrap}section{width:256px}img{width:256px;height:179px;image-rendering:pixelated}h2{font-size:16px}p{max-width:850px}</style><h1>22 native effect covers</h1><p>Decoded directly from the release ZDLs. Each image contains 128×64 monochrome pixels, displayed at the approximate physical LCD proportions. No invented detail or simulated firmware values.</p><main>']
 rows=[]
 for i,p in enumerate(files):
  px,_=decode_picture(str(p));info=read_image_info(str(p));assert len(px)==64 and all(len(r)==128 for r in px)
  for _,x,y in info['knobs']:assert 0<=x<=108 and 0<=y<=49
  im=Image.new('RGB',(128,64));im.putdata([(180,230,255) if b else (16,18,24) for r in px for b in r])
  im.save(OUT/(p.stem+'.png'))
  x=16+(i%cols)*cellw;y=40+(i//cols)*cellh
  d.text((x,y),p.stem,fill='white');sheet.paste(im.resize((256,round(128*PIXEL_ASPECT)),Image.Resampling.NEAREST),(x,y+22))
  html.append(f'<section><h2>{p.stem}</h2><img src="{p.stem}.png" alt="{p.stem} native cover"></section>')
  rows.append({'name':p.stem,'bitmap':[128,64],'knobs':info['knobs']})
 sheet.save(OUT/'contact-sheet.png');html.append('</main>');(OUT/'index.html').write_text(''.join(html));(OUT/'geometry.json').write_text(json.dumps(rows,indent=2))
if __name__=='__main__':main()
