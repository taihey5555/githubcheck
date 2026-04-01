---
name: repo-digest
description: Use when extending this bot's lightweight repo-picking behavior, especially short pick reasons, compact digest text, and backward-compatible history metadata.
---

# Repo Digest

- Keep additions thin. Prefer extending existing fields over adding new flows.
- `pick_reason` is the main agent-facing output. It should stay short, concrete, and fit in one line.
- Preserve backward compatibility for `docs/history.json`. New render logic must tolerate missing fields.
- Prefer updating `bot.py` renderers and message builders instead of editing generated HTML directly.

