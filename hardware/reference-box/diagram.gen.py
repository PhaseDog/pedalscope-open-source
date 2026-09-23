W, H = 1440, 1330
INK="#1a1a1a"; SIG="#1f6b3f"; GRY="#6b6b6b"; PWR="#8a2f22"; BG="#fdfcf9"; BOX="#e8e4da"
p=[]
def add(s): p.append(s)
def txt(x,y,s,size=12,anchor="middle",fill=INK,style="",weight="normal"):
    add(f'<text x="{x}" y="{y}" font-family="Helvetica,Arial,sans-serif" font-size="{size}" '
        f'text-anchor="{anchor}" fill="{fill}" font-style="{style}" font-weight="{weight}">{s}</text>')
def wire(pts,color=SIG,w=1.8,dash=None):
    d=" ".join(f"{'M' if i==0 else 'L'} {x} {y}" for i,(x,y) in enumerate(pts))
    da=f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<path d="{d}" stroke="{color}" stroke-width="{w}" fill="none" stroke-linecap="round"{da}/>')
def dot(x,y,r=4,color=SIG): add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')
def res_h(x,y,label,sub=None):
    wire([(x-38,y),(x-22,y)]); wire([(x+22,y),(x+38,y)])
    add(f'<rect x="{x-22}" y="{y-9}" width="44" height="18" fill="#fff" stroke="{INK}" stroke-width="1.6"/>')
    txt(x,y-16,label,11)
    if sub: txt(x,y+25,sub,9.5,fill=GRY)
def res_v(x,y,label,h=46):
    wire([(x,y),(x,y+10)]); wire([(x,y+h-10),(x,y+h)])
    add(f'<rect x="{x-9}" y="{y+10}" width="18" height="{h-20}" fill="#fff" stroke="{INK}" stroke-width="1.6"/>')
    txt(x+16,y+h/2+4,label,11,anchor="start")
def cap_v(x,y,label,h=46):
    wire([(x,y),(x,y+h/2-5)]); wire([(x,y+h/2+5),(x,y+h)])
    add(f'<line x1="{x-13}" y1="{y+h/2-5}" x2="{x+13}" y2="{y+h/2-5}" stroke="{INK}" stroke-width="2"/>')
    add(f'<line x1="{x-13}" y1="{y+h/2+5}" x2="{x+13}" y2="{y+h/2+5}" stroke="{INK}" stroke-width="2"/>')
    txt(x+18,y+h/2+4,label,11,anchor="start")
def diode_v(x,y,h=40,down=True):
    wire([(x,y),(x,y+h/2-9)]); wire([(x,y+h/2+9),(x,y+h)])
    if down:
        add(f'<path d="M {x-10} {y+h/2-9} L {x+10} {y+h/2-9} L {x} {y+h/2+7} Z" fill="{INK}"/>')
        add(f'<line x1="{x-11}" y1="{y+h/2+8}" x2="{x+11}" y2="{y+h/2+8}" stroke="{INK}" stroke-width="2.2"/>')
    else:
        add(f'<path d="M {x-10} {y+h/2+9} L {x+10} {y+h/2+9} L {x} {y+h/2-7} Z" fill="{INK}"/>')
        add(f'<line x1="{x-11}" y1="{y+h/2-8}" x2="{x+11}" y2="{y+h/2-8}" stroke="{INK}" stroke-width="2.2"/>')
def gnd(x,y):
    wire([(x,y),(x,y+8)],color=GRY)
    for i,w_ in enumerate([20,13,6]):
        add(f'<line x1="{x-w_/2}" y1="{y+8+i*5}" x2="{x+w_/2}" y2="{y+8+i*5}" stroke="{GRY}" stroke-width="2"/>')
def opamp(x,y,label="",h=64,w=72,flip=False):
    add(f'<path d="M {x} {y-h/2} L {x+w} {y} L {x} {y+h/2} Z" fill="#fff" stroke="{INK}" stroke-width="1.7"/>')
    top,bot=("+","−") if flip else ("−","+")
    txt(x+15,y-13,top,15 if top=="−" else 13,anchor="start")
    txt(x+15,y+21,bot,15 if bot=="−" else 13,anchor="start")
    if label: txt(x+w/2-4,y+4,label,10,fill=GRY)
