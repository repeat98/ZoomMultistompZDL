"""Native-pixel covers for the first three approved designs. Layout coordinates also drive firmware overlays."""
from screen_image import Canvas
from lcd_geometry import PIXEL_ASPECT

def round_shape(c,x,y,r,v=1,filled=True):
    # Choose odd pixel diameters that are circular after the LCD stretches Y.
    ry=max(1,round(((2*r+1)/PIXEL_ASPECT-1)/2))
    for dy in range(-ry,ry+1):
        for dx in range(-r,r+1):
            q=(dx/(r+.45))**2+(dy/(ry+.45))**2
            inner=(dx/max(.5,r-1))**2+(dy/max(.5,ry-1))**2
            if q<=1 and (filled or inner>=1):c.px(x+dx,y+dy,v)

POSITIONS = {
    'Stasis': [(2,14,11),(3,55,11),(4,96,11)],
    'Spool': [(2,14,46),(3,55,46),(4,96,46)],
    'Rooms': [(2,14,46),(3,55,46),(4,96,46)],
}
FONT = {
'S':['01111','10000','10000','01110','00001','00001','11110'],
'T':['11111','00100','00100','00100','00100','00100','00100'],
'A':['01110','10001','10001','11111','10001','10001','10001'],
'I':['111','010','010','010','010','010','111'],
'P':['11110','10001','10001','11110','10000','10000','10000'],
'O':['01110','10001','10001','10001','10001','10001','01110'],
'L':['10000','10000','10000','10000','10000','10000','11111'],
'R':['11110','10001','10001','11110','10100','10010','10001'],
'M':['10001','11011','10101','10101','10001','10001','10001'],
}
def fill(c,x0,y0,x1,y1,v=1):
    for y in range(y0,y1+1): c.hline(x0,x1,y,v)
def line(c,a,b,v=1):
    x,y=a; X,Y=b; n=max(abs(X-x),abs(Y-y))
    for i in range(n+1): c.px(round(x+(X-x)*i/max(1,n)),round(y+(Y-y)*i/max(1,n)),v)
def title(c,s,x,y,sx=2,sy=2,v=1,slant=0):
    for ch in s:
        rows=FONT[ch]
        for j,row in enumerate(rows):
            for i,b in enumerate(row):
                if b=='1': fill(c,x+i*sx+(6-j)*slant//6,y+j*sy,x+(i+1)*sx-1+(6-j)*slant//6,y+(j+1)*sy-1,v)
        x+=(len(rows[0])+1)*sx

def controls(c,name,labels):
    for (_,x,y),label in zip(POSITIONS[name],labels):
        c.draw_text(label.upper(),x+10-(len(label)*4-1)//2,y-7)
        round_shape(c,x+10,y+7,7)
        round_shape(c,x+10,y+7,5,0)
        c.vline(x+10,y+3,y+7)

def draw(name,labels):
    c=Canvas()
    if name=='Stasis':
        c.rect(3,1,124,27); c.rect(4,2,123,26)
        controls(c,name,labels)
        fill(c,3,30,124,62)
        # A frozen, angular wave becomes the baseline of the title.
        title(c,'STASIS',18,34,v=0)
        for a,b in [((8,55),(25,55)),((25,55),(29,51)),((29,51),(34,59)),((34,59),(39,55)),((39,55),(88,55))]: line(c,a,b,0)
        fill(c,96,52,99,59,0); fill(c,104,52,107,59,0)
        line(c,(113,51),(119,55),0); line(c,(119,55),(113,59),0)
    elif name=='Spool':
        # A compact reel deck, rather than the pack's common title strip.
        c.rect(8,1,119,62); c.rect(9,2,118,61)
        fill(c,11,4,116,34)
        for cx in (29,98):
            round_shape(c,cx,18,12,0); round_shape(c,cx,18,10,filled=False)
            round_shape(c,cx,18,3)
            for dx,dy in [(0,-7),(-6,4),(6,4)]: round_shape(c,cx+dx,18+round(dy/PIXEL_ASPECT),2)
        title(c,'SPOOL',43,8,sx=1,sy=2,v=0)
        line(c,(30,30),(47,30),0); line(c,(47,30),(52,26),0)
        line(c,(52,26),(75,26),0); line(c,(75,26),(80,30),0);line(c,(80,30),(98,30),0)
        controls(c,name,labels)
    elif name=='Rooms':
        # Architectural lettering suspended within a deep room.
        c.rect(1,1,126,62)
        c.rect(5,3,122,34)
        c.rect(17,8,110,29)
        for a,b in [((5,3),(17,8)),((122,3),(110,8)),((5,34),(17,29)),((122,34),(110,29))]: line(c,a,b)
        title(c,'ROOMS',22,11,sx=3,sy=2)
        for x in (30,52,75,97): line(c,(x,30),(x-8,34))
        controls(c,name,labels)
    from lab_details import apply
    return apply(c,name)
