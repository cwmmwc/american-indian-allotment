# Quick Reference Cheat Sheet

## Project Location
```
/Users/cwm6W/projects/federal-register-app
```

## Start the App
```bash
cd /Users/cwm6W/projects/federal-register-app
source venv/bin/activate
python3 app.py
```
Then open http://localhost:5001 in your browser.

## Stop the App
Press `Ctrl+C` in the terminal where it's running.

## Start Claude Code
```bash
cd /Users/cwm6W/projects/federal-register-app
claude
```
Claude Code will automatically read CLAUDE.md and have full project context.

## Useful Pages
- http://localhost:5001/ — Landing page (four datasets overview)
- http://localhost:5001/claims — Claims search (10,976 FR claims)
- http://localhost:5001/tribes — Browse by tribe
- http://localhost:5001/patents — Patent search (239,845 BLM records)
- http://localhost:5001/patents/timeline — Patent timeline with Wilson & Murray overlays
- http://localhost:5001/sankey — Trust-to-fee conversion flows
- http://localhost:5001/wilson — 1934 reservation baseline + Murray termination era
- http://localhost:5001/claims-rate — Claims by reservation
- http://localhost:5001/dubois — Du Bois-inspired data portraits
- http://localhost:5001/timeline — Forced fee claims timeline
- http://localhost:5001/about — About page

## Git Basics
```bash
git status          # see what's changed
git log --oneline   # see recent commits
git push            # push to GitHub
```

## GitHub Repo
https://github.com/cwmmwc/federal-register-forced-fee

## Key Files
- `app.py` — all routes and logic (single file)
- `templates/` — HTML templates (Jinja2)
- `static/style.css` — styles
- `CLAUDE.md` — full architecture guide (auto-loaded by Claude Code)
- `DATABASE.md` — complete database documentation

## Companion App (Leaflet Map)
```
/Users/cwm6W/projects/patent-analysis
```
Runs on port 8000. Cross-linked via `?tribe={name}&accession={id}`.
