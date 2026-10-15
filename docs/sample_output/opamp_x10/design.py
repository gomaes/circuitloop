from circuitloop.lib import Net, finish, part

vsup, vcc, gnd = Net("VSUP"), Net("VCC"), Net("GND")
vin, inp, vout, fb = Net("IN"), Net("INP"), Net("OUT"), Net("FB")

j1 = part("TERM_2P_5.08", ref="J1")  # supply
j2 = part("HDR_1x02", ref="J2")      # input signal
j3 = part("HDR_1x02", ref="J3")      # output
d1 = part("1N4007", ref="D1")
u1 = part("LM358", ref="U1")
c1 = part("C_CER_50V", "100n", ref="C1")
c2 = part("C_ELEC_25V", "10u", ref="C2")
r1 = part("R_1/4W", "1k", ref="R1")   # input series protection
d2 = part("1N4148", ref="D2")        # clamps negative excursions on INP
r2 = part("R_1/4W", "9k1", ref="R2")  # feedback
r3 = part("R_1/4W", "1k", ref="R3")   # gain-set to ground

vsup += j1[1], d1["A"]
vcc += d1["K"], u1["VCC"], c1[1], c2["POS"]
gnd += d2["A"], j1[2], j2[2], j3[2], u1["GND"], c1[2], c2["NEG"], r3[2], u1["INPB"]
vin += j2[1], r1[1]
inp += r1[2], u1["INPA"], d2["K"]
vout += u1["OUTA"], r2[1], j3[1]
fb += u1["INNA"], r2[2], r3[1]
# unused section B: follower with IN+ grounded
u1["OUTB"] += u1["INNB"]

finish()
