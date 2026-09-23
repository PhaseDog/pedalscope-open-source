W,H = 1720,1560
INK="#1a1a1a"; SIG="#1f6b3f"; GRY="#6f6f6f"; PWR="#a03020"; BLU="#22488a"; ORG="#b06a20"
BG="#fdfcf9"
p=[]
def add(s): p.append(s)
def esc(s): return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def txt(x,y,s,sz=12,a="middle",f=INK,w="normal",st="normal"):
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="Helvetica,Arial,sans-serif" font-size="{sz}" '
        f'text-anchor="{a}" fill="{f}" font-weight="{w}" font-style="{st}">{esc(s)}</text>')
def mono(x,y,s,sz=11,a="start",f=INK,w="normal"):
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="Menlo,Consolas,monospace" font-size="{sz}" '
        f'text-anchor="{a}" fill="{f}" font-weight="{w}">{esc(s)}</text>')
def wire(pts,c=INK,w=2.0):
    dd=" ".join(f"{'M' if i==0 else 'L'} {x:.1f} {y:.1f}" for i,(x,y) in enumerate(pts))
    add(f'<path d="{dd}" stroke="{c}" stroke-width="{w}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
def dot(x,y,c=INK,r=4.5): add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>')
def gnd(x,y):
    wire([(x,y),(x,y+14)])
    for i,w_ in enumerate((22,14,7)):
        add(f'<line x1="{x-w_/2}" y1="{y+14+i*6}" x2="{x+w_/2}" y2="{y+14+i*6}" stroke="{INK}" stroke-width="2.2"/>')
def resH(x0,x1,y,name,val,loc):
    wire([(x0,y),(x1,y)]); m=(x0+x1)/2
    add(f'<rect x="{m-30}" y="{y-11}" width="60" height="22" fill="#fff" stroke="{INK}" stroke-width="1.8"/>')
    txt(m,y-18,name,12,w="bold"); txt(m,y+26,val,10.5); txt(m,y+40,loc,9,f=ORG)
def resV(x,y0,y1,name,val,loc,side=1):
    wire([(x,y0),(x,y1)]); m=(y0+y1)/2
    add(f'<rect x="{x-11}" y="{m-30}" width="22" height="60" fill="#fff" stroke="{INK}" stroke-width="1.8"/>')
    a="start" if side>0 else "end"; dx=19*side
    txt(x+dx,m-8,name,12,a=a,w="bold"); txt(x+dx,m+7,val,10.5,a=a); txt(x+dx,m+21,loc,9,a=a,f=ORG)
def diodeH(x0,x1,y,name,val,loc,above=True):
    # NB: x0 = ANODE end, x1 = CATHODE end (band is drawn at the x1 end).
    wire([(x0,y),(x1,y)]); m=(x0+x1)/2; s=1 if x1>x0 else -1
    add(f'<path d="M {m-s*10} {y-12} L {m-s*10} {y+12} L {m+s*9} {y} Z" fill="{INK}"/>')
    add(f'<line x1="{m+s*10}" y1="{y-13}" x2="{m+s*10}" y2="{y+13}" stroke="{INK}" stroke-width="2.6"/>')
    if above: txt(m,y-44,loc,9,f=ORG); txt(m,y-31,val,10,f=GRY); txt(m,y-18,name,12,w="bold")
    else:     txt(m,y+30,name,12,w="bold"); txt(m,y+43,val,10,f=GRY); txt(m,y+56,loc,9,f=ORG)
def opamp(x,yc,h,label,pm,pp,po):
    ytop,ybot=yc-h/2,yc+h/2; xr=x+130
    add(f'<path d="M {x} {ytop} L {x} {ybot} L {xr} {yc} Z" fill="#fff" stroke="{INK}" stroke-width="2.2"/>')
    ym,yp = yc-h/4, yc+h/4
    txt(x+24,ym+7,"−",20,a="start"); txt(x+24,yp+7,"+",16,a="start")
    txt(x+50,ybot+22,label,11,f=GRY)
    txt(x-8,ym-8,pm,10,a="end",f=PWR,w="bold")
    txt(x-8,yp+18,pp,10,a="end",f=PWR,w="bold")
    txt(xr+8,yc-8,po,10,a="start",f=PWR,w="bold")
    return (x,ym),(x,yp),(xr,yc)
def panel(x,y,w,h,title,col,lines,mono_from=99):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#fff" stroke="{col}" stroke-width="1.8"/>')
    txt(x+20,y+26,title,12.5,a="start",w="bold",f=col)
    for i,s in enumerate(lines):
        if i>=mono_from: mono(x+20,y+50+i*17,s,10.5)
        else: txt(x+20,y+50+i*17,s,10.5,a="start")

add(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
txt(W/2,40,"Reference Box — P5 and P6 schematics",22,w="bold")
txt(W/2,63,"Components tagged with measured part and SB404 column (orange).  Pin map per board layout v4: TL072 pin 1 = col 18 bottom · LM358 pin 1 = col 27 bottom.",10.5,f=GRY)

# ================= P5 =================
txt(70,108,"P5 — precision full-wave rectifier    out = | in |",16,a="start",w="bold",f=SIG)
txt(70,129,"Both diodes sit INSIDE op-amp A's feedback loop, so their forward drops never appear in V_A. That is what makes it precision rather than a 0.6 V-lossy rectifier.",10.5,a="start",f=GRY)

# input
txt(150,338,"IN",13,w="bold"); txt(150,322,"from A5 · col 14 top",9,f=ORG)
wire([(115,370),(150,370)]); dot(150,370)
resH(150,345,370,"R1","10 k #4","col 14")
SA=(345,370); dot(*SA); txt(333,352,"S_A",11.5,a="end",w="bold",f=BLU)

mA,pA,oA = opamp(380,400,120,"TL072 · half A","2","3","1")
wire([SA,mA])
wire([pA,(320,430)]); gnd(320,430)

wire([oA,(560,400)]); dot(560,400)
# D2 upper feedback
wire([(345,370),(345,310)]); wire([(560,400),(560,310)])
diodeH(560,345,310,"D2","1N4148 #8","row 12 · col 20 → 17")
# D1 + V_A  — anode at V_A (700), cathode at op-amp A output (560)
diodeH(700,560,400,"D1","1N4148 #2","col 20 vertical",above=False)
wire([(700,400),(700,205)]); dot(700,260); txt(700,242,"V_A",12,w="bold",f=BLU)
# R2
wire([(345,310),(345,205)])
resH(345,700,205,"R2","10 k #10","col 19")
# R/2 to stage B
resH(700,1000,260,"R/2","#1 || #9  =  4.9935 k","col 16 → 20 top")
wire([(1000,260),(1000,360)]); dot(1000,260)
SB=(1000,360); dot(*SB); txt(988,344,"S_B",11.5,a="end",w="bold",f=BLU)

mB,pB,oB = opamp(1040,390,120,"TL072 · half B","6","5","7")
wire([SB,mB])
wire([pB,(1000,420),(1000,432)]); gnd(1000,432)
wire([oB,(1280,390)]); dot(1280,390)
wire([(1280,390),(1430,390)])
txt(1445,394,"OUT → B5",12.5,a="start",w="bold"); txt(1445,410,"col 21 top",9,a="start",f=ORG)
# R4
wire([(1000,360),(1000,150)]); wire([(1280,390),(1280,150)])
resH(1000,1280,150,"R4","10 k #7","col 16 → 21 top")
# R3
wire([(150,370),(150,620),(960,620),(960,360),(1000,360)])
resH(430,660,620,"R3","10 k #2","col 13 → 16 top")

add(f'<rect x="1010" y="528" width="380" height="104" rx="7" fill="#fff" stroke="{BLU}" stroke-width="1.7"/>')
txt(1028,552,"DIODE ORIENTATION — which way the band faces",11.5,a="start",w="bold",f=BLU)
txt(1028,574,"D1  col 20, vertical:  band toward the BOTTOM bank (pin-1 side)",10,a="start")
txt(1028,592,"D2  row 12, cols 20 → 17:  band toward col 17 (pin 2 / S_A)",10,a="start")
txt(1028,614,"Both bands face the op-amp. Both anodes face V_A / the output node.",10,a="start",f=BLU)

txt(465,512,"stage A — inverting half-wave rectifier",10.5,f=GRY,st="italic")
txt(1105,512,"stage B — weighted inverting summer",10.5,f=GRY,st="italic")

add(f'<rect x="1400" y="470" width="270" height="112" rx="7" fill="#fff" stroke="{PWR}" stroke-width="1.6"/>')
txt(1418,494,"TL072 power",11.5,a="start",w="bold",f=PWR)
for i,s in enumerate(["pin 8 → +9 V   (col 18 top)","pin 4 → −9 V   (col 15 bottom)",
                      "100 nF +9→GND at col 19","100 nF GND→−9 at col 14"]):
    txt(1418,516+i*17,s,10,a="start")

# ================= P6 =================
Y=712
txt(70,Y,"P6 — crossover distortion generator    LM358 unity follower into a 1 k load",16,a="start",w="bold",f=SIG)
txt(70,Y+21,"The load forces the un-biased class-B output stage to both source and sink, so the handover glitch appears at every zero crossing.",10.5,a="start",f=GRY)

yc=Y+170
txt(150,yc+2,"IN",13,w="bold"); txt(150,yc-14,"from A6 · col 25 bottom",9,f=ORG)
wire([(115,yc+30),(300,yc+30)])
m6,p6,o6 = opamp(300,yc,120,"LM358 · half A","2","3","1")
wire([(300,yc+30),p6])
wire([o6,(560,yc)]); dot(560,yc)
wire([(560,yc),(560,yc-95),(255,yc-95),(255,yc-30),(300,yc-30)])
txt(408,yc-104,"unity feedback — pin 1 → pin 2  (col 27 → 26 bottom)",10,f=ORG)
wire([(560,yc),(800,yc)]); dot(680,yc)
resV(680,yc,yc+108,"R_L","1 k (0.9976 k as built)","col 29 → GND rail")
gnd(680,yc+108)
txt(818,yc+4,"OUT → B6",12.5,a="start",w="bold"); txt(818,yc+20,"col 29 bottom",9,a="start",f=ORG)

add(f'<rect x="940" y="{Y+50}" width="330" height="215" rx="7" fill="#fff" stroke="{BLU}" stroke-width="1.7"/>')
txt(960,Y+76,"unused half — MUST be terminated",11.5,a="start",w="bold",f=BLU)
txt(960,Y+94,"an open op-amp half oscillates and pollutes the rails",9.5,a="start",f=GRY)
m7,p7,o7 = opamp(1010,Y+175,90,"","6","5","7")
wire([o7,(1195,Y+175)])
wire([(1195,Y+175),(1195,Y+238),(985,Y+238),(985,Y+152),(1010,Y+152)])
wire([p7,(975,Y+198)]); gnd(975,Y+198)
txt(1105,Y+256,"pin 7 → pin 6 · pin 5 → GND",10,f=BLU)

add(f'<rect x="1310" y="{Y+50}" width="360" height="215" rx="7" fill="#fff" stroke="{PWR}" stroke-width="1.7"/>')
txt(1330,Y+76,"LM358 power",11.5,a="start",w="bold",f=PWR)
for i,s in enumerate(["pin 8 → +9 V   (col 27 top)","pin 4 → −9 V   (col 24 bottom)",
                      "100 nF +9→GND at col 26","100 nF GND→−9 at col 23"]):
    txt(1330,Y+100+i*18,s,10,a="start")
txt(1330,Y+190,"NB: pin 4 is V− here, not ground. The LM358",10,a="start",f=PWR)
txt(1330,Y+206,"runs on split rails in this box — its datasheet",10,a="start",f=PWR)
txt(1330,Y+222,"single-supply examples do not apply.",10,a="start",f=PWR)

# ================= panels =================
PY=1080
panel(70,PY,800,300,"HOW P5 WORKS — and where its accuracy comes from",SIG,[
 "in > 0 → S_A rises → op-amp A output swings NEGATIVE → D1 conducts, D2 off.",
 "         Loop closes through R2 + D1, so  V_A = −(R2/R1)·in = −in.",
 "in < 0 → output swings POSITIVE → D2 conducts and clamps the loop; D1 off.",
 "         V_A now sits between two virtual grounds (R2 to S_A, R/2 to S_B) → V_A = 0.",
 "",
 "Stage B sums the two:   out = −R4·( in/R3 + V_A/(R/2) ) = −( in + 2·V_A )",
 "         in > 0:  −(in − 2·in) = +in          in < 0:  −(in) = |in|",
 "",
 "Accuracy is ratios only — the diode drops are divided away by op-amp A's open-loop gain.",
 "Your parts: R4/R3 = 1.0001 · R3/(R/2) = 2.0004 · R2/R1 = 1.0001.",
 "Half-cycle gain mismatch 0.06%, which alone permits ≈ −63 dB fundamental re H2 —",
 "far under the ≥35 dB target, so the resistors are already ruled out as the limit.",
])

panel(900,PY,770,300,"VERIFY WITH BOTH CHIPS OUT — probe the socket pins, counted from the notch",PWR,[
 "TL072      pin 2 → IN node (col 14 top) ....... 10.0 k   (R1)",
 "           pin 6 → IN node ................... 10.0 k   (R3)",
 "           pin 2 → V_A (col 20 top) .......... 10.0 k   (R2)",
 "           pin 6 → V_A ....................... 4.99 k   (R/2)",
 "           pin 6 → col 21 top ................ 10.0 k   (R4)",
 "           col 20 top → col 20 bottom ........ 0.62 V one way only  (D1)",
 "           col 20 bottom → pin 2 ............. 0.62 V one way only  (D2)",
 "           pin 3 → GND = 0 · pin 5 → GND = 0 · pin 8 → +9 = 0 · pin 4 → −9 = 0",
 "           pins 1, 2, 6, 7 → either rail ..... OPEN",
 "",
 "LM358     pin 3 → A6 wire = 0 · pin 1 ↔ pin 2 = 0 · pin 1 → GND = 1.00 k (R_L)",
 "           pin 7 ↔ pin 6 = 0 · pin 5 → GND = 0 · pin 8 → +9 = 0 · pin 4 → −9 = 0",
], mono_from=0)

panel(70,PY+320,1600,150,"P6 BENCH NOTE — the input bias offset, as built",BLU,[
 "The LM358 has PNP input transistors, so bias current flows OUT of pin 3 — typically 20–50 nA, up to 250 nA worst case. Through the 1 MΩ at the rotary wiper that puts",
 "P6's input tens of mV POSITIVE of 0 V (the offset measured positive as built; an earlier version of this note predicted a negative one and was wrong). It shifts where the",
 "crossover notch sits relative to the signal's zero crossing. Read it with the chip in, no signal, rotary on P6: DC at LM358 pin 1 / col 29 bottom — a board node, never the",
 "OUT jack, whose coupling capacitor blocks exactly this DC. As built the notch is even and odd alike: H2 = H3 within 0.3 dB at every note of the standard sweep.",
])

svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'+"".join(p)+"</svg>"
import os
open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"p5-p6-schematic.svg"),"w").write(svg)
print("ok")
