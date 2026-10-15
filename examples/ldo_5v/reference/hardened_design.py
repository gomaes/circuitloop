"""Reference hardened design (Phase 3) for the ldo_5v example.

Adds a resettable PTC (overcurrent), a series rectifier (reverse polarity) and
bulk input capacitance after the protection diode.
"""

from circuitloop.lib import Net, finish, part

vin, gnd, vout = Net("VIN"), Net("GND"), Net("VOUT")
vptc, vprot = Net("VPTC"), Net("VPROT")

j1 = part("TERM_2P_5.08", ref="J1")
j2 = part("TERM_2P_5.08", ref="J2")
f1 = part("PTC_RXEF020", ref="F1")  # overcurrent
d1 = part("1N4007", ref="D1")  # reverse-polarity blocking diode
u1 = part("LM2940CT-5.0", ref="U1")
c4 = part("C_ELEC_25V", "10u", ref="C4")  # bulk input, after the diode
c1 = part("C_CER_50V", "470n", ref="C1")
c2 = part("C_ELEC_16V", "47u", ref="C2")
c3 = part("C_CER_50V", "100n", ref="C3")

vin += j1[1], f1[1]
vptc += f1[2], d1["A"]
vprot += d1["K"], c4["POS"], c1[1], u1["IN"]
vout += u1["OUT"], c2["POS"], c3[1], j2[1]
gnd += j1[2], c4["NEG"], c1[2], u1["GND"], c2["NEG"], c3[2], j2[2]

finish()
