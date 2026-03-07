# Quick Reference Cheat Sheet

## Project Location
```
/Users/cwm6W/Documents/UVA/UVa 2025-26/federal-register-app
```

## Start the App
```bash
cd "/Users/cwm6W/Documents/UVA/UVa 2025-26/federal-register-app"
source venv/bin/activate
python3 app.py
```
Then open http://localhost:5001 in your browser.

## Stop the App
Press `Ctrl+C` in the terminal where it's running.

## Start Claude Code
```bash
cd "/Users/cwm6W/Documents/UVA/UVa 2025-26/federal-register-app"
claude
```
Claude Code will automatically read CLAUDE.md and have full project context.

## Useful Pages
- http://localhost:5001/ — Claims search
- http://localhost:5001/patents — Patent search (239,845 records)
- http://localhost:5001/patents/timeline — Patent timeline (fee vs trust)
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
