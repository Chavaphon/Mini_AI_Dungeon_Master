# Mini AI Dungeon Master

A text chatbot that runs one boss fight: **Lyra**, the player character, against **Ashfang**, a young ember drake, at the top of a collapsed watchtower. You type what Lyra does in plain English. A local LLM (served by Ollama) works out what you meant, a deterministic Python rules engine rolls the dice and resolves it, and the LLM narrates the result.

> The language model proposes, the engine decides, the language model narrates.

It is a small version of the class project *AI Dungeon Master: A Hybrid Rule-Engine and LLM-Based Game Master System*. The full requirements are in [ProjectRequirements.md](ProjectRequirements.md), and the report answering the assignment questions is in [docs/report.md](docs/report.md).

## How it works

Each turn runs this loop:

```
player input
  -> input guardrails (injection, off-topic, length and abuse)
  -> intent call, temperature 0, JSON output
  -> validate against the allow-list, 1 retry, then a keyword fallback
  -> engine executes Lyra's action
  -> engine executes Ashfang's action
  -> resolved facts for both actions
  -> one narration call, temperature 0.7
  -> output guardrails (numbers match the facts, in character, content)
  -> chat UI + status panel + JSONL log
```

- **The engine owns all state.** Only `mini_dm/engine.py` changes HP, Cure Wounds uses, dodge state, the round and the outcome. Nothing the model writes goes into state.
- **Seeded dice.** Every roll comes from one seeded `random.Random`, so the same seed and inputs give the same dice and state.
- **Two LLM calls per normal turn:** one for intent and one for narration.
- **Local only.** No paid API and no network traffic beyond the local Ollama server.

## Requirements

- Windows with Python 3.14 (the `py` launcher)
- [Ollama](https://ollama.com) running locally, with the `llama3.1:8b` model
- Python packages in `requirements.txt`: `gradio`, `httpx`, `pydantic`, `pytest`

## Setup

From the repo root:

```bash
py -3.14 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
ollama pull llama3.1:8b
```

Make sure Ollama is running (the tray app, or `ollama serve`) at `http://localhost:11434`, the host set in `config.json`.

## Run the app

```bash
.venv/Scripts/python -m mini_dm.app
```

Run it from the repo root. On start it prints `Loading the model...` and warms the model up, which can take up to `warmup_timeout_s` seconds on a cold load. Then open the local URL Gradio prints (by default http://127.0.0.1:7860).

If Ollama is not running, the app prints `Warning: the model did not load. Is Ollama running?` and turns reply with "The mists swirl… (the model is unavailable)" instead of crashing.

The screen has the chat, a status panel (HP bars, Cure Wounds uses left, round number and dodge state) and a **Restart** button that resets the fight.

## How to play

Lyra has four actions. Say them however you like:

| Action | Example input | Effect |
|---|---|---|
| Attack | "I slash at the drake with my sword" | Short sword, +5 to hit, 1d6+3 damage |
| Fire Bolt | "Fire bolt at Ashfang!" | Spell attack, +5 to hit, 1d10 damage, unlimited |
| Cure Wounds | "I heal myself" | Heals 1d8+3, up to max HP, 2 uses |
| Dodge | "I dodge" | Attacks against Lyra have disadvantage until her next turn |

Anything else ("I taunt the drake", "I look around") is narrated, and Ashfang still takes its turn. Spells Lyra does not know are refused ("You know only Fire Bolt and Cure Wounds."), and that turn does not count. Attempts to override the rules, off-topic requests and abusive or over-long input are refused or redirected in character.

After each narration, the chat shows a code-built roll line per action: the d20, bonus, total against AC, hit or miss, and damage. Lyra acts first each round, then Ashfang. The fight ends when either side reaches 0 HP.

## Run the tests

```bash
.venv/Scripts/python -m pytest
```

The tests use a fake LLM client and never call the real model, so Ollama does not need to be running.

## Balance simulation

Simulate 1,000 seeded fights with a random PC policy (no LLM or Ollama needed) and print the PC win rate, fight length and the stats used:

```bash
.venv/Scripts/python -m mini_dm.simulate
```

The fight count and seed come from `config.json`. With the current stats and seed 42 the PC wins 54.8% of fights, and a fight lasts about 9 rounds on average.

## Configuration

All tunable values live in `config.json`. The code contains no hardcoded model names, temperatures, seed or limits.

| Key | What it sets |
|---|---|
| `seed` | Dice seed for the fight and the simulation |
| `ollama.host`, `ollama.model` | Ollama server and model name (`llama3.1:8b`) |
| `ollama.timeout_s`, `ollama.warmup_timeout_s`, `ollama.keep_alive` | Per-call timeout, cold-load timeout, how long Ollama keeps the model loaded |
| `intent.temperature`, `intent.num_predict` | Intent call settings (temperature 0) |
| `narration.temperature`, `narration.num_predict`, `narration.max_sentences`, `narration.max_chars` | Narration call settings and length caps |
| `limits.input_max_chars`, `limits.max_llm_calls_per_phase` | Player input cap (300) and retry budget (2 calls per phase) |
| `simulation.fights` | Number of fights in the balance simulation |
| `logging.dir` | Turn log folder |
| `characters` | Lyra's and Ashfang's HP, AC, attacks, spells and the Fire Breath trigger |

## Turn logs

Each session writes one file to `logs/` (for example `logs/20261012-101500-a1b2c3.jsonl`), with one JSON line per turn: player input, raw LLM outputs, parsed action, validation result, dice rolls, state before and after, narration, guardrail triggers and turn latency. The `logs/` folder is gitignored.

## Project layout

```
mini_dm/
  __init__.py
  config.py        # loads config.json
  engine.py        # state, dice, rules, boss policy
  llm.py           # Ollama client, intent and narration calls
  guardrails.py    # input, output and integrity checks
  turnlog.py       # JSONL turn log
  app.py           # Gradio chat UI and status panel
  simulate.py      # balance simulation, random PC policy, no LLM
  prompts/
    intent.txt
    narration.txt
tests/
logs/              # JSONL turn logs (gitignored)
config.json        # model name, temperatures, seed, limits
requirements.txt
```

## Documents

- [ProjectRequirements.md](ProjectRequirements.md): requirements, guardrails, rules, stats and scope
- [docs/report.md](docs/report.md): what type of chatbot this is, and why it needs guardrails
