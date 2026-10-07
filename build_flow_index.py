import json
import os
import sys

DATA_DIR = sys.argv[1] if len(sys.argv) > 1 else "/home/dannysollo/zero-parades/decompiled/dialogue_data"
CHUNKS_DIR = os.path.join(DATA_DIR, "chunks")

CHECK_TYPES = {"RtPassiveCard", "RtAntiPassiveCard", "RtWhiteCheckCard", "RtRedCheckCard"}

# Passive checks sometimes put a skill name (not a real character) in the
# normal "speaker" field -- see project notes on the "skill voicing a passive
# observation" quirk. Real characters only, for anything that treats a flow's
# speaker as "who this conversation belongs to" (e.g. the universe-view
# character clustering) -- otherwise these pollute the character graph.
SKILL_IDS = {
    "coordination", "inference", "nerve", "wits", "entanglement", "inspiration", "affect", "presence",
    "awareness", "motivation", "recall", "focus", "vigour", "muscle", "senses",
}


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


def main():
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

            # "Primary" speaker = whoever has the most lines in THIS flow (excluding
            # skill-voiced passive checks) -- used for clustering conversations by
            # character. Distinct from `speaker` above (the speaker of whichever
            # card happened to be first in raw storage order, used only for the
            # sidebar preview line's caption, which needs to match `preview`'s text).
            #
            # Turns out a large fraction of flows (roughly 60%) are *entirely*
            # skill-voiced -- whole internal-monologue sequences, not just an
            # occasional passive-check line inside an otherwise normal scene. Those
            # get their own `primarySkillSpeaker` fallback so they can be grouped
            # under their own skill rather than dumped into a generic catch-all
            # alongside flows that have no speaker at all.
            real_counts = {sp: cnt for sp, cnt in speaker_counts.items() if sp not in SKILL_IDS}
            primary_speaker = max(real_counts, key=real_counts.get) if real_counts else None
            primary_skill_speaker = None
            if not primary_speaker:
                skill_only_counts = {sp: cnt for sp, cnt in speaker_counts.items() if sp in SKILL_IDS}
                primary_skill_speaker = max(skill_only_counts, key=skill_only_counts.get) if skill_only_counts else None

            flows.append({
                "flowId": flow_id,
                "chunkId": chunk["chunkId"],
                "file": file_ref,
                "cardCount": len(card_map),
                "speaker": preview_speaker,
                "primarySpeaker": primary_speaker,
                "primarySkillSpeaker": primary_skill_speaker,
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


if __name__ == "__main__":
    main()
