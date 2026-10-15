"""Reference minimal design (Phase 1): LM358 non-inverting amp, G = 1 + 18k/2k = 10."""

from circuitloop.lib import Net, finish, part

vsup, gnd, inp, out, fb = Net("VSUP"), Net("GND"), Net("IN"), Net("OUT"), Net("FB")
fb_b = Net("FB_B")

j1 = part("HDR_1x02", ref="J1")  # supply
j2 = part("HDR_1x03", ref="J2")  # IN / OUT / GND
u1 = part("LM358", ref="U1")
rf = part("R_1/4W", "18k", ref="R1")
rg = part("R_1/4W", "2k", ref="R2")
cd = part("C_CER_50V", "100n", ref="C1")

vsup += j1[1], u1["VCC"], cd[1]
gnd += j1[2], j2[3], u1["GND"], rg[2], cd[2], u1["INPB"]
inp += j2[1], u1["INPA"]
out += j2[2], u1["OUTA"], rf[1]
fb += rf[2], rg[1], u1["INNA"]
fb_b += u1["OUTB"], u1["INNB"]  # unused section wired as a grounded follower

finish()
