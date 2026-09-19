# Obed-Edom

Obed-Edom is a local Mac dashboard for preparing church presentation media. It can turn a Word outline into LED-wall (LW) and lower-third (DSK) Keynote decks, check finished material, resize wall slides for CG, and create map or watercolour assets.

Your outlines and decks are processed on this Mac. Keynote is required.

## Start the dashboard

1. Double-click **`Start Dashboard.command`**.
2. Wait for the browser to open at [http://127.0.0.1:8765/](http://127.0.0.1:8765/). The first launch may take a few minutes while the app sets itself up.
3. Leave the Terminal window open while you work.

If macOS blocks the launcher, Control-click it and choose **Open**.

## What you can do

- **Sermon Base Generator** — create LW and DSK decks, an operator-cued Word outline, previews, and a review PDF.
- **Sermon Checker** — check an outline, one deck, or an LW/DSK pair for cue, wording, layout, photo, and house-style issues. Checks do not alter the source files.
- **Alpha Keynote** — experimental presenter for a prepared 16:9 Keynote HTML export, with current/upcoming stills, slide-number navigation, and a separate silent display output. Native HTML alpha and movie continuity are not qualified; DeckLink fill/key is not available yet.
- **CG Resizer** — turn a finalised wide-wall deck into a 16:9 CG deck and review any framing choices.
- **Maps** — build and export map slides for LW, DSK, and CG.
- **Watercolour** — turn photos into pencil-and-wash artwork and add them to maps.
- **History** — reopen recent results stored in the `output` folder.

## Generate sermon decks

1. Open **Sermon Base Generator**.
2. Add an LW template, a DSK template, or both. The dashboard remembers them on this Mac.
3. Drop in one or more `.docx` sermon or offering outlines.
4. Let the job finish before using Keynote for something else.
5. Review the slide previews and any flags, then open the generated decks and `review.pdf`.

Each run is saved under `output/<outline name>/`. Depending on the templates supplied, it includes:

- LW and DSK `.key` decks
- an `<outline name>_CUED.docx` show-call outline
- `review.pdf` and slide previews

## Outline cues

Put cues in square brackets in the Word outline to tell the generator what to build.

| Cue | Use it for |
|---|---|
| `[TITLE]` | Sermon title |
| `[VERSE]` | Scripture passage |
| `[VERSE-CONTINUED]` | A passage that resumes after commentary |
| `[POINT]` / `[NUM-POINT]` | Unnumbered or numbered sermon point |
| `[VERSE-AFTER-POINT]` | A verse paired with the point immediately before it |
| `[FILLER-QR]` / `[GIVING-OPTIONS]` | Offering slides |

The generator writes one operator cue for every generated slide into the `_CUED.docx` file. Notes such as `[Pray]` or `[Instructions]` remain stage directions and do not create slides.

## Alpha Keynote experiment

Prepare a deck using **Sermon Checker → Build Preview**, then select that prepared
deck and a detected display in **Alpha Keynote**. Starting creates one hidden
output session; **Show output** makes it visible. The 16:9 picture fits inside
the display without stretching. HDMI hiding produces black and leaves playback
running. Type an original slide number and press Enter to restart that slide at
its initial state. Skipped slides are unavailable.

Switching tabs or closing the presenter does not stop output. **Stop session**
ends it. Keep the dashboard server running; restarting the server does not restore
a movie position. Current/upcoming pictures are still previews, and presenter
notes are unavailable in the current HTML preparation path. Audio is disabled.
Only the recognised Keynote player version and manual presentation mode are
accepted. This experiment does not enable the separate DSK animation-file exporter.

## Important checks

- The first time you generate or resize a deck, macOS may ask for Accessibility access. Allow the launcher app—usually Terminal—in **System Settings → Privacy & Security → Accessibility**, then restart the dashboard.
- Keynote jobs run one at a time. Do not close Keynote or the Terminal window while a job is running.
- Always read the flags and review PDF, then check the LW and DSK decks separately before show day.
- Source outlines and Keynote files are not overwritten. Generated work goes to `output` unless another destination is chosen.

## If something does not open

- Visit [http://127.0.0.1:8765/](http://127.0.0.1:8765/) manually if the browser does not appear.
- If a job reports a permission problem, grant Accessibility access and restart the dashboard.
- Find completed work in **History** or the `output` folder.
- To restart, close the dashboard's Terminal window and double-click **`Start Dashboard.command`** again.
