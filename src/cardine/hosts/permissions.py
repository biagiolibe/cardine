"""Host-neutral protected-path inventory and role-action policy.

Pure and fail-closed, the opposite of `read_guard`: an unparsable or unknown
writer form is denied, and nothing here writes, registers a hook, or reads a
credential. Host adapters render this policy; only a host evaluating a probe
can prove it is in force (`proof_enforces`), never the rendered text.

The declared limit of decision 14 stays: a same-user agent that bypasses the
host rules can rewrite receipts, and this module claims nothing against it.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.layout import names

ROLES = ("implementer", "reviewer")
PROTECTED_BRANCHES = ("main", "master")
STAGE = re.compile(r"^\..+\.stage$")  # adjacent `.<filename>.<operation>.<index>.stage`
NATIVE_WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
HOSTS = ("claude", "codex")
# Codex edits files through its patch tool and runs commands through its shell tool.
CODEX_NATIVE_WRITE_TOOLS = ("apply_patch",)
CODEX_SHELL = "shell"

# Action prefixes as non-option CLI words, matched as an ordered subsequence so
# reordered options and option values cannot hide them.
DEVELOPER_ONLY = (("cancel",), ("abort",), ("task", "contract"), ("task", "transition"),
                  ("task", "state"), ("setup",), ("upgrade",), ("lock",), ("self-update",), ("authorize",))
INTEGRATION = (("worktree", "integrate"), ("worktree", "cleanup"), ("worktree", "advance"),
               ("worktree", "repair-base"))
REVIEWER_DENIED = (("execution", "start"), ("execution", "deliver"), ("execution", "validate"),
                   ("task", "close"))
VERDICT = ("review", "verdict")

_REDIRECTS = {">", ">>", ">|", "&>", "&>>", ">&"}
_WRAPPERS = {"command", "exec", "nohup", "time", "nice", "builtin", "stdbuf", "timeout", "env"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "php", "deno", "bun", "lua", "osascript"}
_INLINE = {"-c", "-e", "-E", "-r", "--eval", "-p"}
_WRITE_ALL = {"rm", "rmdir", "unlink", "mv", "tee", "touch", "truncate", "chmod", "chown", "chgrp",
              "mkdir", "mkfifo", "shred", "patch", "sponge", "ed", "ex", "vi", "vim", "nano", "emacs",
              "split", "csplit", "curl", "wget", "tar", "unzip", "zip", "cpio", "mktemp", "ln", "dd"}
_WRITE_DESTINATION = {"cp", "install", "rsync", "ditto"}
_GIT_MUTATING = {"checkout", "restore", "rm", "mv", "clean", "stash", "reset", "apply", "am"}
_GIT_REVIEWER_DENIED = _GIT_MUTATING | {"add", "commit", "merge", "switch", "push", "rebase",
                                         "cherry-pick", "branch", "tag", "worktree", "update-ref", "config"}
_READ_ONLY = {"cat", "ls", "head", "tail", "wc", "grep", "rg", "find", "diff", "stat", "file", "pwd",
              "echo", "printf", "sort", "uniq", "cut", "tr", "less", "more", "which", "test", "true",
              "false", "date", "basename", "dirname", "realpath", "readlink", "set", "cd"}
_OBFUSCATION = ("base64", "b64decode", "chr(", "eval(", "exec(", "__import__", "getattr(", "fromhex",
                "compile(", "importlib")
_WRITE_APIS = ("write", "open(", "unlink", "remove", "rename", "replace", "rmtree", "copy", "move",
               "symlink", "chmod", "truncate", "mkdir", "touch", "system", "popen", "subprocess",
               "fs.", "File.")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


ALLOW = Decision(True)


def _deny(reason: str) -> Decision:
    return Decision(False, reason)


# -- Protected-path inventory -------------------------------------------------

def checkout_roots(checkout: Path) -> tuple[Path, ...]:
    """Protected subtrees and files inside one checkout, from the real layout and resolvers."""
    checkout = Path(checkout)
    n = names()
    tasks = receipts.safe_path(checkout.resolve(), f"{n.tasks_path.as_posix()}/x").parent
    evidence = checkout / n.execution_evidence_path("x").parent
    files = (n.project_declaration_path, n.task_identity_path, n.candidate_validation_path, n.flow_targets_path)
    return (tasks, evidence, *(checkout / item for item in files))


def external_roots(common_dir: Path) -> tuple[Path, ...]:
    """Receipt locations outside a checkout: the Git common directory and the host-operation directory."""
    return (receipts.safe_path(Path(common_dir).resolve(), "cardine-operations/x").parent,
            receipts.host_path("x", common_dir).parent)


def protected_roots(checkouts, common_dir: Path | None = None) -> tuple[Path, ...]:
    """Every protected root of the primary checkout, linked worktrees, and shared locations.

    Each root appears as given and resolved, so `/var` and `/private/var` style
    aliases of one directory are both listed.
    """
    found: dict[str, Path] = {}
    roots = [root for checkout in checkouts for root in checkout_roots(checkout)]
    if common_dir is not None:
        roots.extend(external_roots(common_dir))
    for root in roots:
        for form in (Path(os.path.abspath(root)), Path(os.path.realpath(root))):
            found[str(form)] = form
            text = str(form)
            for prefix in ("/private/var", "/private/tmp", "/private/etc"):
                if text.startswith(prefix + "/") or text == prefix:
                    stripped = Path(text[len("/private"):])
                    found[str(stripped)] = stripped
    return tuple(found[key] for key in sorted(found))


def relative_protected() -> tuple[str, ...]:
    """Project-relative protected paths as POSIX text; the first two are whole subtrees (`/**`)."""
    probe = Path("/probe")
    return tuple(root.relative_to(probe).as_posix() + ("/**" if position < 2 else "")
                 for position, root in enumerate(checkout_roots(probe)))


def _real(text: str, cwd: Path) -> Path:
    path = Path(os.path.expanduser(text))
    return Path(os.path.realpath(path if path.is_absolute() else Path(cwd) / path))


def is_protected(text: str, roots, cwd: Path) -> bool:
    """True when the canonical destination, after symlinks and `..`, lies in a protected root."""
    real = _real(text, cwd)
    if STAGE.match(real.name):
        return True
    return any(real == Path(os.path.realpath(root)) or Path(os.path.realpath(root)) in real.parents
               for root in roots)


def _target(text: str, roots, cwd: Path) -> Decision:
    """Classify one candidate write target; dynamic text is denied, not guessed."""
    if text in ("/dev/null", "/dev/stdout", "/dev/stderr", "-"):
        return ALLOW
    if any(mark in text for mark in ("$", "`")):
        return _deny("dynamic path in a writer")
    if is_protected(text, roots, cwd):
        return _deny("protected path: " + text)
    if any(mark in text for mark in "*?["):
        base = Path(text) if os.path.isabs(text) else Path(cwd) / text
        for match in glob.glob(str(base)):
            if is_protected(match, roots, cwd):
                return _deny("protected path: " + match)
    return ALLOW


# -- Command evaluation -------------------------------------------------------

def _scan_newlines(command: str) -> str:
    """Replace an unquoted newline with a separator; quoted newlines stay data."""
    out, quote = [], ""
    for index, char in enumerate(command):
        escaped = index > 0 and command[index - 1] == "\\" and quote != "'"
        if quote:
            if char == quote and not escaped:
                quote = ""
        elif char in "'\"" and not escaped:
            quote = char
        elif char == "\n":
            char = " ; "
        out.append(char)
    return "".join(out)


def _strip_heredocs(command: str) -> tuple[str, bool]:
    marks = list(re.finditer(r"<<-?\s*(['\"]?)(\w+)\1", command))
    if not marks:
        return command, False
    lines, out, pending = command.split("\n"), [], []
    for line in lines:
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        out.append(line)
        pending.extend(match.group(2) for match in re.finditer(r"<<-?\s*(['\"]?)(\w+)\1", line))
    return "\n".join(out), True


def _substitutions(command: str) -> tuple[str, list[str]]:
    """Pull `$( ... )` and backtick bodies out so each is evaluated as its own command."""
    bodies, out, index = [], [], 0
    while index < len(command):
        if command.startswith("$(", index) or command.startswith("<(", index) or command.startswith(">(", index):
            depth, end = 1, index + 2
            while end < len(command) and depth:
                depth += {"(": 1, ")": -1}.get(command[end], 0)
                end += 1
            if depth:
                raise CardineError("unbalanced substitution")
            bodies.append(command[index + 2:end - 1])
            out.append(" SUBST ")
            index = end
        elif command[index] == "`":
            end = command.find("`", index + 1)
            if end < 0:
                raise CardineError("unbalanced substitution")
            bodies.append(command[index + 1:end])
            out.append(" SUBST ")
            index = end + 1
        else:
            out.append(command[index])
            index += 1
    return "".join(out), bodies


def _segments(command: str) -> list[tuple[list[str], list[str]]]:
    """Simple commands as (argv, redirect targets); raises CardineError when unparsable."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[tuple[list[str], list[str]]] = [([], [])]
    redirect = False
    try:
        tokens = list(lexer)
    except ValueError as error:
        raise CardineError(str(error)) from error
    for token in tokens:
        if redirect:
            redirect = False
            if not re.fullmatch(r"\d+|-", token):
                segments[-1][1].append(token)
            continue
        if token in _REDIRECTS:
            redirect = True
        elif set(token) <= set("();&|") and token:
            if token not in ("(", ")") or segments[-1][0]:
                segments.append(([], []))
        elif set(token) <= set("<") or token in ("<&", "<>"):
            continue
        else:
            segments[-1][0].append(token)
    if redirect:
        raise CardineError("redirect without a target")
    return [item for item in segments if item[0] or item[1]]


