"""
Personal AI CLI assistant.

Commands:
  chat                    Interactive chat REPL (Ollama Cloud -> Groq fallback)
  code <instruction>      Ask the AI to create/edit one or more files in a
                           single call (so it can keep cross-file references
                           consistent), review diffs, then commit.
  branch new/list/switch   Local branch management
  merge <branch>           Merge a branch into the current one

Examples:
  python cli.py chat
  python cli.py code "add error handling around the DB call" -f app.py
  python cli.py code "add a User model and wire it into the API" \\
      -f models/user.py -f api/routes.py
  python cli.py code "scaffold a new /health endpoint module" -f api/health.py --push
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

import click

import github_ops
from llm_client import ProviderError, chat as llm_chat

SYSTEM_PROMPT_CHAT = (
    "You are a helpful, concise personal assistant running from a Linux CLI."
)

FILE_BLOCK_START = "===FILE:"
FILE_BLOCK_END = "===END==="

SYSTEM_PROMPT_CODE = f"""You are a precise coding assistant working across a small set \
of files in one repository. You will be given each file's path and its full \
current content (or "(new file)" if it doesn't exist yet), followed by an \
instruction describing the change to make.

Consider how the files relate to each other (shared function names, \
imports, types) and keep them consistent with each other.

Respond with ONLY one block per file you are creating or changing, in \
exactly this format, and nothing else — no explanations, no markdown code \
fences outside the blocks:

{FILE_BLOCK_START} <path>
<full updated file content>
{FILE_BLOCK_END}

Repeat that block for each file. Always output the COMPLETE content of each \
file, not a diff or partial snippet. Omit files you are not changing.
"""


def _parse_file_blocks(text: str) -> dict[str, str]:
    """Parse the model's ===FILE: path=== ... ===END=== blocks into a dict."""
    pattern = re.compile(
        re.escape(FILE_BLOCK_START) + r"\s*(.+?)\s*\n(.*?)\n" + re.escape(FILE_BLOCK_END),
        re.DOTALL,
    )
    results = {}
    for match in pattern.finditer(text):
        path = match.group(1).strip()
        content = match.group(2)
        results[path] = content
    return results


@click.group()
def cli():
    """Personal AI CLI assistant (Ollama Cloud + Groq fallback)."""
    pass


@cli.command()
def chat():
    """Start an interactive chat session."""
    click.echo("Chat started. Type 'exit' or 'quit' to leave.\n")
    history = [{"role": "system", "content": SYSTEM_PROMPT_CHAT}]

    while True:
        try:
            user_input = click.prompt("you", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            click.echo("\nBye.")
            break

        if user_input.strip().lower() in {"exit", "quit"}:
            click.echo("Bye.")
            break

        history.append({"role": "user", "content": user_input})

        try:
            response = llm_chat(history)
        except ProviderError as e:
            click.secho(f"[error] {e}", fg="red")
            continue

        click.secho(f"assistant ({response.provider})> ", fg="cyan", nl=False)
        click.echo(response.text)
        history.append({"role": "assistant", "content": response.text})


@cli.command()
@click.argument("instruction")
@click.option(
    "-f", "--file", "filepaths", multiple=True, required=True,
    help="File to include (repeatable). Can be an existing file or a new path to create.",
)
@click.option("--push", is_flag=True, help="Push to remote after committing.")
@click.option("--yes", is_flag=True, help="Skip confirmation prompts (use with care).")
def code(instruction: str, filepaths: tuple[str, ...], push: bool, yes: bool):
    """
    Ask the AI to create/update one or more FILES according to INSTRUCTION,
    in a single model call so cross-file references stay consistent. Shows
    a diff per file, then optionally commits (and pushes) via git.
    """
    files = [Path(p).resolve() for p in filepaths]

    originals: dict[Path, str | None] = {}
    for f in files:
        originals[f] = f.read_text() if f.exists() else None

    # Find repo root starting from a directory that actually exists yet —
    # a target file's parent may not exist if it's a new file to be created.
    def _nearest_existing_dir(p: Path) -> Path:
        d = p.parent
        while not d.exists():
            d = d.parent
        return d

    try:
        repo_root = github_ops.find_repo_root(_nearest_existing_dir(files[0]))
    except github_ops.GitError:
        repo_root = None

    file_sections = []
    for f in files:
        content = originals[f] if originals[f] is not None else "(new file)"
        file_sections.append(f"Path: {f.name}\n\n{content}")

    user_content = f"Instruction: {instruction}\n\n" + "\n\n---\n\n".join(file_sections)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_CODE},
        {"role": "user", "content": user_content},
    ]

    click.echo(f"Asking the model to update {len(files)} file(s) ...")
    try:
        response = llm_chat(messages)
    except ProviderError as e:
        click.secho(f"[error] {e}", fg="red")
        return

    updates = _parse_file_blocks(response.text)
    if not updates:
        click.secho("Model didn't return any recognizable file blocks. Raw response:", fg="yellow")
        click.echo(response.text)
        return

    # Map returned block names back to the resolved paths we sent, by filename.
    by_name = {f.name: f for f in files}
    changes: dict[Path, str] = {}
    for name, new_content in updates.items():
        target = by_name.get(name) or by_name.get(Path(name).name)
        if target is None:
            # Model introduced a file we didn't ask about — resolve relative
            # to the first file's directory.
            target = (files[0].parent / name).resolve()
        changes[target] = new_content

    any_diff = False
    for f, new_content in changes.items():
        original = originals.get(f)
        if original is not None and original.strip() == new_content.strip():
            continue
        any_diff = True
        label = f.name if f in originals else str(f)
        click.secho(f"\n--- {label} ---", fg="cyan")
        old_lines = (original or "").splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{label}", tofile=f"b/{label}")
        click.echo("".join(diff))

    if not any_diff:
        click.echo("No changes suggested.")
        return

    if not yes and not click.confirm("\nApply these changes?"):
        click.echo("Discarded.")
        return

    written = []
    for f, new_content in changes.items():
        original = originals.get(f)
        if original is not None and original.strip() == new_content.strip():
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(new_content)
        written.append(f)
        click.secho(f"Updated {f}", fg="green")

    if repo_root is None:
        click.echo("Not inside a git repo — skipping commit.")
        return

    if not yes and not click.confirm("Stage and commit these changes?"):
        click.echo("Left uncommitted.")
        return

    github_ops.stage_all(repo_root)
    commit_message = f"AI edit: {instruction}"
    try:
        github_ops.commit(repo_root, commit_message)
        click.secho(f"Committed: {commit_message}", fg="green")
    except github_ops.GitError as e:
        click.secho(f"[error] {e}", fg="red")
        return

    if push:
        if not yes and not click.confirm("Push to remote now?"):
            click.echo("Not pushed.")
            return
        try:
            branch = github_ops.current_branch(repo_root)
            github_ops.push(repo_root, branch=branch)
            click.secho(f"Pushed to {branch}.", fg="green")
        except github_ops.GitError as e:
            click.secho(f"[error] {e}", fg="red")


