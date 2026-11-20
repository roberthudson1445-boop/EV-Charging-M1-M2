EV CHARGING NETWORK – INTERACTIVE MAP
=====================================

IMPORTANT – HOW TO OPEN THE MAP
--------------------------------
Do not double-click the HTML file directly. That opens a file:// URL, and modern browsers do not send the HTTP Referer required by the standard OpenStreetMap tile service. This causes the 403 / “Access blocked” tile message.

1. Extract all files in this ZIP into one folder.
2. Double-click Open_Map.bat.
3. A minimized Command Prompt window named “EV Charging Map Server” will run a small local Python HTTP server.
4. Your browser will open http://127.0.0.1:8765/EV_Charging_M1_M2_Interactive_Map.html.
5. Keep the minimized server window open while using the map. Close it when you finish.

Python 3 must be installed and available as “py -3” or “python”.
An internet connection is required to load the OpenStreetMap background tiles and the Leaflet library.

MAP CONTROLS
------------
- Choose Low, Base, High, or Armstat.
- Click a charging-site marker to inspect its ID, corridor, chainage, charger count, installed power, and assigned demand.
- Toggle the three demand-reference locations.
- Toggle selected sites with zero assigned demand.

DATA AND LIMITATIONS
--------------------
- Selected-site coordinates and results are embedded from the project's final directed-network scenario outputs.
- Demand represents three documented scopes only, not all traffic along M1/M2.
- The markers show optimized candidate locations, not approved or operating public charging stations.
- Land, legal access, electricity connection, and local construction costs remain unverified.
- OpenStreetMap attribution is displayed on the map. Normal interactive viewing only is intended; do not bulk-download or prefetch map tiles.