def _positional(argv: list[str]) -> list[str]:
    return [token for token in argv if not token.startswith("-")]


def _subsequence(words: tuple[str, ...], tokens: list[str]) -> bool:
    position = 0
    for token in tokens:
        if position < len(words) and token == words[position]:
            position += 1
    return position == len(words)


def _is_cardine(argv: list[str]) -> bool:
    name = os.path.basename(argv[0])
    if name == "cardine":
        return True
    if name == "python" or name.startswith("python"):
        return argv[1:3] == ["-m", "cardine"] or any(os.path.basename(t) == "cardine_cli.py" for t in argv[1:3])
    return False


def _cardine_action(argv: list[str], role: str) -> Decision:
    words = _positional(argv[1:])
    if _subsequence(VERDICT, words):
        return _deny("verdicts are recorded by cardine run or by the developer with --owner")
    for action in DEVELOPER_ONLY + INTEGRATION:
        if _subsequence(action, words):
            return _deny("developer or integration operation: " + " ".join(action))
    if role == "reviewer":
        for action in REVIEWER_DENIED:
            if _subsequence(action, words):
                return _deny("implementation operation for a reviewer: " + " ".join(action))
    return ALLOW


def _git(argv: list[str], role: str, roots, cwd: Path) -> Decision:
    index, work = 1, Path(cwd)
    while index < len(argv) and argv[index].startswith("-"):
        option = argv[index]
        if option in ("-C", "--git-dir", "--work-tree", "-c", "--namespace", "--exec-path"):
            value = argv[index + 1] if index + 1 < len(argv) else ""
            if option in ("-C", "--git-dir", "--work-tree") and (not value or is_protected(value, roots, work)):
                return _deny("git redirected into a protected path")
            if option == "-C":
                work = _real(value, work)
            index += 2
        else:
            index += 1
    if index >= len(argv):
        return ALLOW
    sub, rest = argv[index], argv[index + 1:]
    if role == "reviewer" and sub in _GIT_REVIEWER_DENIED:
        return _deny("git " + sub + " is not a reviewer action")
    if sub == "push":
        return _push(rest, role)
    if sub in _GIT_MUTATING:
        for token in rest:
            if not token.startswith("-") and (verdict := _target(token, roots, work)) is not ALLOW:
                return verdict
    return ALLOW


