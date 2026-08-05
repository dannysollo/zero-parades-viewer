import argparse
import json
import os

parser = argparse.ArgumentParser(description="Build search/character/skill indexes from extract_dialogue.py's chunk output.")
parser.add_argument("--data-dir", default="./dialogue_data", help="Directory containing chunks/ (the --out-dir passed to extract_dialogue.py)")
args = parser.parse_args()

DATA_DIR = args.data_dir
CHUNKS_DIR = os.path.join(DATA_DIR, "chunks")

CHECK_TYPES = {"RtPassiveCard", "RtAntiPassiveCard", "RtWhiteCheckCard", "RtRedCheckCard"}


def resolve_leaf(nodes, rid):
    if rid is None or str(rid) == "-2":
        return None
    node = nodes.get(str(rid))
    if node is None:
        return None
    if node.get("type") in ("RtStringPropertyData", "RtWritableStringPropertyData",
                             "RtIntPropertyData", "RtWritableIntPropertyData",
                             "RtBoolPropertyData", "RtWritableBoolPropertyData"):
        return node.get("m_value")
    return None


def card_text_and_speaker(node, nodes):
    """Universal text detection: matches the viewer's hasDialogueText() heuristic
    (dialog_lines or description key), not a fixed type list — covers checks,
    orb cards, money options, etc., not just bark/fragment/janus."""
    card_data = node.get("m_cardData", {})
    keys = card_data.get("m_keys", [])
    values = card_data.get("m_values", [])
    cd = {k: v for k, v in zip(keys, values)}
    text = None
    if "dialog_lines" in cd:
        text = resolve_leaf(nodes, cd["dialog_lines"].get("rid"))
    if text is None and "description" in cd:
        text = resolve_leaf(nodes, cd["description"].get("rid"))
    speaker = resolve_leaf(nodes, cd.get("character_short_name", {}).get("rid")) if "character_short_name" in cd else None
    return text, speaker


flows = []
characters = {}  # character -> {flowId: line_count}
skills = {}  # skillId -> {flowId: count}
search_entries = []
chunk_files = sorted(f for f in os.listdir(CHUNKS_DIR) if f.endswith(".json"))

for fname in chunk_files:
    with open(os.path.join(CHUNKS_DIR, fname)) as f:
        chunk = json.load(f)
    nodes = chunk["nodes"]
    file_ref = f"chunks/{fname}"

    for flow_id, card_map in chunk["flows"].items():
        preview_speaker, preview_text = None, None
        speaker_counts = {}
        flow_skills = set()

        for card_id, rid in card_map.items():
            node = nodes.get(str(rid))
            if not node:
                continue
            text, speaker = card_text_and_speaker(node, nodes)

            if node.get("type") in CHECK_TYPES and node.get("m_skillID"):
                skill_id = node["m_skillID"]
                flow_skills.add(skill_id)
                skills.setdefault(skill_id, {})
                skills[skill_id][flow_id] = skills[skill_id].get(flow_id, 0) + 1

            if speaker:
                speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1
            if text:
                if preview_text is None:
                    preview_speaker, preview_text = speaker, text
                search_entries.append({
                    "t": text,
                    "s": speaker,
                    "ty": node.get("m_cardType") or node.get("type"),
                    "fl": flow_id,
                    "f": file_ref,
                    "r": str(rid),
                    "sk": node.get("m_skillID") if node.get("type") in CHECK_TYPES else None,
                })

        flows.append({
            "flowId": flow_id,
            "chunkId": chunk["chunkId"],
            "file": file_ref,
            "cardCount": len(card_map),
            "speaker": preview_speaker,
            "preview": (preview_text[:140] if preview_text else None),
            "speakers": sorted(speaker_counts.keys()),
            "skills": sorted(flow_skills),
        })
        for sp, cnt in speaker_counts.items():
            characters.setdefault(sp, {})[flow_id] = characters.get(sp, {}).get(flow_id, 0) + cnt

flows.sort(key=lambda x: x["flowId"])

with open(os.path.join(DATA_DIR, "flows_index.json"), "w") as f:
    json.dump(flows, f, indent=1)

flow_by_id = {f["flowId"]: f for f in flows}

char_list = []
for char, flow_counts in characters.items():
    total_lines = sum(flow_counts.values())
    char_list.append({
        "character": char,
        "totalLines": total_lines,
        "flowCount": len(flow_counts),
        "flows": [
            {"flowId": fid, "file": flow_by_id[fid]["file"], "lines": cnt, "preview": flow_by_id[fid]["preview"]}
            for fid, cnt in sorted(flow_counts.items(), key=lambda kv: -kv[1])
        ],
    })
char_list.sort(key=lambda c: -c["totalLines"])
with open(os.path.join(DATA_DIR, "characters.json"), "w") as f:
    json.dump(char_list, f, indent=1)

skill_list = []
for skill, flow_counts in skills.items():
    total_checks = sum(flow_counts.values())
    skill_list.append({
        "skill": skill,
        "totalChecks": total_checks,
        "flowCount": len(flow_counts),
        "flows": [
            {"flowId": fid, "file": flow_by_id[fid]["file"], "checks": cnt, "preview": flow_by_id[fid]["preview"]}
            for fid, cnt in sorted(flow_counts.items(), key=lambda kv: -kv[1])
        ],
    })
skill_list.sort(key=lambda s: -s["totalChecks"])
with open(os.path.join(DATA_DIR, "skills.json"), "w") as f:
    json.dump(skill_list, f, indent=1)

with open(os.path.join(DATA_DIR, "search_index.json"), "w") as f:
    json.dump(search_entries, f, separators=(",", ":"))

print(f"wrote {len(flows)} flow entries")
with_preview = sum(1 for x in flows if x["preview"])
print(f"flows with a text preview: {with_preview}")
print(f"wrote {len(char_list)} characters")
print(f"wrote {len(skill_list)} skills")
print(f"wrote {len(search_entries)} search entries")
