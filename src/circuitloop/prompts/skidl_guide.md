# Writing design.py for circuitloop

`design.py` is plain Python using SKiDL through circuitloop's thin API.

```python
from circuitloop.lib import Net, finish, part

# 1. Nets. Names used by the spec (power input, loads, stimuli, measured nets)
#    must match exactly. Other nets: give them short descriptive names.
vin, gnd, vout = Net("VIN"), Net("GND"), Net("VOUT")

# 2. Parts — only keys from ref/parts_catalog.md.
#    R/C families need a value ("10k", "4k7", "100n", "47u"); ICs do not.
j1 = part("TERM_2P_5.08", ref="J1")
u1 = part("LM2940CT-5.0", ref="U1")
c1 = part("C_CER_50V", "470n", ref="C1")
c2 = part("C_ELEC_16V", "47u", ref="C2")  # polarised: POS / NEG

# 3. Connections: `net += pin, pin, ...`
#    Pins are addressed by NAME from the catalog (u1["IN"]) or by number (j1[1]).
vin += j1[1], u1["IN"], c1[1]
vout += u1["OUT"], c2["POS"]
gnd += j1[2], u1["GND"], c1[2], c2["NEG"]

# 4. Always end with finish(): runs SKiDL ERC and writes the netlist.
finish()
```

## Rules of thumb that the verifier checks

- Every non-optional pin must be connected. Unused op-amp sections: wire as a
  follower (OUT -> IN-) with IN+ tied to ground or a bias net.
- No net may connect to a single pin, except the spec's interface nets.
- Input pins must not be connected only to other input pins (floating input).
- ICs listed with `decoupling` in the catalog need at least that capacitance
  directly between the given pins' nets.
- Every LED needs its own series resistor; its current is checked in simulation.
- Polarised capacitors: `POS` to the more positive net. Diodes/LEDs: `A` anode, `K` cathode.
- All parts are checked against their ratings × the spec's derating factors in
  every simulated operating condition (v_min, v_nom, v_max).
- Reference designators must be unique (`ref="R1"`, ...). Omitting `ref` auto-numbers.
