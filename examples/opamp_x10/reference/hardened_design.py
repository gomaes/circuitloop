"""Reference hardened design (Phase 3): supply reverse-polarity diode, input series resistor."""

from circuitloop.lib import Net, finish, part

vsup, gnd, inp, out, fb = Net("VSUP"), Net("GND"), Net("IN"), Net("OUT"), Net("FB")
vcc, inp_r, fb_b = Net("VCC"), Net("IN_R"), Net("FB_B")

j1 = part("HDR_1x02", ref="J1")
j2 = part("HDR_1x03", ref="J2")
d1 = part("1N4007", ref="D1")  # reverse polarity
cb = part("C_ELEC_16V", "10u", ref="C2")  # bulk after the diode
u1 = part("LM358", ref="U1")
ri = part("R_1/4W", "1k", ref="R3")  # input series protection
rf = part("R_1/4W", "18k", ref="R1")
rg = part("R_1/4W", "2k", ref="R2")
cd = part("C_CER_50V", "100n", ref="C1")

vsup += j1[1], d1["A"]
vcc += d1["K"], cb["POS"], u1["VCC"], cd[1]
gnd += j1[2], j2[3], cb["NEG"], u1["GND"], rg[2], cd[2], u1["INPB"]
inp += j2[1], ri[1]
inp_r += ri[2], u1["INPA"]
out += j2[2], u1["OUTA"], rf[1]
fb += rf[2], rg[1], u1["INNA"]
fb_b += u1["OUTB"], u1["INNB"]

finish()