def _push(rest: list[str], role: str) -> Decision:
    for token in rest:
        if token.startswith("--"):
            if token.split("=")[0] in ("--force", "--force-with-lease", "--force-if-includes", "--mirror",
                                       "--delete", "--all", "--tags", "--prune", "--follow-tags"):
                return _deny("destructive or broad push: " + token)
        elif token.startswith("-") and set(token[1:]) & set("fd"):
            return _deny("destructive push: " + token)
    positional = _positional(rest)
    if role == "reviewer":
        return _deny("a reviewer cannot push")
    refspecs = positional[1:]
    if not refspecs:
        return _deny("push without an explicit refspec")
    for refspec in refspecs:
        source, colon, destination = refspec.lstrip("+").partition(":")
        target = (destination if colon else source).removeprefix("refs/heads/")
        if target in PROTECTED_BRANCHES or target in ("", "HEAD") or refspec.startswith(":"):
            return _deny("direct push to a protected or ambiguous destination: " + refspec)
    return ALLOW


def _inline(argv: list[str], role: str, roots, heredoc: bool) -> Decision:
    code = " ".join(argv[1:])
    fragments = [".cardine", "cardine-operations", ".stage", *map(str, roots)]
    if any(fragment in code for fragment in fragments):
        return _deny("interpreter code names a protected path")
    if any(token in code for token in _OBFUSCATION):
        return _deny("interpreter code builds code or paths dynamically")
    if role == "reviewer" and any(token in code for token in _WRITE_APIS):
        return _deny("interpreter code may write; reviewers are read-only")
    return ALLOW


