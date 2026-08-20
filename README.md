# KesCode

KesCode is a Python CLI that runs a coding task against a workspace with
workspace-bound tools:

```bash
kescode "Write a hello.py file" --workspace ./work
```

Set `OPENAI_API_KEY` in a `.env` file or in the environment. The model defaults
to `gpt-4o-mini` and can be overridden with `OPENAI_MODEL` or `--model`.

For the interactive multi-turn TUI:

```bash
kescode
```

The `tui` subcommand is also available:

```bash
kescode tui
```
