# CLAUDE.md

Mini AI Dungeon Master: a text chatbot that runs one boss fight (Lyra vs. Ashfang). The player types free text; a local LLM maps it to an action, a deterministic Python rules engine resolves it, and the LLM narrates the result.

> The language model proposes, the engine decides, the language model narrates.

**`ProjectRequirements.md` is the source of truth** for requirements (FR-x), guardrails (GR-x), rules, stats, HP bands, turn order and scope. Read the relevant section before implementing anything. "PC" means player character (Lyra).

## Working rules

- **Ask, don't assume.** If the spec is unclear, contradictory or silent, stop and ask the user. Do not fill gaps with guesses.
- **Spec edits need approval.** Propose changes to ProjectRequirements.md; edit it only after the user approves.
- **Test-first for the engine.** Write a failing pytest before implementing each engine rule.
- **Commit, push and PR:** Once the whole task is done without remaining question, ask the user if he wants to commit, push, and create PR.
- **GitHub via `gh` CLI.** Use the `gh` CLI for issues, PRs and other GitHub operations, not the GitHub MCP server.

## Architecture invariants

- **The engine owns all state.** Only `engine.py` changes HP, Cure Wounds uses, dodge state, round and fight outcome. LLM output is never written into state (GR-1).
- **The engine has no LLM dependency** and must stay importable and testable without Ollama.
- **All dice come from one seeded `random.Random` instance.** Same seed + same inputs = same dice and state (FR-12). Never call the `random` module directly.
- **Boss policy is code only**: Fire Breath once, on the first boss turn after its HP ≤ 50%; otherwise Bite.
- **Narration gets facts only** (actor, action, hit/miss, damage, HP before/after, HP band). Every number in the narration must appear in the facts (GR-3).
- **Retry budget:** at most 2 LLM calls per phase, with a timeout on every Ollama call (GR-9).
- **The model name lives only in `config.json`.** No hardcoded model names, temperatures, seed or limits in code.
- **Localhost only.** No paid APIs and no network traffic beyond the local Ollama server.
- **Log every turn** to `logs/*.jsonl` with the fields listed in FR-11.

Turn loop (§10): input guardrails → intent call (temp 0, `format: "json"`) → validate, 1 retry → PC action → boss action → resolved facts → one narration call for both actions (temp 0.7) → output guardrails → UI + status panel + log. Normal turn = 2 LLM calls.

## Layout

```
mini_dm/
  __init__.py
  engine.py        # state, dice, rules, boss policy
  llm.py           # Ollama client, intent and narration calls
  guardrails.py    # input, output and integrity checks
  app.py           # Gradio chat UI and status panel
  prompts/
    intent.txt
    narration.txt
tests/
logs/              # JSONL turn logs (gitignored)
config.json        # model name, temperatures, seed, limits
requirements.txt   # gradio, httpx, pydantic, pytest
```

## Environment

Windows, Python 3.14 via the `py` launcher, local Ollama with `llama3.1:8b`.

```bash
py -3.14 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m mini_dm.app   # run from repo root
ollama pull llama3.1:8b
```

## Testing

- Engine unit tests cover the list in ProjectRequirements.md §11.
- Guardrail tests use a **fake LLM client**. Tests must never call the real model.
- Every example input in the GR-1 to GR-8 table needs a test showing the expected behaviour.
