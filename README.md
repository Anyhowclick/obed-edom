# Obed-Edom

Local Mac tool that builds LED-wall (LW) and DSK Keynote decks from sermon/offering Word outlines. Keynote.app is required for generate, preview export, and the dashboard’s Keynote jobs.

## Outline cues

An outline carries **semantic cues** that say what a block *is*. Generate turns each
one into the slides below and writes **operator cues** back into `<stem>_CUED.docx`
for show-call.

**One cue is one slide advance on that deck.** Nothing advances on its own, so the
number of `[LW…]` cues equals the LW slide count and likewise for `[DSK…]`. The
Sermon Checker relies on this to spot a slide with no cue, or a cue with no slide.

| Semantic cue | LW master | DSK master | Operator cue | Slides |
|---|---|---|---|---|
| `[TITLE]` | `TITLE` | — | `[LW-TITLE]` | 1 LW |
| `[FILLER]` (sermon) | `TITLE` | — | `[LW-TITLE]` | 1 LW |
| `[FILLER]` (offering) | `BLANK` | `Ways To Give QR Code` | `[LW-OFFERING FILLER]` `[DSK-PP-QR CODE]` | 1 + 1 |
| `[FILLER-QR]` | `BLANK` | `Ways To Give QR Code` | `[LW-OFFERING FILLER]` `[DSK-PP-QR CODE]` | 1 + 1 |
| `[GIVING-OPTIONS]` | `BLANK` | `Ways To Give DSK CREDIT CARD` | `[LW-GIVING OPTIONS]` `[DSK-PP-GIVING OPTIONS]` | 1 + 1 |
| `[VERSE]` | `VERSES` | `Verse Standard` / `Verse 1 Line` | `[LW]` `[DSK-PP]` | 1 + 1 per chunk |
| `[VERSE-CONTINUED]` | `VERSES` | verse master | `[LW]` `[DSK-PP]` | 1 + 1 |
| `[POINT]` | `NON-NUMBERED POINT PRE` | `Non-Num Point with Verse-Pre` | `[LW]` `[DSK-PP]` | 1 + 1 |
| `[NUM-POINT]` | `NUMBERED POINT PRE` | `Num Point with Verse-Pre` | `[LW]` `[DSK-PP]` | 1 + 1 |
| `[VERSE-AFTER-POINT]` | `… POINT POST` | `… Point with Verse-Post` | `[LW]` `[DSK-PP]` | 1 + 1 |

Long passages split across several `[VERSE]` slides; each chunk gets its own operator
cue at the verse number where it starts.

### `[VERSE-CONTINUED]` vs `[VERSE-AFTER-POINT]`

These read alike and do unrelated things.

- **`[VERSE-CONTINUED]`** continues a *passage*. The preacher pauses mid-quote to
  comment, then resumes, so the next slide re-shows the verse with a leading verse
  number. It stays on the ordinary verse master.
- **`[VERSE-AFTER-POINT]`** pairs a verse with a *point title*. It builds the
  point-plus-verse slide on the POST master, and the point before it Magic Moves
  into it. Use it only directly after `[POINT]` or `[NUM-POINT]`.

A plain `[VERSE]` after a point is a verse-only slide: the point stays a static PRE
with no Magic Move. Cue both when you want the point-plus-verse slide *and* the
verse on its own.

`[VERSE-FROM-PREVIOUS]` is **deprecated** — write `[VERSE-CONTINUED]`. It still maps,
but generate raises `cue.deprecated_alias`.

`[Pray]`, `[Instructions]` and `[Turn to your neighbours…]` are stage directions, not
cues, and never become slides.

### Naming conventions

The two families are spelled differently, and both are matched case-insensitively.

- **Semantic cues are hyphenated**: `NUM-POINT`, `GIVING-OPTIONS`, `VERSE-AFTER-POINT`.
  A spaced form (`[VERSE AFTER POINT]`) is accepted and folded to the hyphenated one.
- **Operator cues are a deck prefix then space-separated words**:
  `LW-OFFERING FILLER`, `DSK-PP-QR CODE`.

Either a hyphen or an en dash may follow the deck prefix, because generate writes
`[DSK-PP]` while hand-authored outlines often carry `[DSK–PP]`.

## Accessibility permission

Grant Accessibility to whatever launches generate — Terminal, iTerm, or the dashboard app — in *System Settings > Privacy & Security > Accessibility*.

Multi-verse slides need each verse number to carry the template's verse-number character style, and Keynote's AppleScript dictionary has no style support at all. Generate has to drive **Format > Copy Style** and **Paste Style** through the UI, which needs Accessibility. Without it the deck still generates with the right wording, but later verse numbers sit on the baseline and generate reports a flag. See the `obed-edom` skill for the full details before changing that code.

## Dashboard

Operator UI on localhost: generate from outlines, read-only Keynote diff, plus DSK/resize tabs (those two are UI stubs until the logic lands).

From the repo root, with the venv active:

```bash
python -m pip install -e .
python -m obed_edom dashboard
```

That serves the built SPA from `dashboard/dist` at [http://127.0.0.1:8765/](http://127.0.0.1:8765/) and opens a browser. Use `--no-browser` to skip the open, or `--host` / `--port` to change the bind.

```bash
python -m obed_edom dashboard --no-browser --port 8765
```

Restart the dashboard after pulling code so the Python process reloads.

### Rebuild the UI

Needed if you change files under `dashboard/src` (a prebuilt `dashboard/dist` is already in the repo):

```bash
cd dashboard
npm install
npm run build
```

Then restart `python -m obed_edom dashboard`.

For UI work with hot reload, run the API and Vite together:

```bash
python -m obed_edom dashboard --no-browser
cd dashboard && npm install && npm run dev
```

Vite is on [http://localhost:5173/](http://localhost:5173/) and proxies `/api` to port 8765.

### Notes

- Generate and Keynote inspect run **one job at a time** (Keynote is a single app).
- `.docx` outlines and at least one LW or DSK template `.key` are dropped in the generator. `.key` files are packages — drop from Finder or use **Choose on this Mac**.
- Diff never saves the source Keynotes.
