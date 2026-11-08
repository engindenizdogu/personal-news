"""Tests for pnews.graph on a small hand-made dataset."""

import torch

from pnews import graph

FEEDS = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "gone", "name": "Unused"}]
ITEMS = [
    {"item_id": "i2", "source_id": "a", "title": "Two", "published_at": "2026-02-01T00:00:00+00:00"},
    {"item_id": "i1", "source_id": "a", "title": "One", "published_at": "2026-01-01T00:00:00+00:00"},
    {"item_id": "i3", "source_id": "b", "title": "Three", "published_at": "2026-03-01T00:00:00+00:00"},
    {"item_id": "i4", "source_id": "b", "title": "Not enriched", "published_at": "2026-03-02T00:00:00+00:00"},
    {"item_id": "i5", "source_id": "removed", "title": "Old feed", "published_at": "2026-03-03T00:00:00+00:00"},
]


def ent(eid, etype="organization"):
    return {"entity_id": eid, "name": eid.split(":")[1].title(), "type": etype, "mention": "x"}


ROWS = [
    {"item_id": "i1", "entities": [ent("organization:openai"), ent("person:ann", "person")]},
    {"item_id": "i2", "entities": [ent("organization:openai")]},
    {"item_id": "i3", "entities": [ent("organization:openai"), ent("location:us", "location")]},
    {"item_id": "i5", "entities": [ent("organization:openai")]},
]


def test_build_graph_nodes_edges_and_order():
    data, nodes = graph.build_graph(ITEMS, ROWS, FEEDS)
    assert [i["id"] for i in nodes["item"]] == ["i1", "i2", "i3"]  # enriched, configured, time-ordered
    assert data["item"].num_nodes == 3 and data["source"].num_nodes == 3
    assert [e["id"] for e in nodes["entity"]] == ["location:us", "organization:openai", "person:ann"]
    assert data[graph.FROM].edge_index.tolist() == [[0, 1, 2], [0, 0, 1]]
    assert data[graph.MENTIONS].edge_index.size(1) == 5
    assert data["entity"].x.tolist()[1] == [1.0, 0.0, 0.0, 0.0]  # organization one-hot
    assert data["item"].published_ts[0] < data["item"].published_ts[2]


def test_min_entity_items_drops_single_item_entities():
    data, nodes = graph.build_graph(ITEMS, ROWS, FEEDS, min_entity_items=2)
    assert [e["id"] for e in nodes["entity"]] == ["organization:openai"]
    assert data[graph.MENTIONS].edge_index.size(1) == 3


def test_stats():
    data, nodes = graph.build_graph(ITEMS, ROWS, FEEDS)
    s = graph.compute_stats(data, nodes)
    assert s["nodes"] == {"item": 3, "source": 3, "entity": 3, "total": 9}
    assert s["edges"]["from"] == 3 and s["edges"]["mentions"] == 5
    assert s["entity_degree"]["singletons"] == 2 and s["entity_degree"]["multi_source"] == 1
    assert s["item_links_via_entities"]["item_pairs"] == 3  # all three share OpenAI
    assert s["item_links_via_entities"]["cross_source_pairs"] == 2
    assert s["full_graph"]["connected_components"] == 2  # the unused source node is isolated
    assert s["top_entities"][0] == {"name": "Openai", "type": "organization", "items": 3, "sources": 2}


def test_reverse_edges_added_for_saving():
    from torch_geometric.transforms import ToUndirected

    data, _ = graph.build_graph(ITEMS, ROWS, FEEDS)
    und = ToUndirected()(data)
    assert ("entity", "rev_mentions", "item") in und.edge_types
    assert torch.equal(und["entity", "rev_mentions", "item"].edge_index, data[graph.MENTIONS].edge_index.flip(0))


def test_build_is_deterministic():
    d1, n1 = graph.build_graph(ITEMS, ROWS, FEEDS)
    d2, n2 = graph.build_graph(list(reversed(ITEMS)), list(reversed(ROWS)), FEEDS)
    assert n1 == n2 and torch.equal(d1[graph.MENTIONS].edge_index, d2[graph.MENTIONS].edge_index)


def test_gexf_export_round_trip(tmp_path):
    import networkx as nx

    data, nodes = graph.build_graph(ITEMS, ROWS, FEEDS)
    path = tmp_path / "g.gexf"
    graph.export_gexf(data, nodes, path, seed=1)
    g = nx.read_gexf(path)
    assert g.number_of_nodes() == 9 and g.number_of_edges() == 8  # 3 from + 5 mentions
    assert g.nodes["entity:organization:openai"]["label"] == "Openai"
    assert g.nodes["entity:organization:openai"]["node_type"] == "entity"
    assert g.nodes["entity:organization:openai"]["degree"] == 3
    assert g.nodes["item:i1"]["source_id"] == "a"
    assert {d["relation"] for _, _, d in g.edges(data=True)} == {"from", "mentions"}