def jack(x,y,label):
    add(f'<circle cx="{x}" cy="{y}" r="13" fill="#fff" stroke="{INK}" stroke-width="1.8"/>')
    add(f'<circle cx="{x}" cy="{y}" r="4.5" fill="{INK}"/>')
    txt(x,y-24,label,12,weight="bold")

add(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
txt(W/2,44,"PedalScope Reference Box — signal path and positions",19,weight="bold")
txt(W/2,66,"Addendum E · 1590BB · Lorlin CK1459 2P6T non-shorting · both signal legs switched",12,fill=GRY)

ROWS=[152,312,472,632,792,962]
PA, PB = 300, 1010
CL, CR = 344, 966
IY=560

jack(72,IY,"IN"); wire([(85,IY),(140,IY)])
add(f'<line x1="140" y1="{IY-14}" x2="140" y2="{IY+14}" stroke="{INK}" stroke-width="2"/>')
add(f'<line x1="150" y1="{IY-14}" x2="150" y2="{IY+14}" stroke="{INK}" stroke-width="2"/>')
wire([(150,IY),(200,IY)]); txt(145,IY-22,"10 µF",10.5)
dot(200,IY,3.5); res_v(200,IY,"1 M",46); gnd(200,IY+46)
wire([(200,IY),(258,IY)]); dot(262,IY,5,INK)
txt(262,IY+24,"wiper",10,fill=GRY)

jack(1368,IY,"OUT"); wire([(1355,IY),(1300,IY)])
add(f'<line x1="1300" y1="{IY-14}" x2="1300" y2="{IY+14}" stroke="{INK}" stroke-width="2"/>')
add(f'<line x1="1290" y1="{IY-14}" x2="1290" y2="{IY+14}" stroke="{INK}" stroke-width="2"/>')
wire([(1290,IY),(1244,IY)]); txt(1295,IY-22,"10 µF",10.5)
dot(1244,IY,3.5); res_v(1244,IY,"1 M",46); gnd(1244,IY+46)
wire([(1244,IY),(1186,IY)]); dot(1182,IY,5,INK)
txt(1182,IY+24,"wiper",10,fill=GRY)

for px,lbl,anch in ((PA,"pole A  ·  input distribution","end"),(PB,"pole B  ·  output collection","start")):
    add(f'<line x1="{px}" y1="{ROWS[0]-28}" x2="{px}" y2="{ROWS[-1]+28}" stroke="{BOX}" stroke-width="28" stroke-linecap="round"/>')
    txt(px+(-18 if anch=="end" else 18),ROWS[0]-44,lbl,11,anchor=anch,fill=GRY)
    for i,ry in enumerate(ROWS):
        dot(px,ry,5,INK)
        txt(px+(-16 if anch=="end" else 16),ry+4,str(i+1),9.5,anchor=anch,fill=GRY)
wire([(262,IY),(PA,ROWS[0])],color=INK,w=2.2)
wire([(1182,IY),(PB,ROWS[0])],color=INK,w=2.2)
txt(196,IY-64,"wiper selects one",9.5,anchor="start",fill=GRY)
txt(196,IY-51,"position at a time",9.5,anchor="start",fill=GRY)

names=["P1  Reference divider","P2  RC low-pass","P3  Symmetric clipper",
       "P4  Asymmetric clipper","P5  Full-wave rectifier","P6  Crossover"]
# As-built predictions (Bench/expected-values.md, "Per-position predictions" — the card is the
# authority; the original nominal predictions are retired where the card retires them):
#  P1 "At the standing Line setting: −20.41 dB (measured −20.5). Unloaded the divider gives −20.06"
#     — the figure follows the load.
#  P2 "plateau −2.59 dB; loaded corner f_c = 2121 Hz (the 1590 Hz previously carried here was the
#     *unloaded* corner and is retired)".
#  P3 "H2 is not at the floor: it is real, ~20 dB below H3, and ~11 dB above the rig's even-order
#     floor. The earlier 'H2 at the floor, exactly' claim is retired. Knee empirical".
#  P5 "H4/H2 = −13.98 dB, H6/H2 = −21.34 dB (the −21.7 previously carried here was arithmetically
#     wrong: 20·log₁₀(3/35) = −21.34)".
#  P6 "'Odd-dominant' ... is not what the −26 dBFS sweep measures on any date: H2 = H3 within
#     0.3 dB at every note ... its notch is even and odd alike"; "Treat all P6 numbers as
#     empirical properties of this specific chip".
preds=["H1 flat · −20.41 dB into the rig's ≈30 kΩ input, −20.06 dB unloaded (the figure follows the load) · harmonics at the floor",
       "plateau −2.59 dB · −3 dB at the LOADED corner, f_c = 2121 Hz (1590 Hz was unloaded — retired) · compensated loop → a line",
       "H2 real: ≈20 dB below H3, ≈11 dB above the rig's even floor (the 'symmetry zero' is retired) · H3 ≫ H5 · knee ≈ ±0.6 V, empirical",
       "H2 well above the floor and rising with drive · clip levels asymmetric ≈ 2 : 1",
       "H4/H2 = −13.98 dB · H6/H2 = −21.34 dB · fundamental suppressed by design",
       "THD rises as level FALLS · even and odd alike (H2 = H3 within 0.3 dB) · no conventional knee · chip-specific, empirical"]
for i,ry in enumerate(ROWS):
    off = 78 if i==5 else 56
    add(f'<line x1="{PA}" y1="{ry}" x2="{CL}" y2="{ry}" stroke="{SIG}" stroke-width="1.8"/>')
    add(f'<line x1="{CR}" y1="{ry}" x2="{PB}" y2="{ry}" stroke="{SIG}" stroke-width="1.8"/>')
    txt(CL-2,ry-off,names[i],13,anchor="start",weight="bold")
    txt(CL-2,ry-off+16,preds[i],10.5,anchor="start",fill=GRY,style="italic")

ry=ROWS[0]
res_h(470,ry,"9.09 k","1 %"); wire([(CL,ry),(432,ry)]); wire([(508,ry),(CR,ry)])
dot(610,ry,3.5); res_v(610,ry,"1.01 k",50); gnd(610,ry+50)

ry=ROWS[1]
res_h(470,ry,"10 k","1 %"); wire([(CL,ry),(432,ry)]); wire([(508,ry),(CR,ry)])
dot(610,ry,3.5); cap_v(610,ry,"10 nF   ← measure it, then recompute f_c",50); gnd(610,ry+50)

ry=ROWS[2]
res_h(470,ry,"10 k"); wire([(CL,ry),(432,ry)]); wire([(508,ry),(CR,ry)])
dot(610,ry,3.5)
wire([(586,ry),(634,ry)]); wire([(586,ry),(586,ry+8)]); wire([(634,ry),(634,ry+8)])
diode_v(586,ry+8,40,True); diode_v(634,ry+8,40,False)
wire([(586,ry+48),(634,ry+48)]); wire([(610,ry+48),(610,ry+56)]); gnd(610,ry+56)
txt(676,ry+32,"hand-matched 1N4148 pair —",10,anchor="start",fill=GRY)
txt(676,ry+46,"matching bounds H2 — as built ≈20 dB below H3, not a zero",10,anchor="start",fill=GRY)

ry=ROWS[3]
res_h(470,ry,"10 k"); wire([(CL,ry),(432,ry)]); wire([(508,ry),(CR,ry)])
dot(610,ry,3.5)
wire([(580,ry),(646,ry)]); wire([(580,ry),(580,ry+8)]); wire([(646,ry),(646,ry+8)])
diode_v(580,ry+8,40,True)
diode_v(646,ry+8,26,False); diode_v(646,ry+34,26,False)
wire([(580,ry+48),(580,ry+62)]); wire([(646,ry+60),(580,ry+62)])
wire([(610,ry+62),(610,ry+70)]); gnd(610,ry+70)
txt(688,ry+26,"one up  /  two down",10,anchor="start",fill=GRY)
txt(688,ry+40,"≈ 0.6 V  vs  ≈ 1.2 V",10,anchor="start",fill=GRY)

ry=ROWS[4]
add(f'<rect x="440" y="{ry-26}" width="400" height="72" rx="8" fill="#fff" stroke="{INK}" stroke-width="1.7"/>')
wire([(CL,ry),(440,ry)]); wire([(840,ry),(CR,ry)])
txt(640,ry-6,"TL072  ·  precision full-wave rectifier   ·   out ≈ | x |",12,weight="bold")
txt(640,ry+13,"2 op-amps · 4 × 10 k hand-matched · 2 × 1N4148 in the loops · ±9 V",10,fill=GRY)
txt(640,ry+31,"build per a published reference topology — the resistor ratios ARE the accuracy",9.5,fill=PWR,style="italic")

ry=ROWS[5]
wire([(CL,ry),(496,ry)]); wire([(496,ry),(496,ry-18)]); wire([(496,ry-18),(548,ry-18)])
opamp(548,ry,"LM358",flip=True)
wire([(620,ry),(700,ry)])
dot(664,ry,3.5)
wire([(664,ry),(664,ry+56)]); wire([(664,ry+56),(516,ry+56)]); wire([(516,ry+56),(516,ry+18)]); wire([(516,ry+18),(548,ry+18)])
dot(768,ry,3.5); wire([(700,ry),(768,ry)]); res_v(768,ry,"1 k  load",50); gnd(768,ry+50)
wire([(768,ry),(CR,ry)])
txt(830,ry+34,"unity follower · load to ground",10,anchor="start",fill=GRY)
txt(830,ry+48,"forces class-B crossover",10,anchor="start",fill=GRY)

py=1140
add(f'<rect x="72" y="{py-70}" width="580" height="176" rx="8" fill="#fff" stroke="{BOX}" stroke-width="2"/>')
txt(96,py-46,"POWER  —  P5 and P6 only",12,anchor="start",weight="bold")
bx=210
wire([(bx,py-24),(bx,py+72)],color=PWR,w=2)
def batt_v(x,y):
    add(f'<line x1="{x-14}" y1="{y-5}" x2="{x+14}" y2="{y-5}" stroke="{INK}" stroke-width="2.6"/>')
    add(f'<line x1="{x-7}" y1="{y+5}" x2="{x+7}" y2="{y+5}" stroke="{INK}" stroke-width="2.6"/>')
batt_v(bx,py-2); batt_v(bx,py+50)
txt(bx-24,py+2,"9 V",10,anchor="end"); txt(bx-24,py+54,"9 V",10,anchor="end")
txt(bx,py-34,"+9 V",10.5,fill=PWR); txt(bx,py+90,"−9 V",10.5,fill=PWR)
dot(bx,py+24,4.5,GRY); wire([(bx,py+24),(bx+64,py+24)],color=GRY); gnd(bx+64,py+24)
txt(bx+96,py+28,"centre tap = ground",10,anchor="start",fill=GRY)
for i,s in enumerate(["DPDT toggle breaks BOTH rails",
                      "100 nF rail-to-ground at every IC socket",
                      "verify ±9 V at the sockets before inserting chips",
                      "use sockets — never solder these ICs in"]):
    txt(360,py-18+i*20,s,10.5,anchor="start",fill=PWR if i==2 else INK)

add(f'<rect x="692" y="{py-70}" width="676" height="176" rx="8" fill="#fff" stroke="{BOX}" stroke-width="2"/>')
txt(716,py-46,"BUILD ORDER  —  verify each position before adding the next",12,anchor="start",weight="bold")
notes=["0.   Harness only: jumper A1→B1 as a straight wire, calibrate, confirm the empty box measures as a cable.",
 "1.   P1, P2 — passive, exact, unpowered. P2's transfer-curve loop must collapse to a straight line.",
 "2.   P3, P4 — passive clipping. P3's evens are real and small (≈20 dB under H3) — a matching residue, not a zero.",
 "3.   Power subsystem, meter-verified at the sockets before any chip goes in.",
 "4.   P5, P6 — judge P5 on H4/H2, H6/H2 AND THD: the even ladder predicts the reported THD. P6 is chip-specific.",
 "5.   Full-suite sweep across CIRCUIT = P1…P6. The pivot figure IS the validation report — alias and keep it."]
for i,n in enumerate(notes):
    txt(716,py-20+i*20,n,10.5,anchor="start",fill=INK if i==0 else GRY)

txt(W/2,H-18,"Star ground — jack sleeves, all circuit grounds and the battery centre tap home-run to one point.",10.5,fill=GRY)

svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'+"".join(p)+"</svg>"
import os
open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"diagram.svg"),"w").write(svg)
print("ok")
