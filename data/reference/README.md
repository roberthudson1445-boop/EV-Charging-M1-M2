# Reference datasets

## Historic traffic counts

`traffic_counts_historic.csv` contains historical classified traffic-count observations reported in the Asian Development Bank North-South Road Corridor Tranche 1 Completion Report. The latest observations recorded for the two counters are M1 km 20.7 (2017) and M2 km 9.38 (2018). These are not current 2026 traffic counts and must not be treated as the traffic volume for every segment of either route.

## EVUP public charging inventory

`evup_public_stations_snapshot_2026-11-18.csv` captures the 12 public EVUP locations listed on the operator's public station directory. The directory reported that the data were last verified on 2026-10-25. The CSV preserves operator-listed connector descriptions and a highest published connector power. It does not infer simultaneous station output, grid capacity, actual utilisation, or daily energy throughput. The entries are a reference inventory only and are not yet integrated as existing capacity in the MILP. Verify addresses, coordinates, road distance, and current station status before using them in a final case study.

Source: https://evup.app/map
