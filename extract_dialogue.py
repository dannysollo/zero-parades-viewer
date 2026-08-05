import argparse
import json
import os
from collections import Counter

import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator


def stringify_rids(obj):
    # rid values are 64-bit and exceed JS's Number.MAX_SAFE_INTEGER (2^53);
    # JSON.parse in a browser silently rounds them to a different integer,
    # breaking every {"rid": N} lookup. Ship them as strings instead.
    if isinstance(obj, dict):
        if set(obj.keys()) == {"rid"} and isinstance(obj["rid"], int):
            return {"rid": str(obj["rid"])}
        return {k: stringify_rids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify_rids(v) for v in obj]
    return obj


parser = argparse.ArgumentParser(description="Extract a C4/FELD dialogue Addressables bundle into flat per-chunk JSON.")
parser.add_argument("--game-root", required=True, help="Path to the game's install directory (contains GameAssembly.dll etc.)")
parser.add_argument("--bundle", required=True, help="Path to the .bundle file containing the dialogue chunks (find it via `grep -a -l RtC4 *.bundle`)")
parser.add_argument("--out-dir", default="./dialogue_data", help="Output directory for chunks/ and index.json")
parser.add_argument("--unity-version", default="2022.3.62f3", help="Unity engine version (read via `strings globalgamemanagers | grep '^20..\\.'`)")
args = parser.parse_args()

CHUNKS_DIR = os.path.join(args.out_dir, "chunks")
os.makedirs(CHUNKS_DIR, exist_ok=True)

print("initializing TypeTreeGenerator against live game install...", flush=True)
gen = TypeTreeGenerator(args.unity_version)
gen.load_local_game(args.game_root)

print("loading bundle...", flush=True)
env = UnityPy.load(args.bundle)
env.typetree_generator = gen

objs = [o for o in env.objects if o.type.name == "MonoBehaviour"]
print(f"{len(objs)} MonoBehaviour objects found", flush=True)

index = {
    "chunks": [],
    "flow_to_chunk": {},
    "card_type_counts": Counter(),
    "total_cards": 0,
    "failed": [],
}

for i, obj in enumerate(objs):
    try:
        tree = obj.read_typetree()
    except Exception as e:
        index["failed"].append({"path_id": obj.path_id, "error": str(e)})
        print(f"[{i}] FAILED to read: {e}", flush=True)
        continue

    name = tree.get("m_Name")
    if name is None or not str(name).startswith("Chunk-"):
        # not a dialogue chunk (shouldn't happen given our earlier scan, but be defensive)
        continue

    chunk_id = tree.get("m_chunkId", name)
    dependencies = tree.get("m_dependencies", [])

    # references pool -> flat "nodes" dict keyed by rid
    ref_list = tree.get("references", {}).get("RefIds", [])
    nodes = {}
    for r in ref_list:
        rid = r.get("rid")
        if rid is None or rid == -2:
            continue
        t = r.get("type", {})
        node = {
            "type": t.get("class"),
            "namespace": t.get("ns"),
            "assembly": t.get("asm"),
        }
        node.update(stringify_rids(r.get("data", {})))
        nodes[str(rid)] = node
        index["card_type_counts"][t.get("class")] += 1

    # flows: flowId -> {cardId: rid}
    flows = {}
    mc = tree.get("m_cards", {})
    for flow_id, cards_dict in zip(mc.get("m_keys", []), mc.get("m_values", [])):
        card_map = {}
        for card_id, ref in zip(cards_dict.get("m_keys", []), cards_dict.get("m_values", [])):
            rid = ref.get("rid")
            card_map[card_id] = str(rid) if isinstance(rid, int) else rid
        flows[flow_id] = card_map
        index["flow_to_chunk"][flow_id] = chunk_id

    out = {
        "chunkId": chunk_id,
        "cardCount": tree.get("m_cardCount"),
        "dependencies": dependencies,
        "flows": flows,
        "nodes": nodes,
    }

    out_path = os.path.join(CHUNKS_DIR, f"{chunk_id}.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)

    index["chunks"].append({
        "chunkId": chunk_id,
        "cardCount": tree.get("m_cardCount"),
        "flowCount": len(flows),
        "nodeCount": len(nodes),
        "file": f"chunks/{chunk_id}.json",
    })
    index["total_cards"] += tree.get("m_cardCount") or 0

    if (i + 1) % 50 == 0:
        print(f"processed {i + 1}/{len(objs)}", flush=True)

index["card_type_counts"] = dict(index["card_type_counts"].most_common())

with open(os.path.join(args.out_dir, "index.json"), "w") as f:
    json.dump(index, f, indent=2)

print("DONE", flush=True)
print(f"chunks written: {len(index['chunks'])}", flush=True)
print(f"total cards: {index['total_cards']}", flush=True)
print(f"failed: {len(index['failed'])}", flush=True)