def _segment(argv: list[str], redirects: list[str], role: str, roots, cwd: Path, heredoc: bool, depth: int) -> Decision:
    for target in redirects:
        if role == "reviewer" and target not in ("/dev/null", "/dev/stdout", "/dev/stderr"):
            return _deny("reviewers are read-only: redirect to " + target)
        if (verdict := _target(target, roots, cwd)) is not ALLOW:
            return verdict
    while argv and re.fullmatch(r"[A-Za-z_]\w*=.*", argv[0]):
        argv = argv[1:]
    if not argv:
        return ALLOW
    if depth > 8:
        return _deny("wrapper nesting too deep")
    name = os.path.basename(argv[0])
    if name in ("sudo", "su", "doas", "eval", "source", ".", "ssh"):
        return _deny("privileged or dynamic wrapper: " + name)
    if name in _WRAPPERS:
        rest = argv[1:]
        while rest and (rest[0].startswith("-") or re.fullmatch(r"[A-Za-z_]\w*=.*", rest[0])
                        or (name in ("timeout", "nice", "stdbuf") and re.fullmatch(r"[\d.]+[smhd]?", rest[0]))):
            rest = rest[1:]
        return _segment(rest, [], role, roots, cwd, heredoc, depth + 1)
    if name == "xargs":
        rest = argv[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in ("-I", "-n", "-P", "-d", "-L", "-s") else rest[1:]
        inner = rest[0] if rest else "echo"
        if os.path.basename(inner) in _WRITE_ALL | _WRITE_DESTINATION | _SHELLS | _INTERPRETERS | {"git", "sed", "cardine"}:
            return _deny("xargs feeds unknown paths to " + inner)
        return _segment(rest, [], role, roots, cwd, heredoc, depth + 1)
    if name in _SHELLS:
        flags = [token for token in argv[1:] if token.startswith("-")]
        if "-c" in flags or any(re.fullmatch(r"-[a-z]*c[a-z]*", flag) for flag in flags):
            position = max(i for i, token in enumerate(argv) if re.fullmatch(r"-[a-z]*c[a-z]*", token))
            if position + 1 >= len(argv):
                return _deny("shell -c without a command")
            return evaluate_command(argv[position + 1], role=role, roots=roots, cwd=cwd, depth=depth + 1)
        return _deny("shell reads a script or standard input")
    if _is_cardine(argv):
        return _cardine_action(argv, role)
    if name in _INTERPRETERS or name.startswith("python"):
        if heredoc or any(token in _INLINE or token == "-" for token in argv[1:]):
            return _inline(argv, role, roots, heredoc)
        return _args_clear(argv[1:], role, roots, cwd)
    if name == "git":
        return _git(argv, role, roots, cwd)
    if name == "sed" or name == "perl" or name == "ruby" or name == "awk":
        in_place = any(re.fullmatch(r"-[A-Za-z]*i.*", t) or t == "--in-place" or t.startswith("--in-place=")
                       or t == "inplace" for t in argv[1:])
        if in_place:
            return _args_clear(argv[1:], role, roots, cwd, writer=True)
        return ALLOW
    if name in _WRITE_ALL:
        return _writer(name, argv[1:], role, roots, cwd, destination_only=False)
    if name in _WRITE_DESTINATION:
        return _writer(name, argv[1:], role, roots, cwd, destination_only=True)
    if name in _READ_ONLY:
        return ALLOW
    # Unknown program: a protected path argument refuses it; otherwise it is ordinary work.
    return _args_clear(argv[1:], role, roots, cwd)


def _writer(name: str, args: list[str], role: str, roots, cwd: Path, *, destination_only: bool) -> Decision:
    if role == "reviewer":
        return _deny("reviewers are read-only: " + name)
    values = []
    for token in args:
        if token.startswith("--") and "=" in token:
            values.append(token.split("=", 1)[1])
        elif re.match(r"^(of|if)=", token):
            values.append(token.split("=", 1)[1])
        elif not token.startswith("-"):
            values.append(token)
    if destination_only and values:
        explicit = [args[i + 1] for i, token in enumerate(args[:-1]) if token in ("-t", "--target-directory")]
        values = explicit or values[-1:]
    for value in values:
        if (verdict := _target(value, roots, cwd)) is not ALLOW:
            return verdict
    return ALLOW


def _args_clear(args: list[str], role: str, roots, cwd: Path, writer: bool = False) -> Decision:
    if writer and role == "reviewer":
        return _deny("reviewers are read-only: in-place edit")
    for token in args:
        value = token.split("=", 1)[1] if token.startswith("--") and "=" in token else token
        if value.startswith("-") or not value or ("/" not in value and "." not in value[:1] and not writer):
            continue
        if is_protected(value, roots, cwd):
            return _deny("protected path argument: " + value)
    return ALLOW


def evaluate_command(command: str, *, role: str, roots, cwd: Path, depth: int = 0) -> Decision:
    """Allow or refuse one shell command for a role session; anything unparsable is refused."""
    if role not in ROLES or not isinstance(command, str) or not command.strip() or "\0" in command:
        return _deny("unparsable command or unknown role")
    try:
        text, heredoc = _strip_heredocs(command)
        text, bodies = _substitutions(_scan_newlines(text))
        for body in bodies:
            if not (verdict := evaluate_command(body, role=role, roots=roots, cwd=cwd, depth=depth + 1)).allowed:
                return verdict
        for argv, redirects in _segments(text):
            if not (verdict := _segment(argv, redirects, role, roots, Path(cwd), heredoc, depth)).allowed:
                return verdict
    except (CardineError, OSError, ValueError) as error:
        return _deny("unparsable command: " + str(error))
    return ALLOW


def evaluate_tool(tool: str, tool_input, *, role: str, roots, cwd: Path) -> Decision:
    """Native tool call: edits, and the shell, are evaluated; unknown tools naming a protected path are refused."""
    if role not in ROLES or not isinstance(tool_input, dict):
        return _deny("unparsable tool call or unknown role")
    if tool in ("Bash", CODEX_SHELL):
        return evaluate_command(tool_input.get("command"), role=role, roots=roots, cwd=cwd)
    paths = [tool_input[key] for key in ("file_path", "notebook_path", "path") if key in tool_input]
    if tool in NATIVE_WRITE_TOOLS or tool in CODEX_NATIVE_WRITE_TOOLS:
        if role == "reviewer":
            return _deny("reviewers are read-only: " + tool)
        if not paths or not all(isinstance(path, str) and path for path in paths):
            return _deny("native write without a path")
    elif tool in ("Read", "Grep", "Glob", "LS", "WebSearch", "WebFetch", "TodoWrite"):
        return ALLOW
    for path in paths:
        if not isinstance(path, str) or (verdict := _target(path, roots, cwd)) is not ALLOW:
            return verdict if isinstance(path, str) else _deny("non-text path")
    return ALLOW


# -- Role profiles and host-evaluated proof ----------------------------------

def probe_matrix(role: str, host: str = "claude") -> dict[str, tuple]:
    """Probes a host must evaluate: name -> (tool, input, expected 'deny' | 'allow').

    Probe names and expectations are host-neutral; only the native tool names
    differ per host (the decision table), so one proof shape serves both hosts.
    """
    if role not in ROLES:
        raise CardineError("unknown role: " + role)
    if host not in HOSTS:
        raise CardineError("unknown host: " + host)
    matrix = _base_probe_matrix(role)
    if host == "claude":
        return matrix
    return {name: (CODEX_SHELL if tool == "Bash" else CODEX_NATIVE_WRITE_TOOLS[0], tool_input, verdict)
            for name, (tool, tool_input, verdict) in matrix.items()}


def _base_probe_matrix(role: str) -> dict[str, tuple]:
    if role == "reviewer":
        return {
            "write-worktree": ("Bash", {"command": "echo changed > tracked.txt", "target": "tracked.txt"}, "deny"),
            "write-state": ("Bash", {"command": "echo changed > .cardine/tasks/001.json", "target": ".cardine/tasks/001.json"}, "deny"),
            "write-git": ("Bash", {"command": "echo changed > .git/config", "target": ".git/config"}, "deny"),
            "verdict-developer": ("Bash", {"command": "cardine review verdict 001 APPROVE --owner"}, "deny"),
            "read-tracked": ("Bash", {"command": "cat tracked.txt"}, "allow"),
        }
    state, evidence = ".cardine/tasks/001.json", ".cardine/evidence/001.json"
    deny = {
        "push-main": ("Bash", {"command": "git push origin main"}, "deny"),
        "push-refspec": ("Bash", {"command": "git push origin HEAD:main"}, "deny"),
        "push-force-plus": ("Bash", {"command": "git push origin +main"}, "deny"),
        "push-reordered": ("Bash", {"command": "git -C . push --force origin task-1"}, "deny"),
        "verdict-developer": ("Bash", {"command": "cardine review verdict 001 APPROVE --owner"}, "deny"),
        "cancel": ("Bash", {"command": "cardine cancel 001 --reason x"}, "deny"),
        "integrate": ("Bash", {"command": "cardine --project . worktree integrate finalize 001"}, "deny"),
        "edit-state": ("Edit", {"file_path": state}, "deny"),
        "write-evidence": ("Write", {"file_path": evidence}, "deny"),
        "notebook-state": ("NotebookEdit", {"notebook_path": state}, "deny"),
        "redirect": ("Bash", {"command": "echo {} > " + state}, "deny"),
        "append-chain": ("Bash", {"command": "true && echo {} >> " + state}, "deny"),
        "pipe-tee": ("Bash", {"command": "echo {} | tee " + state}, "deny"),
        "copy": ("Bash", {"command": "cp /tmp/x " + state}, "deny"),
        "move": ("Bash", {"command": "mv /tmp/x " + evidence}, "deny"),
        "remove": ("Bash", {"command": "rm " + state}, "deny"),
        "sed-in-place": ("Bash", {"command": "sed -i s/a/b/ " + state}, "deny"),
        "symlink": ("Bash", {"command": "ln -s " + state + " src/alias"}, "deny"),
        "interpreter": ("Bash", {"command": "python3 -c \"open('" + state + "','w')\""}, "deny"),
        "wrapper": ("Bash", {"command": "env sh -c 'echo {} > " + state + "'"}, "deny"),
    }
    controls = {
        "inspect-status": ("Bash", {"command": "git status"}, "allow"),
        "inspect-state": ("Bash", {"command": "cat " + state}, "allow"),
        "edit-source": ("Edit", {"file_path": "src/module.py"}, "allow"),
        "commit": ("Bash", {"command": "git commit -m message"}, "allow"),
    }
    if role == "implementer":
        controls["task-close"] = ("Bash", {"command": "cardine task close 001"}, "allow")
        controls["push-task-branch"] = ("Bash", {"command": "git push origin task-1"}, "allow")
        deny["review-submission"] = ("Bash", {"command": "cardine review verdict 001 APPROVE"}, "deny")
    else:
        deny["edit-source"] = ("Edit", {"file_path": "src/module.py"}, "deny")
        deny["push-task-branch"] = ("Bash", {"command": "git push origin task-1"}, "deny")
        deny["commit"] = ("Bash", {"command": "git commit -m message"}, "deny")
        del controls["edit-source"], controls["commit"]
    return {**deny, **controls}


@dataclass(frozen=True)
class RolePolicy:
    host: str
    role: str
    identity: str
    settings: dict
    digest: str


def policy_digest(host: str, role: str, settings: dict) -> str:
    body = json.dumps([host, role, settings, probe_matrix(role, host)], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass(frozen=True)
class HostProof:
    """Decisions a host reported for the probe matrix under one installed policy digest."""
    host: str
    identity: str
    digest: str
    decisions: dict


def proof_enforces(policy: RolePolicy, proof: HostProof | None) -> bool:
    """True only for a complete host proof of this exact policy; text and partial proofs never qualify."""
    if not isinstance(proof, HostProof):
        return False
    expected = {name: verdict for name, (_t, _i, verdict) in probe_matrix(policy.role, policy.host).items()}
    return (proof.host == policy.host and proof.identity == policy.identity and proof.digest == policy.digest
            and proof.decisions == expected)
