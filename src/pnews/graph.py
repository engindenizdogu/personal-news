"""Build the heterogeneous item graph and report its statistics.

v0 (midterm): nodes are items, sources and entities; edges are
    (item, from, source)       every item -> the feed it came from
    (item, mentions, entity)   every validated entity of the item (data/enrichment/entities.jsonl)
plus the reverse of each (PyG ToUndirected: rev_from, rev_mentions) so messages flow both ways.
Topics (`about`) and similar-story edges come in v1.

Which items: those with an enrichment row, from sources still in config/feeds.yml.
Node features in v0: source = one-hot id, entity = one-hot type. Items have no features
yet (text embeddings come in week 1); their publish time is stored for the time split.
Ratings are never read here (no label leakage).

Outputs:
    data/graphs/graph_<version>.pt           PyG HeteroData (git-ignored, rebuildable)
    data/graphs/graph_<version>_nodes.json   node index -> id, per node type
    report/tables/graph_<version>_stats.json / .md
    report/figures/graph_<version>_degree.png    degree distributions
    report/figures/graph_<version>_network.png   items, sources and shared entities
    data/graphs/graph_<version>.gexf         for Gephi / Gephi Lite (all nodes, with attributes)

Usage:
    uv run python -m pnews.graph
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

import networkx as nx
import torch
import yaml
from torch_geometric.data import HeteroData
from torch_geometric.transforms import ToUndirected

from pnews.collect import load_feeds
from pnews.content import load_items
from pnews.enrich import ENTITY_TYPES

FROM = ("item", "from", "source")
MENTIONS = ("item", "mentions", "entity")


# ---------------------------------------------------------------- build


def load_entity_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def build_graph(items: list[dict], entity_rows: list[dict], feeds: list[dict], min_entity_items: int = 1) -> tuple[HeteroData, dict]:
    """Return (HeteroData with forward edges only, node tables). Deterministic for the same inputs."""
    feed_ids = [f["id"] for f in feeds]
    rows = {r["item_id"]: r for r in entity_rows}
    graph_items = [i for i in items if i["item_id"] in rows and i["source_id"] in feed_ids]
    graph_items.sort(key=lambda i: (i["published_at"] or "", i["item_id"]))  # time order

    # Entities: keep those mentioned by >= min_entity_items graph items.
    ent_info: dict[str, dict] = {}
    ent_items: dict[str, set] = defaultdict(set)
    for item in graph_items:
        for e in rows[item["item_id"]]["entities"]:
            ent_info.setdefault(e["entity_id"], {"id": e["entity_id"], "name": e["name"], "type": e["type"]})
            ent_items[e["entity_id"]].add(item["item_id"])
    kept_entities = sorted(eid for eid, its in ent_items.items() if len(its) >= min_entity_items)

    item_idx = {i["item_id"]: n for n, i in enumerate(graph_items)}
    source_idx = {sid: n for n, sid in enumerate(feed_ids)}
    entity_idx = {eid: n for n, eid in enumerate(kept_entities)}

    from_edges = [(item_idx[i["item_id"]], source_idx[i["source_id"]]) for i in graph_items]
    mention_edges = sorted({
        (item_idx[i["item_id"]], entity_idx[e["entity_id"]])
        for i in graph_items for e in rows[i["item_id"]]["entities"] if e["entity_id"] in entity_idx
    })

    data = HeteroData()
    data["item"].num_nodes = len(graph_items)
    data["item"].published_ts = torch.tensor(
        [datetime.fromisoformat(i["published_at"]).timestamp() if i["published_at"] else float("nan") for i in graph_items],
        dtype=torch.float64,
    )
    data["source"].x = torch.eye(len(feed_ids))
    data["entity"].x = torch.tensor(
        [[1.0 if ent_info[eid]["type"] == t else 0.0 for t in ENTITY_TYPES] for eid in kept_entities]
    ).reshape(len(kept_entities), len(ENTITY_TYPES))
    data[FROM].edge_index = _edge_index(from_edges)
    data[MENTIONS].edge_index = _edge_index(mention_edges)

    nodes = {
        "item": [{"id": i["item_id"], "source_id": i["source_id"], "title": i["title"], "url": i.get("url"),
                  "published_at": i["published_at"]} for i in graph_items],
        "source": [{"id": f["id"], "name": f["name"]} for f in feeds],
        "entity": [ent_info[eid] for eid in kept_entities],
        "entity_types": list(ENTITY_TYPES),
        "min_entity_items": min_entity_items,
    }
    return data, nodes


def _edge_index(pairs: list[tuple[int, int]]) -> torch.Tensor:
    if not pairs:
        return torch.empty((2, 0), dtype=torch.long)
    return torch.tensor(pairs, dtype=torch.long).t().contiguous()


# ---------------------------------------------------------------- statistics


def _summary(values: list[int]) -> dict:
    if not values:
        return {"min": 0, "median": 0, "mean": 0, "max": 0}
    return {"min": min(values), "median": statistics.median(values), "mean": round(statistics.mean(values), 2), "max": max(values)}


def compute_stats(data: HeteroData, nodes: dict) -> dict:
    items, entities = nodes["item"], nodes["entity"]
    src, dst = data[MENTIONS].edge_index.tolist() if data[MENTIONS].edge_index.numel() else ([], [])

    ent_deg = Counter(dst)                    # items per entity
    item_deg = Counter(src)                   # entities per item
    item_degrees = [item_deg.get(n, 0) for n in range(len(items))]
    ent_degrees = [ent_deg.get(n, 0) for n in range(len(entities))]
    ent_sources = defaultdict(set)
    for i, e in zip(src, dst):
        ent_sources[e].add(items[i]["source_id"])

    # Items linked through a shared entity (the structure a graph model can use beyond the source).
    items_of_entity = defaultdict(list)
    for i, e in zip(src, dst):
        items_of_entity[e].append(i)
    proj = nx.Graph()
    proj.add_nodes_from(range(len(items)))
    for its in items_of_entity.values():
        proj.add_edges_from(combinations(sorted(its), 2))
    cross = sum(1 for a, b in proj.edges if items[a]["source_id"] != items[b]["source_id"])
    comps = sorted((len(c) for c in nx.connected_components(proj)), reverse=True)

    # Whole graph, undirected, all node types.
    full = nx.Graph()
    full.add_nodes_from(("item", n) for n in range(len(items)))
    full.add_nodes_from(("source", n) for n in range(len(nodes["source"])))
    full.add_nodes_from(("entity", n) for n in range(len(entities)))
    fs, fd = data[FROM].edge_index.tolist() if data[FROM].edge_index.numel() else ([], [])
    full.add_edges_from((("item", a), ("source", b)) for a, b in zip(fs, fd))
    full.add_edges_from((("item", a), ("entity", b)) for a, b in zip(src, dst))

    per_source = Counter(i["source_id"] for i in items)
    return {
        "nodes": {"item": len(items), "source": len(nodes["source"]), "entity": len(entities), "total": full.number_of_nodes()},
        "edges": {"from": len(fs), "mentions": len(src), "total_undirected": full.number_of_edges()},
        "min_entity_items": nodes["min_entity_items"],
        "items_per_source": dict(sorted(per_source.items())),
        "entities_by_type": dict(Counter(e["type"] for e in entities)),
        "entity_degree": {
            **_summary(ent_degrees),
            "histogram": dict(sorted(Counter(ent_degrees).items())),
            "singletons": sum(1 for d in ent_degrees if d == 1),
            "multi_source": sum(1 for s in ent_sources.values() if len(s) > 1),
        },
        "item_degree": {**_summary(item_degrees), "items_without_entities": sum(1 for d in item_degrees if d == 0)},
        "item_links_via_entities": {
            "item_pairs": proj.number_of_edges(),
            "cross_source_pairs": cross,
            "items_with_a_link": sum(1 for n in proj.nodes if proj.degree(n) > 0),
            "components": len(comps),
            "largest_component": comps[0] if comps else 0,
        },
        "full_graph": {
            "connected_components": nx.number_connected_components(full),
            "density": round(nx.density(full), 5),
        },
        "top_entities": [
            {"name": entities[e]["name"], "type": entities[e]["type"], "items": d, "sources": len(ent_sources[e])}
            for e, d in sorted(ent_deg.items(), key=lambda kv: (-kv[1], entities[kv[0]]["id"]))[:15]
        ],
    }


def stats_markdown(stats: dict, version: str) -> str:
    n, e, ed, idg, lk = stats["nodes"], stats["edges"], stats["entity_degree"], stats["item_degree"], stats["item_links_via_entities"]
    lines = [
        f"# Graph {version}: statistics",
        "",
        f"Entities kept if mentioned by at least {stats['min_entity_items']} item(s).",
        "",
        "| Nodes | Count |", "|---|---|",
        f"| item | {n['item']} |", f"| source | {n['source']} |", f"| entity | {n['entity']} |", f"| **total** | **{n['total']}** |",
        "",
        "| Edges (one direction) | Count |", "|---|---|",
        f"| item → source (`from`) | {e['from']} |", f"| item → entity (`mentions`) | {e['mentions']} |",
        "",
        "| Entities by type | Count |", "|---|---|",
        *[f"| {t} | {c} |" for t, c in sorted(stats["entities_by_type"].items())],
        "",
        "| Degree | min | median | mean | max |", "|---|---|---|---|---|",
        f"| items per entity | {ed['min']} | {ed['median']} | {ed['mean']} | {ed['max']} |",
        f"| entities per item | {idg['min']} | {idg['median']} | {idg['mean']} | {idg['max']} |",
        "",
        f"- Entities mentioned by one item only: {ed['singletons']} of {n['entity']}"
        f" ({100 * ed['singletons'] / max(n['entity'], 1):.0f}%); entities seen in more than one source: {ed['multi_source']}",
        f"- Items without entities: {idg['items_without_entities']}",
        f"- Item pairs sharing at least one entity: {lk['item_pairs']} ({lk['cross_source_pairs']} across sources);"
        f" items with such a link: {lk['items_with_a_link']} of {n['item']}; largest linked group: {lk['largest_component']} items",
        f"- Whole graph: {stats['full_graph']['connected_components']} connected component(s), density {stats['full_graph']['density']}",
        "",
        "| Top entities | Type | Items | Sources |", "|---|---|---|---|",
        *[f"| {t['name']} | {t['type']} | {t['items']} | {t['sources']} |" for t in stats["top_entities"]],
        "",
        "| Items per source | Count |", "|---|---|",
        *[f"| {s} | {c} |" for s, c in stats["items_per_source"].items()],
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- figures

# Validated categorical slots 1-3 (dataviz reference palette, light mode). Node types also
# differ by marker shape, because slot 3 is below 3:1 contrast on the white surface.
COLORS = {"item": "#2a78d6", "source": "#eb6834", "entity": "#1baf7a"}
SHAPES = {"item": "o", "source": "s", "entity": "^"}
INK, INK_MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3df"


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_degrees(stats: dict, path: Path, version: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hist = {int(k): v for k, v in stats["entity_degree"]["histogram"].items()}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.8), facecolor="white")
    a1.bar(list(hist), list(hist.values()), width=0.8, color=COLORS["entity"], edgecolor="white", linewidth=2)
    a1.set_yscale("log")
    a1.set_xlabel("Items mentioning the entity", color=INK)
    a1.set_ylabel("Entities (log scale)", color=INK)
    a1.set_title("How many items each entity connects", color=INK, fontsize=11, loc="left")
    _style(a1)

    # Cap the x axis at CAP: one long contributor list (185 entities) would squash the rest.
    CAP = 60
    item_deg = stats["_item_degrees"]
    over = [d for d in item_deg if d >= CAP]
    a2.hist([min(d, CAP) for d in item_deg], bins=range(0, CAP + 6, 5), color=COLORS["item"], edgecolor="white", linewidth=2)
    a2.set_xticks(list(range(0, CAP, 10)) + [CAP])
    a2.set_xticklabels([str(t) for t in range(0, CAP, 10)] + [f"{CAP}+"])
    if over:
        a2.annotate(f"{len(over)} item(s) with {', '.join(map(str, sorted(over)))}", xy=(CAP + 2.5, 1), xytext=(CAP - 22, 5),
                    color=INK_MUTED, fontsize=8, arrowprops={"arrowstyle": "-", "color": INK_MUTED, "linewidth": 0.8})
    a2.set_xlabel("Entities per item", color=INK)
    a2.set_ylabel("Items", color=INK)
    a2.set_title("How many entities each item mentions", color=INK, fontsize=11, loc="left")
    _style(a2)

    fig.suptitle(f"Graph {version}: degree distributions", color=INK, fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_network(data: HeteroData, nodes: dict, path: Path, seed: int, version: str) -> None:
    """Items, sources, and entities shared by 2+ items (single-item entities are left out to keep it readable)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    src, dst = data[MENTIONS].edge_index.tolist() if data[MENTIONS].edge_index.numel() else ([], [])
    deg = Counter(dst)
    shared = {e for e, d in deg.items() if d >= 2}
    g = nx.Graph()
    fs, fd = data[FROM].edge_index.tolist()
    g.add_edges_from((("item", a), ("source", b)) for a, b in zip(fs, fd))
    g.add_edges_from((("item", a), ("entity", b)) for a, b in zip(src, dst) if b in shared)
    pos = nx.spring_layout(g, seed=seed, k=0.6, iterations=300)

    fig, ax = plt.subplots(figsize=(11, 8.5), facecolor="white")
    nx.draw_networkx_edges(g, pos, ax=ax, edge_color=GRID, width=0.8)
    for kind in ("entity", "item", "source"):
        nl = [n for n in g.nodes if n[0] == kind]
        size = {"item": 40, "source": 220, "entity": [30 + 25 * deg[n[1]] for n in nl]}[kind]
        nx.draw_networkx_nodes(g, pos, nodelist=nl, ax=ax, node_color=COLORS[kind], node_shape=SHAPES[kind],
                               node_size=size, edgecolors="white", linewidths=1.0)
    # Source labels below their node (bold), entity labels above, so the two don't collide.
    ys = [p[1] for p in pos.values()]
    dy = 0.025 * (max(ys) - min(ys) or 1)
    for n, s in enumerate(nodes["source"]):
        if ("source", n) in g:
            x, y = pos[("source", n)]
            ax.text(x, y - 1.6 * dy, s["id"], ha="center", va="top", fontsize=8, fontweight="bold", color=INK)
    for e, d in deg.items():
        if d >= 4:
            x, y = pos[("entity", e)]
            ax.text(x, y + dy, nodes["entity"][e]["name"], ha="center", va="bottom", fontsize=7.5, color=INK_MUTED)

    legend = [Line2D([0], [0], marker=SHAPES[k], color="white", markerfacecolor=COLORS[k], markersize=9, label=lbl)
              for k, lbl in [("item", "item"), ("source", "source (feed)"), ("entity", "entity shared by 2+ items")]]
    ax.legend(handles=legend, loc="lower left", frameon=False, fontsize=9, labelcolor=INK)
    st = Counter(n[0] for n in g.nodes)
    ax.set_title(f"Graph {version}: {st['item']} items, {st['source']} sources, {st['entity']} shared entities"
                 f" (entities in only one item not shown; labels on entities in 4+ items)",
                 color=INK, fontsize=10, loc="left")
    ax.axis("off")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


