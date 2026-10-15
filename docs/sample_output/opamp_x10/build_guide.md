# Build guide — opamp_x10

Board: **13 × 11 holes** (33.0 × 27.9 mm) of 2.54 mm perfboard with isolated pads (one spare row/column around the circuit is included).

Hole names: columns **A, B, C …** from the left and rows **1, 2, 3 …** from the top, as seen from the **component side**. On the solder side the columns run right-to-left; the solder-side drawing is already mirrored and labelled with the same hole names.

## 1. Place and solder components (low to high)

| step | ref | part | value | pins → holes | note |
|---|---|---|---|---|---|
| 1 | D1 | 1N4007 |  | A→K4, K→K8 | cathode (band / flat) = K |
| 2 | D2 | 1N4148 |  | A→F3, K→F6 | cathode (band / flat) = K |
| 3 | R1 | R_1/4W | 1k | 1→G2, 2→G6 |  |
| 4 | R2 | R_1/4W | 9k1 | 1→C4, 2→C8 |  |
| 5 | R3 | R_1/4W | 1k | 1→D7, 2→D3 |  |
| 6 | C1 | C_CER_50V | 100n | 1→J8, 2→J7 |  |
| 7 | J2 | HDR_1x02 |  | 1→H2, 2→H3 |  |
| 8 | J3 | HDR_1x02 |  | 1→E5, 2→E4 |  |
| 9 | U1 | LM358 |  | OUTA→H7, INNA→G7, INPA→F7, GND→E7, INPB→E10, INNB→F10, OUTB→G10, VCC→H10 | socket; pin 1 notch/dot; use a DIP-8 socket |
| 10 | C2 | C_ELEC_25V | 10u | POS→J9, NEG→J10 | polarised: + to POS |
| 11 | J1 | TERM_2P_5.08 |  | 1→I4, 2→I6 |  |

Order by height: 1 = lowest: resistors and axial diodes (bend leads to the pitch, lie flat); 2 = IC sockets, ceramic capacitors, pin headers; 3 = LEDs and TO-92 parts (observe orientation); 4 = terminal blocks; 5 = tallest: TO-220 regulators

## 2. Solder-side wiring (tinned wire / solder bridges)

Each run connects the listed holes in a straight line; solder every hole along the run. Do one net at a time and tick it off.

| step | net | run (from → to) | holes |
|---|---|---|---|
| 1 | GND | J7 → J6 | 2 |
| 2 | GND | J6 → I6 | 2 |
| 3 | GND | J7 → L7 | 3 |
| 4 | GND | L7 → L10 | 4 |
| 5 | GND | L10 → J10 | 3 |
| 6 | GND | L7 → L3 | 5 |
| 7 | GND | L3 → H3 | 5 |
| 8 | GND | H3 → F3 | 3 |
| 9 | GND | F3 → F4 | 2 |
| 10 | GND | F4 → E4 | 2 |
| 11 | GND | F3 → D3 | 3 |
| 12 | GND | D3 → B3 | 3 |
| 13 | GND | B3 → B6 | 4 |
| 14 | GND | B6 → E6 | 4 |
| 15 | GND | E6 → E7 | 2 |
| 16 | GND | B6 → B10 | 5 |
| 17 | GND | B10 → E10 | 4 |
| 18 | FB | C8 → C7 | 2 |
| 19 | FB | C7 → D7 | 2 |
| 20 | FB | C8 → G8 | 5 |
| 21 | FB | G8 → G7 | 2 |
| 22 | IN | H2 → G2 | 2 |
| 23 | INP | F6 → G6 | 2 |
| 24 | INP | F6 → F7 | 2 |
| 25 | N$1 | F10 → G10 | 2 |
| 26 | OUT | E5 → C5 | 3 |
| 27 | OUT | C5 → C4 | 2 |
| 28 | OUT | E5 → H5 | 4 |
| 29 | OUT | H5 → H7 | 3 |
| 30 | VCC | J8 → J9 | 2 |
| 31 | VCC | J8 → K8 | 2 |
| 32 | VCC | J9 → H9 | 3 |
| 33 | VCC | H9 → H10 | 2 |
| 34 | VSUP | K4 → I4 | 3 |

## 3. Insulated jumper wires

None — every connection is a solder-side run.

## 4. Checks before power-up

- Inspect every joint; look for bridges between adjacent pads of *different* nets.
- Continuity: each net below must beep end-to-end; GND must **not** beep to any supply net.

  - `FB`: C8, D7, G7
  - `GND`: J7, J10, F3, I6, H3, E4, D3, E7, E10
  - `IN`: H2, G2
  - `INP`: F6, G6, F7
  - `N$1`: F10, G10
  - `OUT`: E5, C4, H7
  - `VCC`: J8, J9, K8, H10
  - `VSUP`: K4, I4

- First power-up through a current-limited supply; check the acceptance voltages from the verification report.
