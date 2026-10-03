# CLAUDE.md

Read `PROJECT.md` first. It holds the plan, current status, open decisions, privacy rules and agent rules for this repo. Then read `docs/schema.md` and `docs/data_notes.md`.

Key rules, repeated here because they matter most:
- Do not open files in `data/raw/` or `data/private/`, and do not print rows of real data. Check real-data logic with aggregate queries only, unless Topias explicitly asks otherwise in the session.
- Never fabricate results. Every reported number must trace to a file in `results/raw/`.
- Ask before changing models, metrics, eval questions or the schema.
- No emojis in code or comments.
- Update "Current status" and the session log in `PROJECT.md` at the end of each session.