# ---------------------------------------------------------------- export


def _hex_to_viz(hex_color: str) -> dict:
    h = hex_color.lstrip("#")
    return {"r": int(h[0:2], 16), "g": int(h[2:4], 16), "b": int(h[4:6], 16), "a": 1.0}


def to_networkx(data: HeteroData, nodes: dict, seed: int) -> nx.Graph:
    """Undirected networkx graph with every node and edge, labels and attributes for browsing.

    Node ids: "item:<item_id>", "source:<id>", "entity:<entity_id>". Attributes (all strings or
    ints, as GEXF needs): node_type, label, source_id, entity_type, published_at, url, degree.
    Gephi styling: color by node type, size by degree, starting positions from a seeded layout."""
    g = nx.Graph()
    for i in nodes["item"]:
        g.add_node(f"item:{i['id']}", label=i["title"], node_type="item", source_id=i["source_id"],
                   entity_type="", published_at=i["published_at"] or "", url=i.get("url") or "")
    for s in nodes["source"]:
        g.add_node(f"source:{s['id']}", label=s["name"], node_type="source", source_id=s["id"],
                   entity_type="", published_at="", url="")
    for e in nodes["entity"]:
        g.add_node(f"entity:{e['id']}", label=e["name"], node_type="entity", source_id="",
                   entity_type=e["type"], published_at="", url="")
    items, sources, ents = nodes["item"], nodes["source"], nodes["entity"]
    for a, b in zip(*data[FROM].edge_index.tolist()):
        g.add_edge(f"item:{items[a]['id']}", f"source:{sources[b]['id']}", relation="from")
    for a, b in zip(*data[MENTIONS].edge_index.tolist()):
        g.add_edge(f"item:{items[a]['id']}", f"entity:{ents[b]['id']}", relation="mentions")

    pos = nx.spring_layout(g, seed=seed, k=0.6 / max(len(g), 1) ** 0.5 * 6, iterations=300) if len(g) else {}
    for n, attrs in g.nodes(data=True):
        deg = g.degree(n)
        attrs["degree"] = deg
        size = {"item": 6.0, "source": 20.0}.get(attrs["node_type"], 3.0 + 3.0 * deg)
        x, y = pos.get(n, (0.0, 0.0))
        attrs["viz"] = {"color": _hex_to_viz(COLORS[attrs["node_type"]]), "size": size,
                        "position": {"x": float(x) * 1000, "y": float(y) * 1000, "z": 0.0}}
    return g


