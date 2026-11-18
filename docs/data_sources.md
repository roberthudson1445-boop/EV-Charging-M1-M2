# Initial data-source register for the Armenia M1/M2 case study

This register distinguishes available reference evidence from inputs that are
still missing. Do not treat national totals or historical counts as current,
site-specific measurements.

## Road corridors and geometry

1. **Armenia main-road network (OpenStreetMap-derived dataset)**
   - Dataset page: https://data.amerigeoss.org/en/dataset/armenia-road-network-main-roads
   - The dataset page describes a main-road network layer and offers WMS,
     KML, and zipped-shapefile resources. It identifies the OpenStreetMap
     Open Database License (ODbL) and attribution requirements.
   - Use for initial road-network geometry, but verify the M1/M2 alignment,
     road class, route tags, and current construction/realignment before use.
2. **OpenStreetMap route tags**
   - Example M1 way with `ref:en=M-1`:
     https://www.openstreetmap.org/way/1172630454
   - Example M2 way with `ref:en=M-2`:
     https://www.openstreetmap.org/way/84638548
   - OSM is volunteered geographic information; preserve attribution and
     record the extraction date and query in the project metadata.

## Traffic counts and demand

1. **Asian Development Bank, North-South Road Corridor Investment Program –
   Tranche 1 Completion Report (January 2020)**
   - https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf
   - Appendix 9 records automatic traffic counters at M1 km 20.7 and M2
     km 9.38. Its table reports historical classified counts through 2017
     for the M1 station and 2018 for the M2 station. These are historic
     observations, not current 2026 traffic counts; the report also explains
     that the M2 km 9.38 counter is representative only of the section near
     Yerevan and that traffic declines farther from Yerevan.
2. **Road Department counter-network reporting (19 December 2025)**
   - News report relaying information from the Road Department Foundation: https://www.auroranews.am/news/2025-12-19-mijpetakan-chanaparhnerin-transporti-intensivutyuny-chapogh-hashvichner-en-teghadrvel
   - Reports 14 online traffic counters across eight interstate roads, including two counter locations on M-1 and four on M-2. It describes classified average-daily traffic recording (light vehicles, trucks, and truck-trailers), but does not publish counter chainages or the numerical station-level time series. It is evidence that a counter network exists, not a usable traffic-count dataset. The current raw counts must be requested from the Road Department or another verifiable source.
3. **UNDP, Armenia Post-Disaster Needs Assessment (2024)**
   - https://www.undp.org/sites/g/files/zskgke326/files/2024-11/pdna_armenia_eng_final.pdf
   - Reports that traffic intensity on interstate roads is counted yearly,
     while counts on republican roads are irregular and local-road counts
     are scarce; it gives examples for M4 and M6, not direct M1/M2 segment
     counts. Use as context for data limitations, not as M1/M2 demand values.
4. **IEA, Sustainable Transport Policy for Armenia: A Roadmap**
   - https://www.iea.org/reports/sustainable-transport-policy-for-armenia-a-roadmap/sustainable-transport-in-armenia
   - Reports 36,000 EV imports in 2019–2024 and 9,528 in 2024. Imports are
     vehicle inflows, not the active EV fleet or daily EV traffic on M1/M2;
     do not insert these numbers directly as segment demand.

## Existing public charging infrastructure

1. **EVUP public charging network map and station directory**
   - https://evup.app/map
   - The operator's public directory lists 12 EVUP locations and 50 connectors in Armenia; the directory snapshot used for this repository was marked as last verified on 2026-10-25.
   - A CSV snapshot of the 12 published locations is stored in `data/reference/evup_public_stations_snapshot_2026-11-18.csv`. It records station codes, addresses, published connector descriptions, and the highest published connector power.
   - These entries are an inventory reference only. The published connector count or connector power is **not** the available grid capacity, guaranteed simultaneous station output, utilisation, or daily energy throughput. Do not sum connector ratings to infer transformer capacity. Coordinates and exact road-network proximity still require geocoding and route-distance verification.
   - The inventory is not automatically subtracted from the optimisation demand or treated as candidate-site electrical data in the current MILP. A future model version can explicitly represent existing stations and residual uncovered demand if suitable capacity/session data become available.

## Electrical-network constraints

1. **Electric Networks of Armenia (ENA), Technical Information**
   - https://www.ena.am/AboutUs.aspx?id=3&lang=2
   - The page reports nationwide counts and aggregate capacities for
     110 kV and 35 kV substations. It does not provide a complete
     site-by-site available-capacity table for candidate M1/M2 locations.
   - Specific available capacity, connection voltage, transformer loading,
     and connection cost at candidate sites remain to be obtained from ENA
     or a verifiable engineering source. Do not allocate the national
     aggregate capacity to individual candidate stations.

## Indicative electrical-network mapping (not capacity data)

1. **World Bank Group, Armenia - Electricity Transmission Substations (2011)**
   - Data catalog: https://datacatalog.worldbank.org/search/dataset/0039829/armenia-electricity-transmission-network
   - The related Open Data Armenia record describes the point layer as digitized from a PDF map and explicitly warns that it represents rough schematic locations and is not suitable for high-accuracy applications: https://data.opendata.am/dataset/armenia-electricity-transmission-substations-2011
   - This layer may help with broad map context only. It does not provide a verified site name, voltage, available capacity, loading, or connection cost for each point. It is not used as the MILP grid-capacity input.

## Required remaining data

- Recent AADT/classified counts along M1 and M2, ideally by direction and
  segment, with observation year and count-station chainage.
- EV share of the relevant traffic, charging probability on each segment,
  and average kWh delivered per charging visit. Until measured data are
  obtained, these must be explicitly labelled scenario assumptions.
- Candidate station coordinates and road-network distances to each demand
  point.
- Site-specific grid connection capacity in active kW (or source kVA plus
  documented power factor), and connection-cost estimates.
- Construction, land, transformer, charger, and operating-cost basis with
  currency and price year.

The loader expects a fully populated `data/raw/` directory. It intentionally
rejects missing site-demand distance pairs and missing numeric values rather
than silently replacing them with invented data.
