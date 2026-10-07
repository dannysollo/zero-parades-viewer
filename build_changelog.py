"""Diff two extracted dialogue_data versions and write changes.json for the
viewer's "What's new" popup and NEW/CHANGED card badges.

Usage: build_changelog.py <old_data_dir> <new_data_dir> [--old-audio-list FILE]

Cards are matched by (flowId, cardId), which ZAUM keeps stable across builds
(chunk *file* names are not stable -- The Final Cut renumbered most of them --
so never key anything on the chunk file). Rids are only meaningful within one
version's chunk, so the rids written here are always the NEW version's.

A card is "changed" when its dialogue text (ignoring whitespace-only edits),
speaker, check skill, or check difficulty differs. Edge-only changes are not
counted: they're almost always a side effect of new cards being spliced in,
and those new cards are already flagged themselves.
"""
import argparse
import json
import os
import re
from collections import Counter

from build_flow_index import CHECK_TYPES, SKILL_IDS, card_text_and_speaker

CHUNK_KINDS = [
    ("Chunk-orb-flow", "orb"),
    ("Chunk-process-thought-flow", "thought"),
    ("Chunk-bark-flow", "bark"),
    ("Chunk-dramatic-encounter", "encounter"),
    ("Chunk-flow", "conversation"),
]
PREVIEW_LEN = 160
# The protagonist and the narrator are in nearly every scene, so they say
# nothing about *where* a change is. Group by the most frequent other speaker.
NON_PARTNERS = {"herschel", "narrator"} | SKILL_IDS


def chunk_kind(chunk_id):
    for prefix, kind in CHUNK_KINDS:
        if chunk_id.startswith(prefix):
            return kind
    return "other"


def norm(text):
    return re.sub(r"\s+", " ", text).strip() if text else text


def load_cards(data_dir):
    """(flowId, cardId) -> card summary, flowId -> chunkId, and
    (chunk file, rid) -> (flowId, cardId) for translating old shared links."""
    cards, flow_chunk, by_rid = {}, {}, {}
    chunks_dir = os.path.join(data_dir, "chunks")
    for fname in sorted(os.listdir(chunks_dir)):
        with open(os.path.join(chunks_dir, fname)) as f:
            chunk = json.load(f)
        nodes = chunk["nodes"]
        for flow_id, card_map in chunk["flows"].items():
            flow_chunk[flow_id] = chunk["chunkId"]
            for card_id, rid in card_map.items():
                by_rid[(f"chunks/{fname}", str(rid))] = (flow_id, card_id)
                node = nodes.get(str(rid), {})
                text, speaker = card_text_and_speaker(node, nodes)
                is_check = node.get("type") in CHECK_TYPES
                cards[(flow_id, card_id)] = {
                    "r": str(rid),
                    "t": text,
                    "s": speaker,
                    "ty": node.get("m_cardType") or node.get("type"),
                    "sk": node.get("m_skillID") if is_check else None,
                    "dc": node.get("m_threshold") if is_check else None,
                }
    return cards, flow_chunk, by_rid


def summary(card_id, card):
    out = {"c": card_id, "r": card["r"], "ty": card["ty"]}
    if card["t"]:
        out["t"] = card["t"][:PREVIEW_LEN]
    if card["s"]:
        out["s"] = card["s"]
    return out


