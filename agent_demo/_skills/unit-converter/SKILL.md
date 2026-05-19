---
name: unit-converter
description: >
  Converts values between units of measurement across categories: length (km, miles,
  feet, inches), weight (kg, lbs, oz, stone), temperature (Celsius, Fahrenheit, Kelvin),
  volume (liters, gallons, cups, ml), area (m², acres, ft²), speed (km/h, mph, knots),
  time (seconds to years), data storage (bytes to petabytes), pressure, and energy.
  Use when the user asks to convert, calculate, or express a measurement in different units.
license: Apache-2.0
metadata:
  author: ai-powered-apps-development-expert
  version: "1.0"
allowed-tools: execute_code
---

# Unit Converter

Converts a numeric value from one unit to another within the same physical category and returns the converted value along with the detected category.

## Supported categories and units

- **Length** — km, miles, feet, inches (plus meters, centimeters, millimeters, yards)
- **Weight** — kg, lbs, oz, stone (plus grams, milligrams, tonnes)
- **Temperature** — Celsius, Fahrenheit, Kelvin
- **Volume** — liters, gallons, cups, ml (plus pints, quarts, fluid ounces)
- **Area** — m², acres, ft² (plus km², hectares, square miles)
- **Speed** — km/h, mph, knots (plus m/s, ft/s)
- **Time** — seconds, minutes, hours, days, weeks, months, years
- **Data storage** — bytes, KB, MB, GB, TB, PB
- **Pressure** — Pa, kPa, bar, psi, atm
- **Energy** — joules, kilojoules, calories, kilocalories, kWh

The full unit list per category and the conversion factors live in [unit-converter/scripts/convert.py](scripts/convert.py).

## Resources

- [examples.md](unit-converter/examples.md) — sample inputs and expected outputs covering each category.
- [scripts/convert.py](unit-converter/scripts/convert.py) — the `convert_units(value, from_unit, to_unit)` implementation and the `fmt` helper used to format results.
- [references/how-code-execution-works.md](unit-converter/references/how-code-execution-works.md) — how the `execute_code` tool runs the script, manages sessions, and combines `script_path` with `code`.
