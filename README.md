# Obed-Edom

Local Mac tool that builds LED-wall (LW) and DSK Keynote decks from sermon/offering Word outlines. Keynote.app is required for generate, preview export, and the dashboard’s Keynote jobs.

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
