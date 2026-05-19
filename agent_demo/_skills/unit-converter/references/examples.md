# Unit Converter — Examples

## Mapping user phrasings to `convert_units` arguments

| User says                     | `value` | `from_unit`    | `to_unit`   |
|-------------------------------|---------|----------------|-------------|
| "Convert 100 km to miles"     | `100`   | `"km"`         | `"miles"`   |
| "98.6°F in Celsius"           | `98.6`  | `"fahrenheit"` | `"celsius"` |
| "5 kg to pounds"              | `5`     | `"kg"`         | `"lbs"`     |
| "How many MB is 1.5 TB?"      | `1.5`   | `"tb"`         | `"mb"`      |
| "60 mph in km/h"              | `60`    | `"mph"`        | `"km/h"`    |
| "3 cups of milk in ml"        | `3`     | `"cups"`       | `"ml"`      |
| "5 acres to hectares"         | `5`     | `"acres"`      | `"ha"`      |
| "Convert 0 Kelvin to Celsius" | `0`     | `"kelvin"`     | `"celsius"` |
| "1 atm in psi"                | `1`     | `"atm"`        | `"psi"`     |
| "How many seconds in a year?" | `1`     | `"years"`      | `"seconds"` |

Parsing cues:

- `to`, `in`, `into`, and `as` all signal the target unit.
- Plurals, common abbreviations and symbols are accepted (`feet` / `foot` / `ft`; `pounds` / `pound` / `lbs` / `lb`).
- Temperature words (`celsius`, `fahrenheit`, `kelvin`, …) are recognized whether or not the `°` symbol appears.
- Compound symbols use a slash, not a Unicode division sign (`km/h`, not `km∕h`); squared/cubed area or volume units use ASCII digits (`m2`, `km2`, `ft2`, `m3`), not `²`/`³`.

## Example return values

```python
>>> convert_units(100, "km", "miles")
(62.13711922373339, 'length')

>>> convert_units(98.6, "fahrenheit", "celsius")
(37.0, 'temperature')

>>> convert_units(1.5, "tb", "mb")
(1572864.0, 'data')

>>> convert_units(5673893, "sec", "days")
(65.67005787037037, 'time')
```

## Accepted unit aliases per category

Every alias on a row is interchangeable as `from_unit` or `to_unit` (case-insensitive). Use these strings — not the human-readable forms — when calling `convert_units`.

### length
`km`, `kilometers`, `kilometer` · `m`, `meters`, `meter` · `cm`, `centimeters`, `centimeter` · `mm`, `millimeters`, `millimeter` · `miles`, `mile`, `mi` · `yards`, `yard`, `yd` · `feet`, `foot`, `ft` · `inches`, `inch`, `in` · `nautical_miles`, `nautical_mile`, `nm`

### weight
`kg`, `kilograms`, `kilogram` · `g`, `grams`, `gram` · `mg`, `milligrams`, `milligram` · `t`, `tonnes`, `tonne`, `metric_tons` · `lbs`, `lb`, `pounds`, `pound` · `oz`, `ounces`, `ounce` · `stone`, `stones`, `st` · `short_tons`, `short_ton`

### temperature
`celsius`, `c` · `fahrenheit`, `f` · `kelvin`, `k` · `rankine`, `r` · `delisle`, `de` · `newton`, `n` · `reaumur`, `re` · `romer`, `ro`

### volume
`l`, `liters`, `liter`, `litres`, `litre` · `ml`, `milliliters`, `milliliter` · `cl`, `centiliters` · `m3`, `cubic_meters` · `cm3`, `cubic_centimeters` · `gallons`, `gallon`, `gal` · `quarts`, `quart`, `qt` · `pints`, `pint`, `pt` · `cups`, `cup` · `fl_oz`, `fluid_ounces`, `fluid_ounce` · `tbsp`, `tablespoons`, `tablespoon` · `tsp`, `teaspoons`, `teaspoon` · `imperial_gallons`, `imperial_gallon`

### area
`m2`, `square_meters`, `square_meter` · `km2`, `square_kilometers` · `cm2`, `square_centimeters` · `ha`, `hectares`, `hectare` · `ft2`, `square_feet`, `square_foot` · `in2`, `square_inches` · `yd2`, `square_yards` · `acres`, `acre` · `mi2`, `square_miles`

### speed
`m/s`, `meters_per_second` · `km/h`, `kmh`, `kph`, `kilometers_per_hour` · `mph`, `miles_per_hour` · `knots`, `knot`, `kt` · `ft/s`, `feet_per_second`

### time
`s`, `seconds`, `second`, `sec` · `ms`, `milliseconds`, `millisecond` · `min`, `minutes`, `minute` · `h`, `hours`, `hour`, `hr` · `days`, `day`, `d` · `weeks`, `week`, `w` · `months`, `month` · `years`, `year`, `yr`

### data
`b`, `bytes`, `byte` · `kb`, `kilobytes`, `kilobyte` · `mb`, `megabytes`, `megabyte` · `gb`, `gigabytes`, `gigabyte` · `tb`, `terabytes`, `terabyte` · `pb`, `petabytes`, `petabyte` · `bits`, `bit` · `kbits`, `kilobits`, `kilobit` · `mbits`, `megabits` · `gbits`, `gigabits`

### pressure
`pa`, `pascal`, `pascals` · `kpa`, `kilopascal`, `kilopascals` · `mpa`, `megapascal` · `bar`, `bars` · `mbar`, `millibar`, `millibars` · `atm`, `atmospheres`, `atmosphere` · `psi`, `pounds_per_square_inch` · `mmhg`, `torr` · `inhg`, `inches_of_mercury`

### energy
`j`, `joules`, `joule` · `kj`, `kilojoules`, `kilojoule` · `cal`, `calories`, `calorie` · `kcal`, `kilocalories`, `kilocalorie` · `wh`, `watt_hours`, `watt_hour` · `kwh`, `kilowatt_hours`, `kilowatt_hour` · `btu`, `btus` · `ev`, `electronvolts`, `electronvolt`

## Error examples

```python
>>> convert_units(5, "kg", "meters")
ValueError: Cannot convert between 'kg' (weight) and 'meters' (length)

>>> convert_units(10, "stone_cold", "kg")
ValueError: Unknown unit: 'stone_cold'
```
