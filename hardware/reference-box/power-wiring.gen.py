W,H = 1500,1050
INK="#1a1a1a"; PWR="#a03020"; BLU="#22488a"; GRY="#666"; ORG="#b06a20"; BG="#fdfcf9"
p=[]
def add(s): p.append(s)
def txt(x,y,s,sz=12,a="middle",f=INK,w="normal",st="normal"):
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="Helvetica,Arial,sans-serif" font-size="{sz}" text-anchor="{a}" fill="{f}" font-weight="{w}" font-style="{st}">{s}</text>')
def wire(pts,c=INK,w=2.2,d=None):
    dd=" ".join(f"{'M' if i==0 else 'L'} {x:.1f} {y:.1f}" for i,(x,y) in enumerate(pts))
    da=f' stroke-dasharray="{d}"' if d else ""
    add(f'<path d="{dd}" stroke="{c}" stroke-width="{w}" fill="none" stroke-linecap="round" stroke-linejoin="round"{da}/>')
def dot(x,y,c=INK,r=4): add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>')

add(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
txt(W/2,40,"Reference Box — power subsystem wiring (batteries · DPDT · LED · star)",20,w="bold")
txt(W/2,64,"DPDT drawn from the REAR (lug side). Verify lug behaviour with the meter BEFORE soldering — toggle lug order does not follow visual intuition.",11.5,f=PWR)

# ---------------- batteries ----------------
def battery(x,y,name,flip_pol=False):
    add(f'<rect x="{x}" y="{y}" width="180" height="110" rx="8" fill="#efece0" stroke="{INK}" stroke-width="2"/>')
    txt(x+90,y+62,name,15,w="bold")
    # snap terminals on top edge
    pxp, pxn = (x+45, x+135) if not flip_pol else (x+135, x+45)
    add(f'<circle cx="{pxp}" cy="{y+20}" r="11" fill="none" stroke="{INK}" stroke-width="2"/>'); txt(pxp,y+25,"+",15,w="bold")
    add(f'<circle cx="{pxn}" cy="{y+20}" r="11" fill="none" stroke="{INK}" stroke-width="2"/>'); txt(pxn,y+25,"−",15,w="bold")
    return (pxp,y+9),(pxn,y+9)
Apos,Aneg = battery(90,150,"Battery A")
Bpos,Bneg = battery(90,330,"Battery B",flip_pol=True)
txt(180,290,"mark the snaps A and B",10.5,f=GRY,st="italic")

# centre tap: A(−) joined to B(+)
wire([Aneg,(Aneg[0],120),(320,120),(320,300),(280,300)],INK,2.2)
wire([Bpos,(Bpos[0],318),(280,318),(280,300)],INK,2.2)
dot(280,300)
txt(330,288,"CENTRE TAP = A(−) + B(+)",11.5,a="start",w="bold")
txt(330,316,"heat-shrink the splice",10,a="start",f=GRY)
# centre tap to star, unswitched (routes right of the verify box)
wire([(280,300),(450,300),(450,960),(700,960)],GRY,3)
# star symbol
add(f'<circle cx="740" cy="960" r="26" fill="none" stroke="{GRY}" stroke-width="2.5"/>')
for dx,dy in ((-18,-18),(18,-18),(-18,18),(18,18),(0,-26),(0,26),(-26,0),(26,0)):
    wire([(740,960),(740+dx*0.55,960+dy*0.55)],GRY,2)
txt(740,1012,"STAR GROUND (lid) — screw + toothed washer",11.5,w="bold",f=GRY)
txt(740,1028,"centre tap lands here UNSWITCHED, its own spot on the tag stack",10.5,f=GRY)
txt(430,946,"crosses the box↔lid boundary: leave lay-the-lid-flat slack",10,f=PWR,st="italic")

# ---------------- DPDT ----------------
SX,SY=560,180   # lug grid origin
add(f'<rect x="{SX-46}" y="{SY-36}" width="172" height="216" rx="10" fill="#efece0" stroke="{INK}" stroke-width="2"/>')
txt(SX+40,SY-50,"DPDT toggle (rear / lug view) — C&amp;K 7201, ON–ON",12.5,w="bold")
lug={}
for ci,cx in enumerate((SX,SX+80)):
    for ri,cy in enumerate((SY,SY+72,SY+144)):
        add(f'<rect x="{cx-9}" y="{cy-14}" width="18" height="28" rx="4" fill="#d8d2c0" stroke="{INK}" stroke-width="1.6"/>')
        add(f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="#fff" stroke="{INK}" stroke-width="1.4"/>')
        lug[(ci,ri)]=(cx,cy)
txt(SX,SY-14,"pole 1",10,f=GRY); txt(SX+80,SY-14,"pole 2",10,f=GRY)
txt(SX+40,SY+40,"row 1: feed",9.5,f=GRY); txt(SX+40,SY+112,"row 2: COMMON",9.5,f=GRY)
txt(SX+40,SY+184,"row 3: not used",9.5,f=GRY)
txt(SX+40,SY+205,"ON = bat thrown AWAY from row 1 (typ.) — CONFIRM with meter",9,f=PWR)

# battery feeds to row-1 lugs
wire([Apos,(Apos[0],100),(SX,100),lug[(0,0)]],PWR,2.6)
txt(400,92,"A(+)  red",10.5,f=PWR,a="middle")
wire([Bneg,(Bneg[0],470),(470,470),(470,132),(SX+80,132),lug[(1,0)]],BLU,2.6)
txt(300,458,"B(−)  black",10.5,f=BLU,a="middle")

# commons to board rails (exit sideways, clear of the unused row-3 lugs)
bx=1130
wire([lug[(0,1)],(500,SY+72),(500,560),(bx,560)],PWR,2.6)
wire([lug[(1,1)],(940,SY+72),(940,600),(bx,600)],BLU,2.6)
txt(700,548,"switched +9 → board +9 rail, P6 end",11,f=PWR,a="middle")
txt(760,620,"switched −9 → board −9 rail, P6 end",11,f=BLU,a="middle")
txt(1030,662,"both cross to the lid: slack",10,f=PWR,st="italic",a="middle")

# board edge sketch
add(f'<rect x="{bx}" y="520" width="300" height="130" rx="6" fill="#f4f1e5" stroke="{GRY}" stroke-width="1.5"/>')
txt(bx+150,505,"SB404 — P6 end (OUT edge)",11.5,w="bold")
wire([(bx+10,560),(bx+70,560)],PWR,3); txt(bx+80,564,"+9 rail (outer)",10,a="start",f=PWR)
wire([(bx+10,585),(bx+70,585)],GRY,3); txt(bx+80,589,"GND rail (middle) → single wire → star",10,a="start",f=GRY)
wire([(bx+10,600),(bx+7,600)],BLU,0.1)
wire([(bx+10,610),(bx+70,610)],GRY,2,d="4 3"); txt(bx+80,614,"inner spare rails — unused",9.5,a="start",f=GRY)
wire([(bx+10,635),(bx+70,635)],BLU,3); txt(bx+80,639,"−9 rail (outer)",10,a="start",f=BLU)
wire([(bx,600),(bx+10,600)],BLU,0.1)
# -9 wire entry continues to the -9 rail
wire([(bx,600),(bx+10,635)],BLU,2.6)

# ---------------- LED ----------------
LX,LY=760,760
txt(LX+60,LY-64,"LED indicator — taps the SWITCHED wires (box side, near the switch)",12.5,w="bold",a="middle")
wire([(500,560),(500,LY),(LX-40,LY)],PWR,2.6)   # from switched +9
dot(500,560,PWR)
# LED symbol: anode left
wire([(LX-40,LY),(LX-12,LY)],PWR,2.2)
add(f'<path d="M {LX-12} {LY-11} L {LX-12} {LY+11} L {LX+10} {LY} Z" fill="{INK}"/>')
add(f'<line x1="{LX+11}" y1="{LY-11}" x2="{LX+11}" y2="{LY+11}" stroke="{INK}" stroke-width="2.4"/>')
for a,b in (((LX-4,LY-14),(LX+4,LY-22)),((LX+4,LY-12),(LX+12,LY-20))):
    wire([a,b],INK,1.4); add(f'<path d="M {b[0]} {b[1]} l -1.5 4.5 l 4.5 -1.5 z" fill="{INK}"/>')
txt(LX-1,LY+32,"LED — long lead (anode) toward +9",9.5,f=GRY)
# series resistor
wire([(LX+11,LY),(LX+40,LY)],INK,2.2)
add(f'<rect x="{LX+40}" y="{LY-8}" width="52" height="16" fill="#fff" stroke="{INK}" stroke-width="1.6"/>')
txt(LX+66,LY-14,"10 k (junk box)",9.5)
wire([(LX+92,LY),(940,LY)],BLU,2.6)
wire([(940,600),(940,LY)],BLU,2.6); dot(940,600,BLU)
txt(LX+66,LY+52,"18 V across LED + 10 k → ≈1.6 mA · no ground-path current · equal drain on both batteries",10,f=GRY)
txt(LX+66,LY+68,"mount in the bezel firing outward, leads heat-shrunk",10,f=GRY)

# ---------------- verify box ----------------
VX,VY=90,560
add(f'<rect x="{VX-20}" y="{VY-28}" width="360" height="330" rx="8" fill="#fff" stroke="{PWR}" stroke-width="2"/>')
txt(VX,VY-6,"VERIFY, IN THIS ORDER",12.5,w="bold",f=PWR)
steps=[
 "1. Meter the bare switch: centre row lugs are the",
 "    commons. Find the bat position that closes",
 "    centre↔row-1 on BOTH poles at once; confirm",
 "    pole 1 never beeps to pole 2.",
 "2. Mount switch. Wire feeds + commons as drawn.",
 "    Heat-shrink every splice; Kapton between",
 "    battery terminals and the chassis.",
 "3. Batteries in, switch OFF: board wire ends read",
 "    0 V to centre tap.  Switch ON: +9.x and −9.x.",
 "    (Fresh PP3s read 9.3–9.6 V — that is normal;",
 "    record the actual values.)",
 "4. LED lights only in ON. If it is dark in ON,",
 "    polarity — flip the LED, nothing is harmed.",
 "5. Only then: land +9/−9 on the board rails, then",
 "    the Stage E socket-pin check (count pins from",
 "    the NOTCH on the socket, not from any drawing),",
 "    chips out → then seat the ICs.",
]
for i,s in enumerate(steps): txt(VX,VY+18+i*17,s,10.5,a="start")

svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'+"".join(p)+"</svg>"
import os
open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"power-wiring.svg"),"w").write(svg)
print("ok")