@cli.group()
def branch():
    """Create, list, or switch branches."""
    pass


@branch.command("new")
@click.argument("name")
@click.option("--from", "from_branch", default=None, help="Base branch (defaults to current).")
@click.option("--path", "repo_path", type=click.Path(exists=True, file_okay=False), default=".")
def branch_new(name: str, from_branch: str | None, repo_path: str):
    """Create and switch to a new branch."""
    try:
        root = github_ops.find_repo_root(Path(repo_path).resolve())
    except github_ops.GitError as e:
        click.secho(f"[error] {e}", fg="red")
        return

    if github_ops.branch_exists(root, name):
        click.secho(f"Branch '{name}' already exists.", fg="yellow")
        if click.confirm(f"Switch to '{name}' instead?"):
            github_ops.checkout_branch(root, name)
        return

    try:
        github_ops.create_branch(root, name, from_branch=from_branch)
        click.secho(f"Created and switched to '{name}'.", fg="green")
    except github_ops.GitError as e:
        click.secho(f"[error] {e}", fg="red")


@branch.command("list")
@click.option("--path", "repo_path", type=click.Path(exists=True, file_okay=False), default=".")
def branch_list(repo_path: str):
    """List local branches."""
    try:
        root = github_ops.find_repo_root(Path(repo_path).resolve())
    except github_ops.GitError as e:
        click.secho(f"[error] {e}", fg="red")
        return

    current = github_ops.current_branch(root)
    for b in github_ops.list_branches(root):
        marker = "* " if b == current else "  "
        click.echo(f"{marker}{b}")


@branch.command("switch")
@click.argument("name")
@click.option("--path", "repo_path", type=click.Path(exists=True, file_okay=False), default=".")
def branch_switch(name: str, repo_path: str):
    """Switch to an existing branch."""
    try:
        root = github_ops.find_repo_root(Path(repo_path).resolve())
        github_ops.checkout_branch(root, name)
        click.secho(f"Switched to '{name}'.", fg="green")
    except github_ops.GitError as e:
        click.secho(f"[error] {e}", fg="red")


@cli.command()
@click.argument("source_branch")
@click.option("--path", "repo_path", type=click.Path(exists=True, file_okay=False), default=".")
@click.option("--push", is_flag=True, help="Push the current branch after a successful merge.")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def merge(source_branch: str, repo_path: str, push: bool, yes: bool):
    """Merge SOURCE_BRANCH into the current branch."""
    try:
        root = github_ops.find_repo_root(Path(repo_path).resolve())
    except github_ops.GitError as e:
        click.secho(f"[error] {e}", fg="red")
        return

    if not github_ops.branch_exists(root, source_branch):
        click.secho(f"Branch '{source_branch}' doesn't exist locally.", fg="red")
        return

    if not github_ops.is_working_tree_clean(root):
        click.secho("Working tree has uncommitted changes — commit or stash first.", fg="red")
        return

    target = github_ops.current_branch(root)
    click.echo(f"About to merge '{source_branch}' into '{target}'.")

    if not yes and not click.confirm("Proceed?"):
        click.echo("Cancelled.")
        return

    try:
        output = github_ops.merge_branch(root, source_branch)
        click.echo(output)
    except github_ops.GitError as e:
        click.secho(f"[error] {e}", fg="red")
        return

    if github_ops.has_merge_conflicts(root):
        click.secho("Merge conflicts detected. Resolve them manually, then commit.", fg="red")
        click.echo("Files with conflicts:")
        click.echo(github_ops.get_status(root))
        if not yes and click.confirm("Abort the merge instead?"):
            github_ops.abort_merge(root)
            click.echo("Merge aborted, back to a clean state.")
        return

    click.secho(f"Merged '{source_branch}' into '{target}'.", fg="green")

    if push:
        if not yes and not click.confirm(f"Push '{target}' to remote now?"):
            click.echo("Not pushed.")
            return
        try:
            github_ops.push(root, branch=target)
            click.secho(f"Pushed '{target}'.", fg="green")
        except github_ops.GitError as e:
            click.secho(f"[error] {e}", fg="red")


if __name__ == "__main__":
    cli()
