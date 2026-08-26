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

## Keynote scripting limitations

Keynote's scripting interface (verified on 15.3.1) leaves several things out of reach. These are Keynote's limits, not bugs in this tool; each has a probe under `scripts/` and fuller notes in the `obed-edom` skill.

- **Per-character style is unreadable.** Font, size and colour of a text run cannot be read; anything needing them comes off a rendered preview. (`scripts/probe_runs.js`)
- **Z-order can be neither read nor set.** There is no arrange command and no stacking property. The resizer inherits the source deck's stacking untouched — it cannot repair a bad stack (e.g. a title badge buried under map art) or break a good one. Only generate controls stacking, by creation order. (`scripts/probe_zorder.js`)
- **Corner radius is unreadable and unsettable.** A rounded rectangle's rounding is invisible to scripting, so resizing a rounded plate squares its corners and cannot be undone. The resizer avoids this for a corner label (a lone word on a plate bleeding off a corner) by moving it at its own size instead of resizing it into the template slot; a missions badge plate is still resized to its slot. (`scripts/probe_corner.js`)
- **Character styles must be applied through the UI**, which is why generate needs Accessibility (above).

## After you clone (no technical setup)

You do **not** need Homebrew or Node for day-to-day use. The dashboard UI is already built in this folder (`dashboard/dist`).

1. Clone or unzip this project onto a **Mac** that already has **Keynote**.
2. Double-click **`Start Dashboard.command`**.
3. The first run may take a minute (it sets up a private Python folder). Leave the Terminal window open.
4. Your browser should open [http://127.0.0.1:8765/](http://127.0.0.1:8765/).

If macOS says the file “cannot be opened because it is from an unidentified developer”, Control-click it → **Open**. If Python 3.10+ is missing, the script installs it with Homebrew *only if you already have brew*; otherwise it uses a small helper (`uv`) and does not require `brew install`.

Grant Accessibility to Terminal (or iTerm) the first time you generate a deck — see [Accessibility permission](#accessibility-permission).

## Dashboard

Operator UI on localhost: generate from outlines, read-only Keynote diff, plus DSK/resize tabs (those two are UI stubs until the logic lands).

From the repo root, with the venv active (or just use `Start Dashboard.command`):

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
