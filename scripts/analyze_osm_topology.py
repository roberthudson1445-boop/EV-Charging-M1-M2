
"""Analyze M1/M2 connectivity using original OpenStreetMap node IDs."""

from pathlib import Path

import networkx as nx
from pyrosm import OSM

PBF = Path("data/raw/armenia-latest.osm.pbf")

M1_TAGS = {"M-1", "Մ-1", "М-1"}
M2_TAGS = {"M-2", "Մ-2", "М-2"}


def tokens(value):
    if value is None:
        return set()

    return {
        item.strip().upper()
        for item in str(value).replace(",", ";").split(";")
        if item.strip()
    }


def route_label(row):
    ref = tokens(row.get("ref"))
    ref_en = tokens(row.get("ref:en"))

    local_routes = set()

    if ref & M1_TAGS:
        local_routes.add("M1")
    if ref & M2_TAGS:
        local_routes.add("M2")

    english_routes = set()

    if "M-1" in ref_en:
        english_routes.add("M1")
    if "M-2" in ref_en:
        english_routes.add("M2")

    combined = local_routes | english_routes

    if len(combined) == 1:
        return next(iter(combined))

    if len(combined) > 1:
        return "CONFLICT"

    return None


def point_description(node_id, node_lookup):
    row = node_lookup.get(node_id)

    if row is None:
        return f"node={node_id}"

    return (
        f"node={node_id}, "
        f"lon={float(row['lon']):.6f}, "
        f"lat={float(row['lat']):.6f}"
    )


def main():
    if not PBF.exists():
        raise FileNotFoundError(PBF)

    print("Reading the full driving network from the local PBF...")

    osm = OSM(str(PBF))

    nodes, edges = osm.get_network(
        network_type="driving",
        nodes=True,
        extra_attributes=["ref", "ref:en", "name"],
    )

    print("\nFull driving network")
    print("Nodes:", len(nodes))
    print("Road segments:", len(edges))
    print("Edge columns:", list(edges.columns))

    required = {"u", "v", "length", "ref", "highway"}
    missing = required - set(edges.columns)

    if missing:
        raise ValueError(
            f"Pyrosm output is missing required columns: {sorted(missing)}"
        )

    node_lookup = nodes.set_index("id").to_dict("index")

    edges = edges.copy()
    edges["route_label"] = edges.apply(route_label, axis=1)

    print("\nRoute classification")
    print(edges["route_label"].value_counts(dropna=False).to_string())

    conflicts = edges[edges["route_label"] == "CONFLICT"]
    print("\nConflicting M1/M2 tags:", len(conflicts))

    for route_id in ("M1", "M2"):
        selected = edges[edges["route_label"] == route_id]
        graph = nx.MultiGraph()

        for row in selected.itertuples():
            graph.add_edge(
                row.u,
                row.v,
                length_km=float(row.length) / 1000.0,
            )

        components = []

        for component_nodes in nx.connected_components(graph):
            subgraph = graph.subgraph(component_nodes)

            length = sum(
                data["length_km"]
                for _, _, data in subgraph.edges(data=True)
            )

            endpoints = [
                node
                for node, degree in subgraph.degree()
                if degree == 1
            ]

            components.append(
                (length, subgraph.number_of_edges(),
                 len(component_nodes), endpoints)
            )

        components.sort(key=lambda item: item[0], reverse=True)

        total_length = sum(item[0] for item in components)

        print("\n" + "=" * 60)
        print(f"{route_id} — OSM NODE-ID CONNECTIVITY")
        print("=" * 60)

        print("Tagged road segments:", len(selected))
        print("Graph nodes:", graph.number_of_nodes())
        print("Graph edges:", graph.number_of_edges())
        print("Connected components:", len(components))
        print(f"Total tagged length: {total_length:.2f} km")

        if components and total_length > 0:
            share = 100 * components[0][0] / total_length
            print(f"Largest component share: {share:.2f}%")

        print("\nLargest components:")

        for index, (length, edge_count, node_count, endpoints) in enumerate(
            components[:12], start=1
        ):
            print(
                f"{index:2}. edges={edge_count:5}, "
                f"nodes={node_count:5}, "
                f"endpoints={len(endpoints):4}, "
                f"length={length:8.2f} km"
            )

            for endpoint in endpoints[:4]:
                print("    ", point_description(endpoint, node_lookup))


if __name__ == "__main__":
    main()