def export_gexf(data: HeteroData, nodes: dict, path: Path, seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(to_networkx(data, nodes, seed), path)


# ---------------------------------------------------------------- run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, default=Path("config/graph.yml"))
    ap.add_argument("--feeds", type=Path, default=Path("config/feeds.yml"))
    ap.add_argument("--items", type=Path, default=Path("data/items.jsonl"))
    ap.add_argument("--entities", type=Path, default=Path("data/enrichment/entities.jsonl"))
    ap.add_argument("--out-dir", type=Path, default=Path("data/graphs"))
    ap.add_argument("--report-dir", type=Path, default=Path("report"))
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    version = cfg["version"]
    data, nodes = build_graph(load_items(args.items), load_entity_rows(args.entities), load_feeds(args.feeds),
                              cfg.get("min_entity_items", 1))
    stats = compute_stats(data, nodes)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(ToUndirected()(data), args.out_dir / f"graph_{version}.pt")
    (args.out_dir / f"graph_{version}_nodes.json").write_text(json.dumps(nodes, ensure_ascii=False, indent=1), encoding="utf-8")

    tables = args.report_dir / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    (tables / f"graph_{version}_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    (tables / f"graph_{version}_stats.md").write_text(stats_markdown(stats, version), encoding="utf-8")

    src = data[MENTIONS].edge_index[0].tolist() if data[MENTIONS].edge_index.numel() else []
    item_deg = Counter(src)
    plot_degrees({**stats, "_item_degrees": [item_deg.get(n, 0) for n in range(stats["nodes"]["item"])]},
                 args.report_dir / "figures" / f"graph_{version}_degree.png", version)
    plot_network(data, nodes, args.report_dir / "figures" / f"graph_{version}_network.png", cfg["seed"], version)
    export_gexf(data, nodes, args.out_dir / f"graph_{version}.gexf", cfg["seed"])

    print(stats_markdown(stats, version))
    print(f"saved {args.out_dir / f'graph_{version}.pt'}, {args.out_dir / f'graph_{version}.gexf'}"
          f" and figures/tables under {args.report_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
