"""Individual 128x64 cover designs, authored for the physical LCD aspect."""
import math
from screen_image import Canvas
from stock_style_covers import fill,line,round_shape
from lcd_geometry import PIXEL_ASPECT
NAMES={'Oxide','Galactic','Flower','Shatter','Arrakis','Microlm','Corrupt','Klang','GenLoss','Scorch','Howl','Taffy','Dissolve','Mangle','Hydra','Rewire','Dustbox','Spiral','Gyre','Tonic'}

def word(c,text,x,y,sx=2,sy=2,v=1,lean=0):
    # Compact stock-style block lettering; all marks stay on the pixel grid.
    for ch in text.upper():
        for yy,row in enumerate(Canvas._FONT[ch]):
            for xx,bit in enumerate(row):
                if bit=='1':
                    dx=(4-yy)*lean//4
                    fill(c,x+xx*sx+dx,y+yy*sy,x+(xx+1)*sx-1+dx,y+(yy+1)*sy-1,v)
        x+=3*sx+1

def wave(c,x0,x1,y,amp,period=18):
    last=None
    for x in range(x0,x1+1):
        p=(x,round(y+amp*math.sin((x-x0)*2*math.pi/period)))
        if last:line(c,last,p)
        last=p

def spark(c,x,y,r=2):
    c.hline(x-r,x+r,y);c.vline(x,y-max(1,round(r/PIXEL_ASPECT)),y+max(1,round(r/PIXEL_ASPECT)))

