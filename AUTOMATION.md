# Automation operations

Daily public feed collection and semi-monthly keyword trends remain on GitHub Actions.
No model API credential is required. Both writers synchronize main before pushing,
retry rejected pushes at most three times, and explicitly request a Pages rebuild.

The Codex daily editorial task runs at 09:00 America/Toronto. It writes source-grounded
Chinese edits to `data/editorial/YYYY-MM-DD.json` with existing source URLs and translated
title/body (or paper summary). It must not invent source URLs, statements or statistics.

Run `python scripts/publish_editorial.py` to apply these edits to today's public digest
and regenerate HTML, JSON, RSS and the archive without calling a model API. Run
`python -m unittest discover -s tests` before publishing. The workflow's later feed
refreshes preserve matching edits. Items no longer in the current digest are not restored
from an old editorial file. Original text is retained in the JSON's `*_original` fields.

The desktop editorial task needs the computer powered on and the app running.
GitHub's public-feed updates continue independently when the desktop is offline.
