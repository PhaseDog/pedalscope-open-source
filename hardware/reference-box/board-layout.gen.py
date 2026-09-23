W,H = 1540,2140
INK="#1a1a1a"; SIG="#1f6b3f"; GRY="#6f6f6f"; PWR="#8a2f22"; ORG="#b06a20"; BLU="#22488a"
BG="#fdfcf9"; BOARD="#f4f1e5"; RP="#f7e0da"; RN="#dce3f5"; RG="#e8e8e8"; CHAN="#eae7d9"
NC,NP = 30,18
p=[]
def add(s): p.append(s)
def txt(x,y,s,sz=12,a="middle",f=INK,st="normal",w="normal"):
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="Helvetica,Arial,sans-serif" font-size="{sz}" '
        f'text-anchor="{a}" fill="{f}" font-style="{st}" font-weight="{w}">{s}</text>')
def wire(pts,c=INK,w=1.8,d=None):
    dd=" ".join(f"{'M' if i==0 else 'L'} {x:.1f} {y:.1f}" for i,(x,y) in enumerate(pts))
    da=f' stroke-dasharray="{d}"' if d else ""
    add(f'<path d="{dd}" stroke="{c}" stroke-width="{w}" fill="none" stroke-linecap="round"{da}/>')
add(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
txt(W/2,36,"Reference Box — SB404 board layout  (v4 — SOCKET PIN MAP CORRECTED)",19,w="bold")
txt(W/2,58,"v3's DIP pin map was MIRRORED about the long axis (caught before build). v4: notch faces the OUT edge; pin 1 = col 18 (TL072) / col 27 (LM358), BOTTOM bank.",11,f=PWR,w="bold")
txt(W/2,76,"Board mounted COMPONENT SIDE UP (facing the enclosure's top face). Pedal convention: IN on the RIGHT, OUT on the LEFT, viewed from above.",11,f=GRY)

def draw_board(ox,oy,pt,flip,detail):
    def px(c): return ox+16+((NC-c) if flip else (c-1))*pt
    def py(r): return oy+16+r*pt
    BWl = 16+(NC-1)*pt+16; BHl = 16+(NP-1)*pt+16
    add(f'<rect x="{ox}" y="{oy}" width="{BWl}" height="{BHl}" rx="6" fill="{BOARD}" stroke="{GRY}" stroke-width="1.5"/>')
    def rowband(r0,r1,fill):
        y0=py(r0)-pt/2; y1=py(r1)+pt/2
        add(f'<rect x="{ox+14}" y="{y0:.1f}" width="{BWl-28}" height="{y1-y0:.1f}" fill="{fill}"/>')
    rowband(0,0,RP); rowband(1,1,RG); rowband(3,7,"#ffffff")
    rowband(8,9,CHAN); rowband(10,14,"#ffffff"); rowband(16,16,RG); rowband(17,17,RN)
    for r,lab,col in ((0,"+9 V",PWR),(1,"GND",GRY),(16,"GND",GRY),(17,"−9 V",BLU)):
        if flip: txt(ox+BWl+8,py(r)+4,lab,9.5,a="start",f=col,w="bold")
        else:    txt(ox-10,py(r)+4,lab,8,a="end",f=col,w="bold")
    for c in range(1,NC+1):
        for a,b in ((3,7),(10,14)):
            add(f'<line x1="{px(c):.1f}" y1="{py(a):.1f}" x2="{px(c):.1f}" y2="{py(b):.1f}" stroke="#e3dfd0" stroke-width="{pt*0.19:.1f}"/>')
    for r in (0,1,16,17):
        add(f'<line x1="{px(1):.1f}" y1="{py(r):.1f}" x2="{px(NC):.1f}" y2="{py(r):.1f}" stroke="#dcd7c6" stroke-width="{pt*0.19:.1f}"/>')
    for c in range(1,NC+1):
        for r in range(NP):
            add(f'<circle cx="{px(c):.1f}" cy="{py(r):.1f}" r="{pt*0.085:.2f}" fill="#b5b0a0"/>')
    def res_v(c,r0,r1,label,side=1):
        x,y0,y1=px(c),py(r0),py(r1); m=(y0+y1)/2
        wire([(x,y0),(x,m-24)],SIG); wire([(x,m+24),(x,y1)],SIG)
        add(f'<rect x="{x-8}" y="{m-24}" width="16" height="48" fill="#fff" stroke="{INK}" stroke-width="1.5"/>')
        if side>0: txt(x+13,m+4,label,10,a="start")
        else:      txt(x-13,m+4,label,10,a="end")
    def cap_v(c,r0,r1):
        x,y0,y1=px(c),py(r0),py(r1); m=(y0+y1)/2
        wire([(x,y0),(x,m-5)],SIG); wire([(x,m+5),(x,y1)],SIG)
        add(f'<line x1="{x-10}" y1="{m-5}" x2="{x+10}" y2="{m-5}" stroke="{INK}" stroke-width="2"/>')
        add(f'<line x1="{x-10}" y1="{m+5}" x2="{x+10}" y2="{m+5}" stroke="{INK}" stroke-width="2"/>')
    def diode_v(c,r0,r1,down=True):
        x,y0,y1=px(c),py(r0),py(r1); m=(y0+y1)/2
        wire([(x,y0),(x,m-9)],SIG); wire([(x,m+9),(x,y1)],SIG)
        if down:
            add(f'<path d="M {x-8} {m-9} L {x+8} {m-9} L {x} {m+7} Z" fill="{INK}"/>')
            add(f'<line x1="{x-9}" y1="{m+8}" x2="{x+9}" y2="{m+8}" stroke="{INK}" stroke-width="2.2"/>')
        else:
            add(f'<path d="M {x-8} {m+9} L {x+8} {m+9} L {x} {m-7} Z" fill="{INK}"/>')
            add(f'<line x1="{x-9}" y1="{m-8}" x2="{x+9}" y2="{m-8}" stroke="{INK}" stroke-width="2.2"/>')
    def res_h(c0,c1,r,label):
        y=py(r); xl,xr=min(px(c0),px(c1)),max(px(c0),px(c1)); m=(xl+xr)/2
        wire([(xl,y),(m-22,y)],SIG); wire([(m+22,y),(xr,y)],SIG)
        add(f'<rect x="{m-22}" y="{y-7}" width="44" height="14" fill="#fff" stroke="{INK}" stroke-width="1.5"/>')
        txt(m,y-12,label,8.5)
    def diode_h(c_cath,c_an,r):
        # cathode bar toward logical column c_cath, correct in ANY mirroring
        xk,xa,y=px(c_cath),px(c_an),py(r); m=(xk+xa)/2
        s = 1 if xk>m else -1   # screen direction of cathode from midpoint
        wire([(xa,y),(m-s*9,y)],SIG); wire([(m+s*9,y),(xk,y)],SIG)
        add(f'<path d="M {m-s*9} {y-8} L {m-s*9} {y+8} L {m+s*7} {y} Z" fill="{INK}"/>')
        add(f'<line x1="{m+s*8}" y1="{y-9}" x2="{m+s*8}" y2="{y+9}" stroke="{INK}" stroke-width="2.2"/>')
    def jump(c0,r0,c1,r1):
        wire([(px(c0),py(r0)),(px(c1),py(r1))],ORG,2.4)
    def socket(c0,c1,name):
        # pin 1 = c1-end, BOTTOM bank; notch at the c1 end. DIP numbering runs
        # counterclockwise viewed from the component side: c1..c0 bottom = 1..4,
        # c0..c1 top = 5..8. (v3 had this mirrored about the long axis.)
        x0,x1,y0,y1=px(c0),px(c1),py(7),py(10)
        xl,xr=min(x0,x1),max(x0,x1)
        add(f'<rect x="{xl-14}" y="{y0-11}" width="{xr-xl+28}" height="{y1-y0+22}" rx="3" fill="#fff" stroke="{INK}" stroke-width="1.6"/>')
        nx = xr+14 if x1==xr else xl-14; sw = 1 if x1==xr else 0
        add(f'<path d="M {nx} {(y0+y1)/2-9} A 9 9 0 0 {sw} {nx} {(y0+y1)/2+9}" fill="none" stroke="{INK}" stroke-width="1.4"/>')
        add(f'<circle cx="{x1}" cy="{y1}" r="4" fill="{PWR}"/>'); txt(x1,y1+16,"pin 1",8.5,f=PWR,w="bold")
        if detail: txt((xl+xr)/2,(y0+y1)/2+4,name,10.5,f=GRY)
    if detail:
        res_v(1,6,11,"9.09 k"); res_v(1,12,16,"1.01 k")
        res_v(4,6,11,"10 k"); cap_v(4,12,16); txt(px(4)+14,py(14)+2,"10 nF",9.5,a="start")
        res_v(7,6,11,"10 k"); diode_v(7,12,16,True); jump(7,13,8,13); diode_v(8,12,16,False)
        res_v(10,6,11,"10 k"); diode_v(10,12,16,True); diode_h(10,12,12); diode_v(12,13,16,False)
        # TL072: p1=c18B p2=c17B p3=c16B p4=c15B | p5=c15T p6=c16T p7=c17T p8=c18T
        socket(15,18,"TL072"); jump(18,7,18,0); jump(15,14,15,17)
        cap_v(19,0,1); cap_v(14,16,17)
        # --- P5 precision full-wave rectifier network ---
        res_v(14,6,11,"10k R1")            # input -> (via jumper) pin 2
        jump(14,13,17,13)                  #   R1 bottom -> pin 2 (c17 bottom)
        jump(14,3,13,3); res_h(13,16,4,"10k R3")   # input -> pin 6 (c16 top)
        jump(18,13,20,13)                  # pin 1 -> extension c20 bottom
        diode_v(20,6,11,True)              # D1: VA (c20 top, anode) -> pin 1 ext (cathode)
        diode_h(17,20,12)                  # D2: pin 1 ext (anode) -> pin 2 (cathode)
        jump(20,4,19,4)                    # VA -> c19 top
        res_v(19,6,11,"R2",side=-1)        # 10k: VA -> (via jumper) pin 2   [A1 feedback]
        jump(19,14,17,14)
        res_h(16,20,3,"#1∥#9")             # R/2 = 4.99k: VA -> pin 6
        res_h(16,21,5,"10k R4")            # pin 6 -> out ext c21       [A2 feedback]
        jump(17,6,21,6)                    # pin 7 -> out ext (B5 lands on c21 top)
        jump(16,14,16,16)                  # pin 3 -> GND rail
        jump(15,3,15,1)                    # pin 5 -> GND rail
        # LM358: p1=c27B p2=c26B p3=c25B p4=c24B | p5=c24T p6=c25T p7=c26T p8=c27T
        socket(24,27,"LM358"); jump(27,7,27,0); jump(24,10,24,17)
        jump(26,11,27,11); jump(27,12,29,12); res_v(29,13,16,"1 k")   # P6 load: 1 k as built (card), not the 10 k first specified
        cap_v(26,0,1); cap_v(23,16,17)
        # unused LM358 half termination: pin7<->pin6 (c26T,c25T), pin5 (c24T) -> GND
        jump(25,4,26,4); jump(24,3,24,1)
        txt(px(26),py(5)+14,"unused half:",8.5,f=BLU); txt(px(26),py(6)+10,"7→6, 5→GND",8.5,f=BLU)
        # GND rails tie + power entry at P6 end
        jump(30,1,30,16)
        txt(px(30),py(9)+4,"tie",8.5,f=ORG)
        ex = px(30) + (-34 if flip else 34)
        wire([(px(30),py(0)),(ex,py(0))],PWR,2); txt(ex,py(0)-9,"+9 in",9,a="middle",f=PWR,w="bold")
        wire([(px(30),py(17)),(ex,py(17))],BLU,2); txt(ex,py(17)+18,"−9 in",9,a="middle",f=BLU,w="bold")
        wire([(px(28),py(16)),(ex,py(16)+14)],GRY,2); txt(ex-4,py(16)+17,"GND → star ⏚",9,a="end",f=GRY,w="bold")
        for c,lab,side in ((1,"A1","t"),(1,"B1","b"),(4,"A2","t"),(4,"B2","b"),(7,"A3","t"),(7,"B3","b"),
                           (10,"A4","t"),(10,"B4","b"),(14,"A5","t"),(21,"B5","t"),(25,"A6","b"),(29,"B6","b")):
            x=px(c)
            if side=="t":
                wire([(x,py(3)),(x,oy-24)],SIG,1.4,"5 3"); txt(x,oy-31,lab,9.5,f=SIG,w="bold")
            else:
                wire([(x,py(14)),(x,oy+BHl+22)],SIG,1.4,"5 3")
                txt(x,oy+BHl+36,lab,9.5,f=SIG,w="bold")
    else:
        socket(15,18,"TL072"); socket(24,27,"LM358")
    for c0,c1,lab in ((1,2,"P1"),(4,5,"P2"),(7,8,"P3"),(10,12,"P4"),(15,21,"P5"),(23,29,"P6")):
        xa,xb=px(c0),px(c1); m=(xa+xb)/2
        txt(m,oy+BHl+(58 if detail else 24),lab,12 if detail else 11,w="bold")
    return BWl,BHl

txt(90,110,"① COMPONENT SIDE — place parts in this view",15,a="start",w="bold",f=SIG)
txt(90,130,"Looking down, parts facing you: the orientation of the open pedal on your bench, lid off, board up.",10.5,a="start",f=GRY)
BW1,BH1 = draw_board(300,180,31,True,True)
txt(300+BW1+34,180+BH1/2-8,"IN edge ▶",13,a="start",w="bold",f=PWR)
txt(300+BW1+34,180+BH1/2+10,"(P1, toward right jack)",9.5,a="start",f=PWR)
txt(290,180+BH1/2,"◀ OUT edge",13,a="end",w="bold",f=GRY)

Y2=900
txt(90,Y2-38,"② SOLDER SIDE — the same board flipped left-to-right",15,a="start",w="bold",f=BLU)
txt(90,Y2-18,"Copper toward you. Pin 1 and the notch are in mirrored corners. Nothing is placed from this side.",10.5,a="start",f=GRY)
BW2,BH2 = draw_board(460,Y2,18,False,False)
txt(450,Y2+BH2/2,"◀ IN edge",12,a="end",w="bold",f=PWR)
txt(460+BW2+14,Y2+BH2/2,"OUT edge ▶",12,a="start",w="bold",f=GRY)

# --- off-board harness table ---
HX,HY=90,1330
add(f'<rect x="{HX-20}" y="{HY-30}" width="1400" height="420" rx="8" fill="#fff" stroke="#e4e0d4" stroke-width="2"/>')
txt(HX,HY-8,"③ OFF-BOARD HARNESS — every wire, verified",13,a="start",w="bold")
rows=[
 ("Input path","IN jack tip → 10 µF (bipolar — no orientation) → rotary pole-A WIPER lug.  Then 1 MΩ from the wiper lug to star ground — REQUIRED, not optional: it is P6's op-amp DC bias path. Without it, P6's input floats and the position is dead."),
 ("Pole A fan","Wiper selects; contacts 1–6 → board:  A1→col 1 top · A2→col 4 top · A3→col 7 top · A4→col 10 top · A5→col 14 top · A6→col 25 BOTTOM (LM358 pin 3 — the A-side exception)."),
 ("Pole B fan","Board → contacts 1–6:  B1→col 1 bottom · B2→col 4 bottom · B3→col 7 bottom · B4→col 10 bottom · B5→col 21 TOP (P5's output node, pin 7's extension — the B-side exception) · B6→col 29 bottom."),
 ("Output path","Rotary pole-B WIPER lug → 10 µF (bipolar) → OUT jack tip.  1 MΩ directly across the OUT jack's tip and sleeve lugs (bleed/pop suppression)."),
 ("Power","Battery A(+) → DPDT pole 1 → board +9 rail at the P6 end.  Battery B(−) → DPDT pole 2 → board −9 rail, same end.  Battery A(−) joined to Battery B(+) = centre tap → star ground, UNSWITCHED."),
 ("LED","LED + 10 k in series, from the +9 wire to the −9 wire, on the SWITCHED side (so it indicates rails live). Mount firing out through the bezel, away from the board."),
 ("Star ground","One screw + toothed washer on the lid, scuffed to bare metal. Wires landing there and nowhere else: IN jack sleeve · OUT jack sleeve · board GND rail (single wire, P6 end) · battery centre tap · input 1 MΩ. Enclosure grounds via the screw; jacks must NOT also bond through their bushings — use one or the other, and the screw is the one."),
 ("Rotary","CK1459: one wafer, two poles — identify the two wiper lugs and each pole's contact ring WITH THE METER before soldering; lug order on rotaries does not follow visual intuition."),
]
for i,(k,v) in enumerate(rows):
    y=HY+16+i*48
    txt(HX,y,k,11,a="start",w="bold",f=SIG)
    # wrap text at ~150 chars
    words=v.split(); line=""; ln=0
    for wd in words:
        if len(line)+len(wd)>148:
            txt(HX+120,y+ln*15,line,10,a="start"); ln+=1; line=wd
        else: line=(line+" "+wd).strip()
    txt(HX+120,y+ln*15,line,10,a="start")

# --- meter pre-checks ---
MX,MY=90,1790
add(f'<rect x="{MX-20}" y="{MY-30}" width="1400" height="290" rx="8" fill="#fff" stroke="{PWR}" stroke-width="2"/>')
txt(MX,MY-8,"④ METER CHECKS — CONFIRMED 2026-08-09: rails continuous (3 per long edge; outer=+9/−9, middle=GND, inner spare unused), centerline pads discrete, rows match drawing",13,a="start",w="bold",f=PWR)
checks=[
 "1.  Column isolation: beep between a column's TOP strip and its BOTTOM strip — must be OPEN. A DIP straddling the channel depends on this.",
 "2.  Centre channel: the SB404 has 'centerline pads'. Beep the channel rows against each other and against adjacent strips. If the channel contains CONNECTED bus strips, a socket must NOT straddle them — shift the socket rows so pins land only in the isolated 5-pad banks.",
 "3.  Rail continuity: the label says SIX power rails — the four edge rails may be SPLIT (e.g. left/right halves). Beep each edge rail END TO END. Any split in the bottom GND rail must be bridged: P1–P4's shunts return on the right half, P6's load on the left. Splits in +9/−9 matter only if they fall between the power entry (P6 end) and column 15.",
 "4.  Strip extent: confirm each bank strip is exactly the 5 pads assumed (rows 3–7 / 10–14 in this drawing) and that rail rows are where the drawing puts them. Renumber the drawing to the real board if not.",
 "5.  After harness, before circuits: jumper A1→B1 (straight wire), calibrate, measure — the Stage 0 empty-box check from the build plan.",
]
for i,v in enumerate(checks):
    words=v.split(); line=""; ln=0; y=MY+18+i*52
    for wd in words:
        if len(line)+len(wd)>150:
            txt(MX,y+ln*15,line,10.2,a="start"); ln+=1; line=wd
        else: line=(line+" "+wd).strip()
    txt(MX,y+ln*15,line,10.2,a="start")

svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'+"".join(p)+"</svg>"
import os
open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"board-layout.svg"),"w").write(svg)
print("ok")