def draw(name,labels):
    from custom_covers import knob_layout
    c=Canvas()
    # Control coordinates remain byte-for-byte compatible with existing ZDLs.
    c.hline(3,124,63)
    for (_,x,y),label in zip(knob_layout(min(3,len(labels))),labels[:3]):
        c.draw_text(label.upper(),x+10-(len(label)*4-1)//2,37)
        round_shape(c,x+10,y+7,7);round_shape(c,x+10,y+7,5,0);c.vline(x+10,y+3,y+7)
    if name=='Tonic':
        c.rect(3,2,124,33)
        # Laboratory vessel, bubbling signal and reversible process arrows.
        for a,b in [((15,5),(25,5)),((17,5),(17,13)),((23,5),(23,13)),
                    ((17,13),(9,28)),((23,13),(31,28)),((9,28),(31,28))]:line(c,a,b)
        wave(c,12,28,23,2,12)
        round_shape(c,20,18,2,filled=False);c.px(22,10)
        word(c,'TONIC',43,9,sx=4,sy=3)
        c.hline(43,115,28);line(c,(109,25),(115,28));line(c,(109,31),(115,28))
        c.hline(43,115,5);line(c,(43,5),(49,3));line(c,(43,5),(49,7))
    elif name=='Flower':
        for a in range(0,360,60):
            r=math.radians(a);round_shape(c,23+round(12*math.cos(r)),17+round(9*math.sin(r)),8,filled=False)
        round_shape(c,23,17,4)
        word(c,'FLOWER',46,11,sx=3,sy=3);c.hline(47,123,28)
    elif name=='Galactic':
        for x,y,r in [(8,8,3),(113,24,4),(97,5,2),(20,29,2),(64,30,1),(121,8,1)]:spark(c,x,y,r)
        word(c,'GALACTIC',24,13,lean=2)
        line(c,(4,26),(117,2));line(c,(8,29),(120,5))
        # Redraw a clear title window over the orbit.
        fill(c,23,12,106,24,0);word(c,'GALACTIC',24,13,sx=3,sy=2,lean=2)
    elif name=='Shatter':
        c.rect(4,3,123,32)
        for i,ch in enumerate('SHATTER'):word(c,ch,14+i*15,10+(i%3-1)*2,sx=4,sy=3)
        for a,b in [((3,27),(37,3)),((39,32),(62,4)),((94,31),(111,5))]:line(c,a,b,0);line(c,(a[0]+1,a[1]),(b[0]+1,b[1]),0)
    elif name=='Arrakis':
        round_shape(c,102,9,9,filled=False)
        word(c,'ARRAKIS',14,4,sx=3,sy=3)
        for yy in (23,29):
            for x in range(3,125):c.px(x,round(yy+3*math.sin(x*.055)))
        for x in range(6,122,5):c.px(x,33)
    elif name=='Microlm':
        for x in range(3,36,4):line(c,(x,3),(x+9,33))
        for y in range(3,34,4):c.hline(3,41,y)
        fill(c,44,5,123,29);word(c,'MICRO',49,7,v=0);word(c,'LOOM',67,19,v=0)
    elif name=='Corrupt':
        word(c,'CORRUPT',8,7,sx=4,sy=3)
        for x,y,w in [(2,9,9),(100,24,24),(18,27,31),(75,3,36)]:fill(c,x,y,x+w,y+2)
        for y in (12,19):
            row=c.pixels[y][:];c.pixels[y]=[0]*128
            for x in range(125):c.px(x+3,y,row[x])
        c.hline(7,117,32)
    elif name=='Klang':
        round_shape(c,21,17,18,filled=False);round_shape(c,34,17,18,filled=False)
        fill(c,49,6,124,29);word(c,'KLANG',54,11,sx=4,sy=3,v=0)
    elif name=='GenLoss':
        c.rect(3,2,124,33);word(c,'GEN',9,6,sx=3,sy=2);word(c,'LOSS',9,19,sx=3,sy=2)
        c.rect(58,5,119,29);c.rect(62,9,115,24)
        for x in (75,102):round_shape(c,x,17,7,filled=False);spark(c,x,17,3)
        for x in range(60,119,3):c.px(x,31)
    elif name=='Scorch':
        for yy,x0,x1 in [(3,17,34),(4,16,33),(5,15,32),(6,14,31),(7,13,30),(8,12,29),(9,11,28),(10,10,27),(11,9,26),(12,8,25),(13,7,34),(14,6,33),(15,5,32)]:c.hline(x0,x1,yy)
        line(c,(34,13),(13,33));line(c,(13,33),(20,15))
        word(c,'SCORCH',42,10,sx=3,sy=3,lean=3)
    elif name=='Howl':
        for r in (18,13,7):round_shape(c,25,18,r,filled=False)
        word(c,'HOWL',57,9,sx=5,sy=4)
        for y in (4,31):c.hline(54,119,y)
    elif name=='Taffy':
        for a,b in [((6,3),(22,9)),((6,31),(22,25)),((122,3),(106,9)),((122,31),(106,25))]:line(c,a,b)
        c.rect(22,6,106,29);word(c,'TAFFY',29,11,sx=4,sy=3)
        line(c,(6,3),(6,31));line(c,(122,3),(122,31))
    elif name=='Dissolve':
        word(c,'DISSOLVE',7,8,sx=3,sy=3)
        for y in range(4,33):
            for x in range(51,125):
                if (x*17+y*11)%83 < (x-51)*.45:c.px(x,y,0)
        for x in range(18,125,5):c.px(x,29+(x%3))
    elif name=='Mangle':
        fill(c,4,3,123,32)
        for x in range(5,122,10):
            for dy in range(5):c.hline(x+dy,x+8-dy,3+dy,0);c.hline(x+dy,x+8-dy,32-dy,0)
        word(c,'MANGLE',25,11,sx=3,sy=3,v=0)
    elif name=='Hydra':
        for x in (23,63,103):
            line(c,(63,31),(x,11));line(c,(x,11),(x,5));c.rect(x-5,2,x+5,6)
        fill(c,27,15,98,29,0);word(c,'HYDRA',33,17,sx=4,sy=2)
    elif name=='Rewire':
        word(c,'RE',6,5,sx=4,sy=2);word(c,'WIRE',6,20,sx=4,sy=2)
        for i in range(4):
            x=65+i*15;y=6+(i%2)*17;c.rect(x,y,x+9,y+7)
            line(c,(x+4,y+7),(x+4,32-i*3));line(c,(x+4,32-i*3),(117-i*10,32-i*3))
        c.vline(124,2,33)
    elif name=='Dustbox':
        c.rect(5,2,122,33);c.rect(8,4,119,31)
        for x in range(10,119):
            for y in range(6,30):
                if (x*31+y*17)%79==0:c.px(x,y)
        fill(c,14,10,114,23,0);word(c,'DUSTBOX',17,12,sx=3,sy=2)
    elif name=='Spiral':
        prev=None
        for i in range(160):
            a=i*.13;r=1+i*.115;p=(25+round(r*math.cos(a)),18+round(r*math.sin(a)/PIXEL_ASPECT))
            if prev:line(c,prev,p)
            prev=p
        word(c,'SPIRAL',48,11,sx=3,sy=3)
    elif name=='Gyre':
        for y in (5,29):wave(c,5,121,y,3,40)
        word(c,'GYRE',31,10,sx=5,sy=3,lean=2)
        line(c,(115,2),(123,5));line(c,(123,5),(115,9))
    elif name=='Oxide':
        c.rect(4,2,123,33);fill(c,7,5,120,30)
        word(c,'OXIDE',29,11,sx=4,sy=3,v=0)
        for x in (13,114):
            for y in range(7,29,6):fill(c,x-2,y,x+2,y+2,0)
    else:raise ValueError(name)
    from lab_details import apply
    return apply(c,name)
