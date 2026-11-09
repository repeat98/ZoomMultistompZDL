"""Small, intentional laboratory marks for the native cover artwork.

No random distress: annotations stay outside control labels/live value boxes.
"""
import math
from lcd_geometry import PIXEL_ASPECT
from screen_image import Canvas

GLYPHS={
 'Ф':['01110','10101','11111','10101','01110'],
 'Л':['0011','0101','0101','1001','1001'],
 'П':['111','101','101','101','101'],
 'О':['010','101','101','101','010'],
 'И':['1001','1001','1011','1101','1001'],
 'Δ':['00100','01010','01010','10001','11111'],
 '?':['110','001','010','000','010'],
}
def glyph(c,ch,x,y,v=1):
 for dy,row in enumerate((GLYPHS[ch] if ch in GLYPHS else Canvas._FONT[ch])):
  for dx,b in enumerate(row):
   if b=='1':c.px(x+dx,y+dy,v)
def line(c,a,b,v=1):
 x,y=a;X,Y=b;n=max(abs(X-x),abs(Y-y))
 for i in range(n+1):c.px(round(x+(X-x)*i/max(n,1)),round(y+(Y-y)*i/max(n,1)),v)
def screw(c,x,y):
 c.rect(x-1,y-1,x+1,y+1);line(c,(x-1,y+1),(x+1,y-1),0)
def jack(c,x,y):
 c.rect(x-2,y-2,x+2,y+2);c.px(x,y)
def ticks(c,x0,x1,y):
 c.hline(x0,x1,y)
 for x in range(x0,x1+1,4):c.vline(x,y-(2 if (x-x0)%12==0 else 1),y)
def atom(c,x,y):
 for phase in (0,math.pi/3,-math.pi/3):
  last=None
  for i in range(41):
   t=i*math.pi/20;u=8*math.cos(t);v=3*math.sin(t)
   p=(x+round(u*math.cos(phase)-v*math.sin(phase)),y+round((u*math.sin(phase)+v*math.cos(phase))/PIXEL_ASPECT))
   if last:line(c,last,p)
   last=p
 c.px(x,y)
def apply(c,name):
 if name=='Stasis':
  # A phase-memory annotation beside the frozen waveform.
  glyph(c,'Ф',79,53,0);glyph(c,'?',86,53,0)
  for x in (7,120):screw(c,x,32)
  return c
 if name=='Spool':
  # Recorder channel stamp, leader marks and one loose cable.
  glyph(c,'Л',44,28,0);glyph(c,'2',50,28,0)
  line(c,(112,31),(115,34));line(c,(115,34),(123,34));jack(c,123,30)
  for x in (12,115):screw(c,x,4)
  return c
 if name=='Rooms':
  glyph(c,'Ф',60,4);glyph(c,'?',67,4)
  for x in (7,120):screw(c,x,32)
  return c
 # Individually placed annotations, rather than a shared decoration strip.
 if name=='Arrakis':
  ticks(c,7,43,32);glyph(c,'Δ',114,5);glyph(c,'?',119,25)
 elif name=='Corrupt':
  jack(c,119,7);line(c,(115,7),(110,12));glyph(c,'?',107,28)
  c.rect(4,28,13,33);glyph(c,'П',7,29)
 elif name=='Dissolve':
  glyph(c,'Ф',8,27);glyph(c,'?',16,27)
  for x in range(26,104):c.px(x,round(29+3*math.sin(x*.5)*((104-x)/78)))
 elif name=='Dustbox':
  for x in (8,119):screw(c,x,5);screw(c,x,30)
  glyph(c,'Л',93,25);c.draw_text('7',99,25);jack(c,16,27)
 elif name=='Flower':
  glyph(c,'О',113,3);glyph(c,'П',118,3);ticks(c,51,91,32)
 elif name=='Galactic':
  atom(c,111,26);glyph(c,'Л',5,16);c.draw_text('3',10,16)
 elif name=='GenLoss':
  # A broken reel flange and a row of transport marks.
  c.hline(104,110,13,0);c.vline(83,26,29);c.vline(86,26,29)
  glyph(c,'?',112,7);screw(c,6,30)
 elif name=='Gyre':
  glyph(c,'Ф',9,15);glyph(c,'?',16,15);ticks(c,46,82,33)
 elif name=='Howl':
  for deg in range(0,360,40):
   a=math.radians(deg);c.px(25+round(21*math.cos(a)),18+round(15*math.sin(a)))
  glyph(c,'Δ',114,27);glyph(c,'?',119,27)
 elif name=='Hydra':
  for x,n in [(21,'1'),(61,'2'),(101,'3')]:c.draw_text(n,x,8)
  jack(c,63,31);glyph(c,'?',110,18)
 elif name=='Klang':
  glyph(c,'Ф',21,15);ticks(c,59,111,32);screw(c,121,8)
 elif name=='Mangle':
  glyph(c,'Δ',9,14,0);glyph(c,'?',115,14,0)
  # A missing tooth in the mechanical frame.
  c.hline(81,88,31,0);c.hline(82,87,30,0)
 elif name=='Microlm':
  glyph(c,'Л',113,7,0);glyph(c,'?',115,22,0)
  c.hline(12,20,18,0);ticks(c,54,106,33)
 elif name=='Oxide':
  glyph(c,'Ф',19,13,0);glyph(c,'?',101,14,0)
  for x in (7,120):screw(c,x,3)
 elif name=='Tonic':
  glyph(c,'?',117,19);screw(c,5,4);screw(c,122,31)
 elif name=='Rewire':
  jack(c,122,28);glyph(c,'?',91,12)
  line(c,(110,6),(116,3));line(c,(116,3),(122,3))
  c.hline(76,78,29,0)
 elif name=='Scorch':
  glyph(c,'Δ',106,27);c.draw_text('!',115,27);ticks(c,48,87,32)
 elif name=='Shatter':
  glyph(c,'?',115,25);jack(c,8,31);c.hline(14,28,31)
 elif name=='Spiral':
  glyph(c,'Ф',51,28);ticks(c,64,116,33)
 elif name=='Taffy':
  glyph(c,'И',10,14);glyph(c,'?',113,14);ticks(c,42,86,33)
 # Several panels use the main console's ivory field instead of all-dark art.
 if name in {'Arrakis','Galactic','Howl','Hydra','Rewire','Scorch','Gyre','Tonic'}:
  for y in range(1,35):
   for x in range(1,127):c.px(x,y,1-c.pixels[y][x])
  # Small mounting slots anchor the illustrated panel to the instrument face.
  for x in (3,124):c.px(x,2,0);c.px(x,33,0)
 return c
