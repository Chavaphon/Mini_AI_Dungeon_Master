# Mini_AI_Dungeon_Master
A miniature version of AI_Dungeon_Master

## Balance simulation

Simulate 1,000 seeded fights with a random PC policy (no LLM or Ollama needed) and print the PC win rate, fight length and the stats used:

```bash
.venv/Scripts/python -m mini_dm.simulate
```

The fight count and seed come from `config.json`.
