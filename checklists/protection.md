# Protection checklist for hand-built perfboard circuits

Apply what is relevant to the circuit and the spec's `protection` list. Every item
that is added must still pass the original acceptance criteria and derating checks.

## Power input
- [ ] **Reverse polarity** — series diode (1N4007; 1N5819 Schottky when headroom is
      tight) between the input connector and everything else. Polarised capacitors
      must sit *after* the diode, otherwise they see reverse voltage.
- [ ] **Overcurrent** — resettable PTC fuse (PTC_RXEF0xx) in series with the input,
      hold current above the normal input current / derating factor.
- [ ] **Overvoltage / transients** — TVS or Zener clamp to ground *after* a series
      element that limits the clamp current (PTC or resistor); check its power rating.
- [ ] **Bulk capacitance** — an electrolytic (10–100 µF) after the protection diode
      to ride through supply wiring inductance and load steps.

## Integrated circuits
- [ ] 100 nF ceramic decoupling capacitor per IC supply pin (plus whatever the
      parts DB requires, e.g. LDO output capacitors for stability).
- [ ] Reset / enable pins tied to a defined level (pull-up/pull-down), never floating.
- [ ] Unused op-amp sections configured as grounded followers.
- [ ] Control pins with filter capacitors where the datasheet recommends them
      (e.g. NE555 CTRL: 10 nF to ground).

## Signal inputs and outputs
- [ ] **Input protection** — series resistor (1–10 kΩ) on every external signal input
      to limit current into IC input structures; optionally clamp diodes to the rails.
- [ ] **ESD** — TVS/Zener from exposed connector pins to ground.
- [ ] Defined idle level on inputs that can be left open (pull-down/pull-up 10–100 kΩ).
- [ ] Output current limits — series resistor on outputs that drive cables/LEDs.

## Thermal and assembly
- [ ] Regulator dissipation (Vin_max − Vout) × Iout within the derated power rating.
- [ ] Prefer fewer, larger-margin parts over many marginal ones; every extra part is a
      hand-soldered joint.
