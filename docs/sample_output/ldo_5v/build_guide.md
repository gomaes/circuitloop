# Build guide — ldo_5v

Board: **9 × 9 holes** (22.9 × 22.9 mm) of 2.54 mm perfboard with isolated pads (one spare row/column around the circuit is included).

Hole names: columns **A, B, C …** from the left and rows **1, 2, 3 …** from the top, as seen from the **component side**. On the solder side the columns run right-to-left; the solder-side drawing is already mirrored and labelled with the same hole names.

## 1. Place and solder components (low to high)

| step | ref | part | value | pins → holes | note |
|---|---|---|---|---|---|
| 1 | D1 | 1N5819 |  | A→E6, K→E2 | cathode (band / flat) = K |
| 2 | C1 | C_CER_50V | 470n | 1→F2, 2→F3 |  |
| 3 | F1 | PTC_RXEF020 |  | 1→D8, 2→D6 |  |
| 4 | C2 | C_ELEC_16V | 47u | POS→D4, NEG→C4 | polarised: + to POS |
| 5 | J1 | TERM_2P_5.08 |  | 1→C8, 2→C6 |  |
| 6 | J2 | TERM_2P_5.08 |  | 1→G7, 2→G5 |  |
| 7 | U1 | LM2940CT-5.0 |  | IN→G2, GND→G3, OUT→G4 |  |

Order by height: 1 = lowest: resistors and axial diodes (bend leads to the pitch, lie flat); 2 = IC sockets, ceramic capacitors, pin headers; 3 = LEDs and TO-92 parts (observe orientation); 4 = terminal blocks; 5 = tallest: TO-220 regulators

## 2. Solder-side wiring (tinned wire / solder bridges)

Each run connects the listed holes in a straight line; solder every hole along the run. Do one net at a time and tick it off.

| step | net | run (from → to) | holes |
|---|---|---|---|
| 1 | GND | F3 → G3 | 2 |
| 2 | GND | G3 → H3 | 2 |
| 3 | GND | H3 → H5 | 3 |
| 4 | GND | H5 → G5 | 2 |
| 5 | GND | F3 → C3 | 4 |
| 6 | GND | C3 → C4 | 2 |
| 7 | GND | C4 → C6 | 3 |
| 8 | VFUSED | E6 → D6 | 2 |
| 9 | VIN | D8 → C8 | 2 |
| 10 | VOUT | D4 → G4 | 4 |
| 11 | VOUT | F4 → F7 | 4 |
| 12 | VOUT | F7 → G7 | 2 |
| 13 | VPROT | F2 → E2 | 2 |
| 14 | VPROT | F2 → G2 | 2 |

## 3. Insulated jumper wires

None — every connection is a solder-side run.

## 4. Checks before power-up

- Inspect every joint; look for bridges between adjacent pads of *different* nets.
- Continuity: each net below must beep end-to-end; GND must **not** beep to any supply net.

  - `GND`: F3, C4, C6, G5, G3
  - `VFUSED`: E6, D6
  - `VIN`: D8, C8
  - `VOUT`: D4, G7, G4
  - `VPROT`: F2, E2, G2

- First power-up through a current-limited supply; check the acceptance voltages from the verification report.
