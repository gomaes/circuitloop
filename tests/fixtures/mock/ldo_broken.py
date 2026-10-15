"""Deliberately broken LDO: output capacitor too small for LM2940 stability."""

from circuitloop.lib import Net, finish, part

vin, gnd, vout = Net("VIN"), Net("GND"), Net("VOUT")
j1 = part("TERM_2P_5.08", ref="J1")
j2 = part("TERM_2P_5.08", ref="J2")
u1 = part("LM2940CT-5.0", ref="U1")
c1 = part("C_CER_50V", "470n", ref="C1")
c3 = part("C_CER_50V", "100n", ref="C3")
vin += j1[1], u1["IN"], c1[1]
vout += u1["OUT"], c3[1], j2[1]
gnd += j1[2], u1["GND"], c1[2], c3[2], j2[2]
finish()
