# Local Agent Notes

- Keep changes minimal and centered in `bot.py`.
- Do not rewrite notification flow, scoring, or history rendering end-to-end.
- Treat `docs/*.html` as generated output. Change renderers in `bot.py`, not the generated files.
- The lightweight agent layer is `pick_reason`: a short explanation for why a repo was selected.
- The only repo-local skill is `repo-digest`.

