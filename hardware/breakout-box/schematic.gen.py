# PedalScope Breakout Box — schematic. Generated, never hand-edited:
#   python3 schematic.gen.py   → writes schematic.svg beside this script.
# Stock Python 3, no dependencies, deterministic bytes (run it twice, cmp).
# Source of every connection drawn: the user guide's Breakout Box section
# (04-reference/bench-fixtures.md), checked against the build photo in
# photos/breakout-box-inside.jpg. Labels are the panel's own words.
W,H = 1200,790
INK="#1a1a1a"; SIG="#b03a20"; RES="#b06a20"; GND="#555"; GRY="#666"; BG="#fdfcf9"; BOX="#8a8a8a"
p=[]
def add(s): p.append(s)
def txt(x,y,s,sz=13,a="middle",f=INK,w="normal",st="normal"):
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="Helvetica,Arial,sans-serif" font-size="{sz}" text-anchor="{a}" fill="{f}" font-weight="{w}" font-style="{st}">{s}</text>')
def wire(pts,c=INK,w=2.4,d=None):
    dd=" ".join(f"{'M' if i==0 else 'L'} {x:.1f} {y:.1f}" for i,(x,y) in enumerate(pts))
    da=f' stroke-dasharray="{d}"' if d else ""
    add(f'<path d="{dd}" stroke="{c}" stroke-width="{w}" fill="none" stroke-linecap="round" stroke-linejoin="round"{da}/>')
def dot(x,y,c=INK,r=4.5): add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>')

add(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
txt(W/2,40,"Breakout Box — schematic",21,w="bold")
txt(W/2,64,"Three TS jacks, three 4 mm posts, one 10 kΩ resistor. Everything else is wire.",13,f=GRY)

# Enclosure outline: the Hammond 1590B is the ground plane (drawn dashed).
add(f'<rect x="60" y="100" width="1080" height="560" rx="14" fill="none" stroke="{BOX}" stroke-width="2" stroke-dasharray="9 6"/>')
txt(80,124,"Hammond 1590B enclosure — die-cast aluminium, bonded to the common sleeve",12.5,a="start",f=BOX,w="bold")

# A TS jack: a panel symbol with a tip terminal and a sleeve terminal.
# side = "left" puts the mating face on the left (a jack at the box edge).
def jack(x,y,name,note,side):
    add(f'<rect x="{x-34}" y="{y-44}" width="68" height="120" rx="6" fill="#efece0" stroke="{INK}" stroke-width="2"/>')
    fx = x-34 if side=="left" else x+34
    add(f'<rect x="{fx-6}" y="{y-24}" width="12" height="80" fill="#d8d2c0" stroke="{INK}" stroke-width="1.6"/>')
    txt(x,y-54,name,15,w="bold")
    txt(x,y+90,note,11,f=GRY)
    tx = x+34 if side=="left" else x-34
    txt(x,y+4,"T",12,f=SIG,w="bold"); txt(x,y+52,"S",12,f=GND,w="bold")
    dot(tx,y,SIG); dot(tx,y+48,GND)
    return (tx,y),(tx,y+48)

# A 4 mm binding post, drawn from above, with its colour.
def post(x,y,name,fill):
    add(f'<circle cx="{x}" cy="{y}" r="17" fill="{fill}" stroke="{INK}" stroke-width="2"/>')
    add(f'<circle cx="{x}" cy="{y}" r="6" fill="{BG}" stroke="{INK}" stroke-width="1.4"/>')
    txt(x,y-26,name,14,w="bold")
    return (x,y+17)

INt, INs   = jack(150,300,"IN","from the interface's output","left")
OUTt, OUTs = jack(1040,230,"OUT","to the pedal — direct","right")
O10t, O10s = jack(1040,470,"OUT 10k","to the pedal — via 10 kΩ","right")

TIPp   = post(560,170,"TIP","#c8322a")
T10p   = post(760,420,"TIP +10k","#c8322a")
SLVp   = post(300,515,"SLEEVE","#222")

# Signal: IN tip → TIP post → OUT tip (direct pass-through).
J1=(400,300)
wire([INt,J1],SIG)
wire([J1,(400,230),OUTt],SIG)
wire([(TIPp[0],230),TIPp],SIG); dot(TIPp[0],230,SIG)
dot(*J1,SIG)
txt(760,222,"direct: IN tip = TIP = OUT tip",12,f=SIG)

# Signal: IN tip → 10 kΩ → TIP +10k post → OUT 10k tip.
wire([J1,(400,470),(470,470)],SIG)
add(f'<rect x="470" y="458" width="110" height="24" fill="#fff" stroke="{RES}" stroke-width="2.2"/>')
txt(525,475,"10 kΩ",13,f=RES,w="bold")
txt(525,504,"1 %, ¼ W — the only component",11,f=RES)
wire([(580,470),O10t],RES)
wire([(T10p[0],470),T10p],RES); dot(T10p[0],470,RES)
txt(870,462,"TIP +10k = OUT 10k tip",12,f=RES)

# Common sleeve: every jack sleeve, the SLEEVE post, the enclosure.
GY=570
wire([INs,(240,INs[1]),(240,GY),(950,GY)],GND)
wire([OUTs,(950,OUTs[1]),(950,GY)],GND)
wire([O10s,(950,O10s[1])],GND); dot(950,O10s[1],GND)
wire([SLVp,(SLVp[0],GY)],GND); dot(SLVp[0],GY,GND); dot(950,GY,GND)
txt(390,562,"common sleeve",12,f=GND,w="bold")
# Chassis bond: non-isolated jacks ground every sleeve to the enclosure.
def chassis(x,y):
    wire([(x,y),(x,y+18)],GND)
    for i,hw in enumerate((20,13,6)):
        wire([(x-hw,y+18+i*7),(x+hw,y+18+i*7)],GND,2)
    for k in range(-1,2):
        wire([(x+k*12,y+32),(x+k*12-7,y+40)],GND,1.6)
dot(700,GY,GND); chassis(700,GY)
txt(728,GY+34,"enclosure, through the non-isolated jack bushings",11.5,a="start",f=GND)

# Lid bond: a lead from the common ground to a solder lug bolted inside the lid.
LX=1060
wire([(950,GY),(LX,GY),(LX,600)],GND,2.4,d="7 5")
add(f'<rect x="{LX-70}" y="600" width="140" height="44" rx="6" fill="#efece0" stroke="{BOX}" stroke-width="2"/>')
txt(LX,620,"LID",13,w="bold",f=BOX)
txt(LX,637,"solder lug + star washer",10.5,f=GRY)
txt(LX-58,GY+22,"lid-bond lead",11.5,f=GND)

# Notes.
txt(80,692,"Every connector is TS — tip and sleeve, nothing else — so the loop is single-ended wherever it meets the box.",12,a="start")
txt(80,712,"Line-level signal only. Never connect this box to an amplifier's speaker output.",12,a="start",f=SIG,w="bold")
txt(80,732,"No hole positions are given: none has been measured.",11.5,a="start",f=GRY,st="italic")
txt(80,768,"PedalScope Breakout Box · CERN-OHL-P-2.0 · generated by schematic.gen.py",10.5,a="start",f=GRY)

svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'+"".join(p)+"</svg>"
import os
open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"schematic.svg"),"w").write(svg)
print("ok")
