# Zero Parades Dialogue Viewer

Extracts the branching dialogue system ("C4", the engine ZAUM also used for
*Disco Elysium*) from the Unity game *Zero Parades* and renders it as an
interactive, searchable node graph — inspired by
[Disco Elysium Scribe](https://disco-elysium-scribe.pages.dev/).

The dialogue data isn't in the game's ordinary asset files. It lives in one
Addressables bundle, serialized via Unity's `[SerializeReference]` (which
tools like AssetRipper can't decode), inside an IL2CPP-stripped build (so the
game's own DLLs are metadata-only stubs with no real fields or logic). Both
obstacles are why this needs a small pipeline rather than just being a
straightforward asset dump.

## What's here

- **`extract_dialogue.py`** — reads every `MonoBehaviour` in the dialogue
  bundle with [UnityPy] and flattens the resolved `SerializeReference` graph
  into one JSON file per chunk. Builds since the game's Unity 6 upgrade ("The
  Final Cut") ship the bundle with embedded type trees, so that's all it
  needs. For older builds without them, it falls back to pointing UnityPy's
  `TypeTreeGenerator` at your live game install (it reads `GameAssembly.dll`
  + `global-metadata.dat` itself, no manual `.tpk` needed). That fallback
  can't read IL2CPP metadata v39 (Unity 6.3), which is fine because those
  builds don't need it. Those builds also move every white check out of its
  conversation's chunk into the bundle's `DialogueDatabase`
  (`m_alwaysLoadedCards`); the extractor merges them back in. `rid` values are
  serialized as strings — they're 64-bit and JavaScript's `JSON.parse` would
  silently round them to the wrong integer otherwise.
- **`build_flow_index.py`** — builds the search index and the character/skill
  browsing indexes from that chunk output.
- **`build_changelog.py`** — diffs two extractions (e.g. before and after a
  game update) and writes `changes.json`, which drives the viewer's "What's
  New" popup, New tab, and NEW/CHANGED badges. Cards are matched by
  `flowId`+`cardId`, which stay stable across builds; chunk file names and
  `rid`s don't, so it also writes `legacy_links.json` to keep links shared
  before the update working.
- **`viewer.html`** — the viewer itself. Vanilla JS, no build step, no
  server-side logic beyond serving static files. Node-link graph per
  conversation (pan/zoom, click a node to see connected cards highlighted and
  everything else dimmed, double-click a jump card to fast-travel to its
  target), plus tabs for browsing by character, by skill check, and
  full-text search across every line — all with shareable links.
- **`Dockerfile`** / **`nginx.conf`** / **`fly.toml`** — deploys the above as
  a static site on [Fly.io](https://fly.io).

[UnityPy]: https://github.com/K0lb3/UnityPy

## Usage

Extraction needs a Unity IL2CPP game install (`GameAssembly.dll` +
`<Game>_Data/il2cpp_data/Metadata/global-metadata.dat`) and the specific
`.bundle` file containing the dialogue data — find it with something like
`grep -a -l RtC4 *.bundle` in the game's Addressables output directory,
adjusted for whatever your game's own dialogue-card class names are.

```bash
pip install -r requirements.txt

python extract_dialogue.py \
  --game-root "/path/to/Game" \
  --bundle "/path/to/Game/.../some_bundle.bundle" \
  --out-dir ./dialogue_data

python build_flow_index.py ./dialogue_data

# optional, after a game update: extract the new build into its own
# directory, then diff it against the previous one
python build_changelog.py ./dialogue_data_old ./dialogue_data \
  --old-audio-list old_audio_files.txt \
  --old-label "the previous version" --new-label "The Final Cut"

# serve it locally
cd dialogue_data && python3 -m http.server 8000
# then open http://localhost:8000/viewer.html
# (copy viewer.html into dialogue_data/, or serve both directories together)
```

To deploy: copy `viewer.html` next to the generated `dialogue_data/` output,
then `flyctl deploy` using the included `Dockerfile`/`fly.toml`.

## Notes on reuse

This was built against one specific game's data model (`ZAUM.FELD.*` card
types, its own skill list, its own `m_cardData` key names like
`dialog_lines`/`character_short_name`). Adapting it to a different game on
the same dialogue engine, or a different engine entirely, will mean revisiting
the type names hardcoded throughout `extract_dialogue.py`, `build_flow_index.py`,
and `viewer.html`.

Extracted game dialogue/script content is the property of its developer —
this repo only contains the extraction/viewing tool, not any game's data.
