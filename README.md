# Personal AI CLI Assistant

A Linux CLI chatbot that runs on **Ollama Cloud**, falling back to **Groq**
automatically if Ollama Cloud is rate-limited or unavailable. Includes a
`code` command that can edit a file and commit the change via git.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and add your OLLAMA_API_KEY and GROQ_API_KEY
```

Get keys:
- Ollama Cloud: https://ollama.com (account settings → API keys)
- Groq: https://console.groq.com/keys

The Groq client retries a small fallback list automatically if your configured
`GROQ_MODEL` is unavailable. The default is `llama-3.1-70b-versatile`, and you
can override the list with `GROQ_MODEL_FALLBACKS` if needed.

## Usage

### Chat

```bash
python cli.py chat
```

Interactive REPL. Type `exit` or `quit` to leave.

### Code edits + commit (single or multiple files)

```bash
python cli.py code "add input validation to the parse function" -f app.py
```

For anything that spans more than one file, pass multiple `-f` flags — the
model sees all the files together in one call, so it can keep things like
function names, imports, and types consistent across them instead of
editing each file blind to the others:

```bash
python cli.py code "add a User model and wire it into the API" \
  -f models/user.py -f api/routes.py
```

`-f` also accepts paths that don't exist yet — useful when the change
requires a new file (e.g. scaffolding a new module).

This will:
1. Send all the specified files (existing content, or "(new file)") + your
   instruction to the model in one call
2. Show you a unified diff per file
3. Ask for confirmation before writing any files
4. Ask for confirmation before `git add` + `git commit` (one commit for the
   whole set of changes)
5. Optionally push, if you pass `--push` (still asks to confirm unless
   you also pass `--yes`)

```bash
# skip all confirmation prompts (use with care)
python cli.py code "fix the bug" -f file.py --yes --push
```

Note: `code` operates on one file at a time and expects the file to already
be inside a git repo you have push access to (via SSH key or a git
credential helper — this tool shells out to your local `git`, it doesn't
call the GitHub API directly).

### Branches

```bash
python cli.py branch new feature-x          # create + switch
python cli.py branch new feature-x --from main
python cli.py branch list
python cli.py branch switch main
```

### Merging

```bash
python cli.py merge feature-x                # merge feature-x into current branch
python cli.py merge feature-x --push          # merge, then push current branch
python cli.py merge feature-x --yes           # skip the "proceed?" prompt
```

The merge command refuses to run if your working tree has uncommitted
changes (commit or stash first). If the merge produces conflicts, it does
**not** try to resolve them for you — it stops, shows you which files
conflicted, and leaves the repo in git's normal conflict state so you can
resolve by hand (`git status`, edit the files, `git add`, `git commit`). If
you decline the abort prompt, it stays that way; nothing is force-resolved.

## How the fallback works

`llm_client.py` tries Ollama Cloud first. On a rate limit, timeout, or error
response, it automatically retries the same request against Groq. You'll see
a `[warn]` line on stderr when a fallback happens.

## Extending it

- Swap models by editing `OLLAMA_MODEL` / `GROQ_MODEL` in `.env`
- If Groq returns `model_not_found`, the client retries the models listed in
   `GROQ_MODEL_FALLBACKS`
- Add more subcommands to `cli.py` (e.g. a `review` command that just
  comments on a diff without writing it)
- Add streaming output by switching `stream: False` in `llm_client.py` and
  handling chunked responses