def voiced_card_ids(names):
    """Audio stems are "<cardId>" or "<cardId>-alternative-N" (Janus variants)."""
    return {n[: -len(".opus")].split("-alternative-")[0] for n in names if n.endswith(".opus")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old_dir")
    ap.add_argument("new_dir")
    # Only "newly voiced" is detectable: re-encoding the same source audio
    # doesn't give byte-identical .opus files, so hashes can't spot re-records.
    ap.add_argument("--old-audio-list", help="the old version's audio/ file listing (one name per line)")
    ap.add_argument("--old-label", default="previous version")
    ap.add_argument("--new-label", default="current version")
    args = ap.parse_args()

    old, _, old_by_rid = load_cards(args.old_dir)
    new, flow_chunk, _ = load_cards(args.new_dir)

    speakers_by_flow = {}
    for (flow_id, _), card in new.items():
        if card["s"] and card["s"] not in NON_PARTNERS:
            speakers_by_flow.setdefault(flow_id, Counter())[card["s"]] += 1
    with open(os.path.join(args.new_dir, "flows_index.json")) as f:
        flow_meta = {fl["flowId"]: fl for fl in json.load(f)}
    old_flows = {flow_id for flow_id, _ in old}

    old_voiced = new_voiced = None
    if args.old_audio_list:
        with open(args.old_audio_list) as f:
            old_voiced = voiced_card_ids(line.strip() for line in f)
        new_audio_dir = os.path.join(args.new_dir, "audio")
        new_voiced = voiced_card_ids(os.listdir(new_audio_dir)) if os.path.isdir(new_audio_dir) else set()

    flows = {}

    def flow_entry(flow_id):
        if flow_id not in flows:
            meta = flow_meta.get(flow_id, {})
            flows[flow_id] = {
                "flowId": flow_id,
                "file": meta.get("file"),
                "status": "updated" if flow_id in old_flows else "new",
                "kind": chunk_kind(flow_chunk.get(flow_id, "")),
                "primarySpeaker": meta.get("primarySpeaker"),
                "primarySkillSpeaker": meta.get("primarySkillSpeaker"),
                "partner": (speakers_by_flow[flow_id].most_common(1)[0][0]
                            if flow_id in speakers_by_flow else None),
                "preview": meta.get("preview"),
                "cardCount": meta.get("cardCount"),
                "newCards": [],
                "changedCards": [],
                "removedCards": [],
            }
        return flows[flow_id]

    totals = {"newFlows": 0, "updatedFlows": 0, "newCards": 0, "newLines": 0,
              "changedCards": 0, "removedCards": 0, "removedLines": 0,
              "newlyVoicedCards": 0}

    for key, card in new.items():
        flow_id, card_id = key
        prev = old.get(key)
        if prev is None:
            flow_entry(flow_id)["newCards"].append(summary(card_id, card))
            totals["newCards"] += 1
            totals["newLines"] += bool(card["t"])
            continue

        changes = {}
        if norm(prev["t"]) != norm(card["t"]):
            changes["text"] = prev["t"]
        if prev["s"] != card["s"]:
            changes["speaker"] = prev["s"]
        if prev["sk"] != card["sk"]:
            changes["skill"] = prev["sk"]
        if prev["dc"] != card["dc"]:
            changes["difficulty"] = prev["dc"]
        if old_voiced is not None and card_id in new_voiced and card_id not in old_voiced:
            changes["voice"] = "added"
            totals["newlyVoicedCards"] += 1
        if changes:
            entry = summary(card_id, card)
            entry["was"] = changes
            flow_entry(flow_id)["changedCards"].append(entry)
            totals["changedCards"] += 1

    for key, card in old.items():
        if key in new:
            continue
        flow_id, card_id = key
        entry = summary(card_id, card)
        del entry["r"]  # old-version rid, meaningless against the new chunks
        flow_entry(flow_id)["removedCards"].append(entry)
        totals["removedCards"] += 1
        totals["removedLines"] += bool(card["t"])

    for fl in flows.values():
        totals["newFlows" if fl["status"] == "new" else "updatedFlows"] += 1

    out = {
        "oldLabel": args.old_label,
        "newLabel": args.new_label,
        "totals": totals,
        "flows": sorted(flows.values(), key=lambda fl: (fl["status"] != "new", -len(fl["newCards"]), fl["flowId"])),
    }
    with open(os.path.join(args.new_dir, "changes.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))

    # Rids are reassigned on every build, so links shared before this update
    # (#...&f=<old chunk file>&n=<old rid>) can only be resolved through the
    # old version's own (file, rid) -> card mapping. The viewer fetches this
    # lazily, only when it's handed one of those old-style links.
    legacy = {}
    for (file, rid), (flow_id, card_id) in old_by_rid.items():
        if (flow_id, card_id) in new:
            legacy.setdefault(file, {})[rid] = card_id
    with open(os.path.join(args.new_dir, "legacy_links.json"), "w") as f:
        json.dump(legacy, f, separators=(",", ":"))

    print(json.dumps(totals, indent=1))


if __name__ == "__main__":
    main()
