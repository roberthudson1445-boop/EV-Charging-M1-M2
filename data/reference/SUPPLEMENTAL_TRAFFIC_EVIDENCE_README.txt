SUPPLEMENTAL ARMENIA TRAFFIC EVIDENCE
===================================

Files created by add_supplemental_traffic_evidence.py

1) adb_traffic_counts_point_reference_2005_2007.csv
   Point counter records on M1/M2 from ADB's 2008 Armenia Transport Sector
   Development Strategy, Table 4-2 (traffic volumes for 2005-2007). Includes
   M2 km200.320 and km367.250, which broaden historical geographic coverage.
   These observations are old and must not be treated as 2026 traffic.

2) adb_traffic_vehicle_class_reference.csv
   Vehicle-class detail from the ADB North-South Tranche 1 Completion Report:
   2009 M2 km16 count and 2012 base-year section traffic for M1 Section 3 and
   the two M2 subsections. Section totals are not exact point-counter records.

3) traffic_network_context_not_point_demand.csv
   Context-only sources with no exact station chainage. ADB reports about
   2,500 AADT in 2022 on the Sisian-Tatev-Kapan route used for traffic to/from
   southern Armenia and the Iran border. UNDP's 2024 assessment summarizes
   national interstate AADT context. Neither row is added to the MILP demand
   matrix because a precise count location / compatible vehicle split is not
   documented in the source summary.

IMPORTANT MODELLING RULES
-------------------------
- The new reference files are supplemental evidence only. They do not change
  traffic_counts_historic.csv, generated demand scenarios, distance matrices,
  or any existing MILP results.
- Do not append old 2005-2007 counts to the recent counter series and blindly
  extrapolate them to 2026. M2's route alignment and operating context changed.
- Do not map route-level AADT to a fabricated exact chainage.
- The current demand model still represents three specific locations /
  subsections, not the full M1/M2 corridor demand.

SOURCES
------
ADB Armenia Transport Sector Development Strategy (November 2008), Table 4-2:
https://collaboration.worldbank.org/content/usergenerated/asi/cloud/attachments/sites/collaboration-for-development/en/groups/eastern-partnership-transport-panel/documents/jcr%3Acontent/content/primary/blog/2009-2020_-_armenia-0mSW/2009-2020%20-%20Armenia%2C%20Transport%20Sector%20Development%20Strategy%20%28ADB%29.pdf

ADB North-South Road Corridor Investment Program Tranche 1 Completion Report
(January 2020), Appendix 9 Tables 3-5:
https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf

ADB Resilient and Inclusive Road Sector Improvement Project (56317-001):
https://www.adb.org/projects/56317-001/main

UNDP / Government of Armenia / EU, Armenia Floods May 2024 PDNA (October 2024),
transport section:
https://www.undp.org/sites/g/files/zskgke326/files/2024-11/pdna_armenia_eng_final.pdf
