"""Reference minimal design (Phase 1) for the ldo_5v example."""

from circuitloop.lib import Net, finish, part

vin, gnd, vout = Net("VIN"), Net("GND"), Net("VOUT")

j1 = part("TERM_2P_5.08", ref="J1")  # 9 V input
j2 = part("TERM_2P_5.08", ref="J2")  # 5 V output
u1 = part("LM2940CT-5.0", ref="U1")
c1 = part("C_CER_50V", "470n", ref="C1")  # input decoupling
c2 = part("C_ELEC_16V", "47u", ref="C2")  # output stability cap (>= 22 uF)
c3 = part("C_CER_50V", "100n", ref="C3")  # output HF decoupling

vin += j1[1], u1["IN"], c1[1]
vout += u1["OUT"], c2["POS"], c3[1], j2[1]
gnd += j1[2], u1["GND"], c1[2], c2["NEG"], c3[2], j2[2]

finish()
