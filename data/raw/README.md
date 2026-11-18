# Case-study input data

Place the documented case-study files in this folder:

- `sites.csv`
- `demand_points.csv`
- `distances.csv`
- `config.json`

Templates are in `data/templates/`. Copy them here and fill them only with
verified values. Optional `latitude`, `longitude`, `source`, and `notes`
columns are preserved for mapping and provenance, although the optimization
loader currently reads the required numeric fields only.

Do not put synthetic example values here and label them as Armenian field data.

Unit requirements:
- `demand_kwh_day`: kWh/day
- `distance_km`: km by road/detour, not straight-line distance unless clearly stated
- `grid_capacity_kw`: active power in kW (convert source kVA values using a documented power factor)
- `charger_daily_capacity_kwh`: kWh/plug/day
- `charger_peak_power_kw`: kW/plug
- all cost fields and the budget must use the same currency and price basis
