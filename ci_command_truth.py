#!/usr/bin/env python3
"""CI Command Truth — prove every `run:` command in GitHub workflows exists.

STATIC ONLY: this tool never executes anything from the scanned repository.
It reads workflow text, package.json, Makefiles, justfiles, Taskfiles and
checks that referenced files exist on disk. Python standard library only.

Guiding principle: when static resolution is genuinely uncertain, the
segment is SKIPPED with a named reason (and counted as skipped) rather
than flagged — this product dies by false alarms.

Exit codes: 0 = everything checked resolved, 1 = missing targets found,
2 = usage / parse error (including unparseable workflow files and
malformed resolver files, which are always listed explicitly — never a
silent pass).
"""
import argparse
import ast
import difflib
import fnmatch
import glob
import importlib.machinery
import json
import os
import re
import shlex
import sys
import urllib.parse

VERSION = "0.3.0"

MAX_FILE_BYTES = 1_000_000          # cap for any single file we read

BUILTINS = {
    "echo", "cd", "printf", "export", "set", "unset", "test", "[", "[[",
    "source", ".", "exit", "return", "true", "false", ":", "alias",
    "unalias", "local", "readonly", "declare", "typeset", "let", "shift",
    "umask", "wait", "eval", "exec", "trap", "pushd", "popd", "dirs",
    "jobs", "fg", "bg", "kill", "read", "break", "continue",
}
KEYWORDS = {
    "if", "then", "else", "elif", "fi", "for", "while", "until", "do",
    "done", "case", "esac", "in", "function", "select", "time", "!",
    "{", "}", "[[", "]]",
}
EXTERNAL = {
    # common system / CI tools with no repo-local resolution target
    "docker", "podman", "curl", "wget", "git", "gh", "sudo", "apt-get",
    "apt", "brew", "yum", "dnf", "apk", "jq", "yq", "sed", "awk", "grep",
    "egrep", "fgrep", "tar", "zip", "unzip", "gzip", "gunzip", "chmod",
    "chown", "mkdir", "cp", "mv", "rm", "rmdir", "ls", "cat", "head",
    "tail", "env", "xargs", "find", "sort", "uniq", "wc", "touch", "ln",
    "basename", "dirname", "realpath", "readlink", "date", "sleep",
    "which", "whereis", "hostname", "uname", "id", "whoami", "ps", "tee",
    "tr", "cut", "paste", "diff", "patch", "file", "stat", "du", "df",
    "ping", "ssh", "scp", "rsync", "gpg", "openssl", "sha256sum",
    "md5sum", "shasum", "base64", "xxd", "od", "hexdump", "timeout",
    "nohup", "nproc", "free", "locale", "printenv", "command", "hash",
    "cargo", "rustc", "go", "java", "javac", "mvn", "gradle", "dotnet",
    "ruby", "gem", "bundle", "php", "composer", "perl", "lua", "Rscript",
    "gcc", "g++", "cc", "clang", "cmake", "ninja", "meson", "bazel",
    "kubectl", "helm", "terraform", "ansible", "az", "gcloud", "aws",
    "heroku", "vercel", "netlify", "firebase", "flutter", "dart",
    "pytest", "tox", "nox", "poetry", "pipenv", "conda", "mamba",
    "virtualenv", "hatch", "pdm", "uv", "ruff", "mypy", "flake8",
    "black", "isort", "pylint", "coverage", "esphome", "pio",
    "platformio", "arduino-cli", "shellcheck", "actionlint", "hadolint",
    "yamllint", "pre-commit", "act", "codecov", "coveralls", "sonar-scanner",
    "node", "deno", "tsc", "eslint", "prettier", "jest", "vitest",
    "mocha", "webpack", "vite", "rollup", "gulp", "grunt", "nx", "lerna",
    "turbo", "serve", "http-server",
    # node/python handled specially only when followed by a file/module arg;
    # bare invocations fall through to here via the no-target rule anyway.
}
# Interpreters that ARE checked when followed by a file/module argument.
FILE_INTERPRETERS = {"bash", "sh", "zsh", "dash", "python", "python3",
                     "py", "node"}
PY_NAMES = {"python", "python3", "py"}
SHELL_NAMES = {"bash", "sh", "zsh", "dash"}
# Top-level modules commonly run as `python -m X` from an *installed*
# package rather than from the repo being scanned. Repo-local existence
# is always checked FIRST; this list is only a fallback and means
# "assumed installed" (documented in README/ANALYSIS).
KNOWN_EXTERNAL_MODULES = {
    "pip", "build", "pytest", "_pytest", "tox", "nox", "coverage",
    "setuptools", "wheel", "virtualenv", "poetry", "hatch", "pdm",
    "flake8", "black", "isort", "mypy", "pylint", "ruff", "sphinx",
    "mkdocs", "django", "flask", "gunicorn", "uvicorn", "celery",
    "ansible", "twine", "keyring", "pkg_resources", "ensurepip",
    "pipenv", "conda", "torch", "transformers", "jupyter", "notebook",
    "ipykernel", "langchain", "openai", "yt_dlp", "youtube_dl",
}

NPM_BUILTINS = {
    "install", "i", "ci", "add", "remove", "rm", "uninstall", "un",
    "update", "up", "publish", "pack", "init", "create", "config",
    "cache", "audit", "outdated", "ls", "list", "link", "unlink",
    "version", "help", "exec", "explore", "doctor", "fund", "owner",
    "access", "team", "profile", "token", "org", "search", "view",
    "info", "show", "whoami", "login", "logout", "ping", "star",
    "stars", "deprecate", "undeprecate", "dist-tag", "hook", "completion",
    "dedupe", "prune", "rebuild", "set", "get", "root", "prefix",
    "bin", "bugs", "docs", "edit", "home", "repo", "restart", "shrinkwrap",
}
NPM_SCRIPT_SHORTCUTS = {"test", "start", "stop", "restart", "t", "run-script"}
PNPM_BUILTINS = {
    "install", "i", "add", "remove", "rm", "update", "up", "publish",
    "pack", "init", "create", "dlx", "exec", "store", "config", "cache",
    "audit", "outdated", "ls", "list", "link", "unlink", "version",
    "help", "setup", "import", "fetch", "deploy", "patch", "patch-commit",
    "cat-file", "cat-index", "find-hash", "dedupe", "prune", "rebuild",
    "root", "bin", "whoami", "login", "logout", "server", "recursive",
    "multi", "m", "workspace", "supported-browserslist", "licenses",
    "ignored-builds", "approve-builds",
}
YARN_BUILTINS = {
    "install", "add", "remove", "init", "create", "global", "cache",
    "config", "info", "version", "versions", "help", "import", "link",
    "unlink", "publish", "pack", "audit", "outdated", "list", "why",
    "workspace", "workspaces", "generate-lock-entry", "autoclean",
    "check", "upgrade", "upgrade-interactive", "bin", "exec", "node",
    "set", "get", "dlx", "npm", "plugin", "sdks", "explain", "rebuild",
    "unplug", "stage", "patch", "patchCommit", "search", "constraints",
}


def _suggest(name, candidates):
    """Deterministic did-you-mean: at most one close match, or None.

    Scores every candidate with difflib ratios against a fixed cutoff;
    ties break toward the alphabetically first candidate (never
    difflib's larger-name tie-break), so the result never depends on
    candidate ordering. Advisory only — it never changes a verdict.
    """
    if not name:
        return None
    uniq = sorted({c for c in candidates if isinstance(c, str) and c != name})
    best, best_ratio = None, 0.6
    for cand in uniq:
        ratio = difflib.SequenceMatcher(None, name, cand).ratio()
        if ratio >= 0.6 and (best is None or ratio > best_ratio):
            best, best_ratio = cand, ratio
    return best


_EXTENSION_SUFFIXES = sorted(importlib.machinery.EXTENSION_SUFFIXES,
                             key=len, reverse=True)


def _compiled_stem(filename):
    """Stem if `filename` is `<stem><genuine extension suffix>`.

    Uses importlib's platform suffix list, so `mod.abi3.so` counts on
    Linux while `mod.pyd` (Windows-only) and `mod.notreal.so` do not.
    The stem itself must be dot-free (module names are).
    """
    for suffix in _EXTENSION_SUFFIXES:
        if filename.endswith(suffix):
            stem = filename[:-len(suffix)]
            if stem and "." not in stem:
                return stem
            return None
    return None


def read_capped(path):
    """Read up to the real MAX_FILE_BYTES cap.

    Returns (text, None) or (None, error). A file larger than the cap is
    an error ("oversized") — it is NEVER silently truncated.
    """
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None, "oversized"
        with open(path, "rb") as fh:
            data = fh.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            return None, "oversized"
        return data.decode("utf-8", errors="replace"), None
    except OSError as exc:
        return None, str(exc)


# --------------------------------------------------------------------------
# Minimal indentation-based workflow extractor (no PyYAML — not stdlib)
#
# The extractor tracks a stack of mapping keys by indent, so it can tell
# a step's top-level keys from keys nested under with:/env:/strategy:
# etc. Only dashes whose parent path is a job-level `steps:` key create
# steps. Block scalars are tracked for ANY key (so the body of a
# `script: |` / `text: |` block is never mistaken for workflow keys).
# --------------------------------------------------------------------------
class RunEntry:
    __slots__ = ("line", "lines")

    def __init__(self, line):
        self.line = line          # 1-based line of the `run:` key
        self.lines = []           # list of (line_no, text)


class Step:
    __slots__ = ("runs", "wd", "wd_line", "shell", "disabled", "coe",
                 "uses", "checkout_paths", "default_wd", "job_index")

    def __init__(self):
        self.runs = []
        self.wd = None
        self.wd_line = 0
        self.shell = None
        self.disabled = False     # literal `if: false` on step or job
        self.coe = False          # continue-on-error: true
        self.uses = None
        self.checkout_paths = []
        self.default_wd = None    # effective default working-directory
        self.job_index = -1


_KEY_RE = re.compile(r"^([A-Za-z0-9_.\-\"']+)\s*:\s*(.*)$")
_BLOCK_HDR_RE = re.compile(
    r"^([|>])(?:([+-])(\d)|(\d)([+-])|([+-])|(\d))?\s*(?:#.*)?$")


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    return value


def _strip_value_prefixes(value):
    """Strip leading YAML anchors (&name) and tags (!!str, !tag)."""
    v = value.strip()
    while v:
        parts = v.split(None, 1)
        tok = parts[0]
        if tok.startswith("&") or tok.startswith("!"):
            v = parts[1].strip() if len(parts) > 1 else ""
        else:
            break
    return v


def _parse_block_header(v):
    """Return (style, indent_digit|None) if v is a block scalar header."""
    m = _BLOCK_HDR_RE.match(v.strip())
    if not m:
        return None
    digit = m.group(3) or m.group(4) or m.group(7)
    return m.group(1), (int(digit) if digit else None)


def _is_false_value(value):
    v = _strip_value_prefixes(value).strip()
    if v.startswith("${{") and v.endswith("}}"):
        v = v[3:-2].strip()
    v = _unquote(v).strip().lower()
    return v in ("false", "false()")


def extract_steps(text):
    """Return (steps, errors, workflow_default_wd).

    Supports: single-line `run: cmd`, block scalars `|` / `>` (chomping
    and indent indicators, trailing comments), folded scalars joined
    into logical lines, plain multi-line scalars, `- run: cmd` inline
    steps, bare `-` steps, step/job/workflow `working-directory:`
    (job defaults are scoped per job), `shell:`, `if: false`,
    `continue-on-error:`. Flow style / exotic YAML yields an error
    entry (unscanned), never a silent clean pass.
    """
    errors = []
    steps = []
    raw_lines = text.splitlines()
    stack = []                    # list of [indent, key]
    current = None                # current Step or None
    step_key_indent = None
    job_index = -1
    job_defaults = {}             # job_index -> wd
    job_disabled = {}             # job_index -> bool
    workflow_default = None
    block = None                  # active block scalar state
    pending = None                # plain-scalar continuation state
    block_content_lines = set()   # line numbers consumed as block body

    def path_now():
        return [k for _, k in stack]

    def refresh_defaults():
        for s in steps:
            if s.job_index in job_defaults:
                s.default_wd = job_defaults[s.job_index]
            else:
                s.default_wd = workflow_default

    def finish_block():
        nonlocal block
        if block is None:
            return
        entry = block["entry"]
        if entry is not None:
            if block["style"] == ">":
                # Folded: join wrapped lines with spaces; a blank line
                # ends a logical line.
                logical, cur, cur_ln = [], None, None
                for ln, t in block["buffer"]:
                    if t.strip() == "":
                        if cur is not None:
                            logical.append((cur_ln, cur))
                            cur = None
                        continue
                    if cur is None:
                        cur, cur_ln = t.strip(), ln
                    else:
                        cur += " " + t.strip()
                if cur is not None:
                    logical.append((cur_ln, cur))
                entry.lines = logical
            else:
                entry.lines = list(block["buffer"])
        block = None

    def finish_pending():
        nonlocal pending
        if pending is not None:
            pending["entry"].lines = [(pending["line"], pending["text"])]
            pending = None

    def process_key(key, value, lineno, key_indent, popped_path):
        """Handle one mapping key. popped_path = key stack before push."""
        nonlocal block, pending, workflow_default, current
        in_step_top = (current is not None and popped_path
                       and popped_path[-1] == "steps")
        if in_step_top:
            if key == "run":
                entry = RunEntry(lineno)
                current.runs.append(entry)
                v = _strip_value_prefixes(value)
                if v[:1] in ("|", ">"):
                    hdr = _parse_block_header(v)
                    if hdr is None:
                        errors.append(
                            f"line {lineno}: unsupported block scalar "
                            f"header {v!r}")
                        block = {"entry": None, "key_indent": key_indent,
                                 "content_indent": None, "style": "|",
                                 "buffer": []}
                    else:
                        block = {"entry": entry, "key_indent": key_indent,
                                 "content_indent": (key_indent + hdr[1]
                                                    if hdr[1] else None),
                                 "style": hdr[0], "buffer": []}
                elif v.strip():
                    vs = v.strip()
                    if vs[0] in "\"'" and (len(vs) < 2 or vs[-1] != vs[0]):
                        errors.append(
                            f"line {lineno}: unterminated quote in run:")
                        entry.lines.append((lineno, _unquote(vs)))
                    elif vs[0] in "\"'":
                        entry.lines.append((lineno, _unquote(vs)))
                    else:
                        pending = {"entry": entry, "key_indent": key_indent,
                                   "line": lineno, "text": vs}
                        entry.lines.append((lineno, vs))
                else:
                    # `run:` with only an anchor/tag: value may continue
                    # as a plain scalar on following indented lines.
                    pending = {"entry": entry, "key_indent": key_indent,
                               "line": lineno, "text": ""}
                return
            if key == "working-directory":
                current.wd = _unquote(_strip_value_prefixes(value))
                current.wd_line = lineno
                return
            if key == "shell":
                current.shell = _unquote(_strip_value_prefixes(value))
                return
            if key == "if":
                if _is_false_value(value):
                    current.disabled = True
                return
            if key == "continue-on-error":
                v = _unquote(_strip_value_prefixes(value)).strip().lower()
                current.coe = (v == "true")
                return
            if key == "uses":
                current.uses = _unquote(_strip_value_prefixes(value))
                return
            return
        # Nested step keys (under with:, env:, ...) — only checkout
        # `with: path:` is meaningful here.
        if (current is not None and len(popped_path) >= 2
                and popped_path[-2] == "steps" and popped_path[-1] == "with"
                and key == "path"):
            current.checkout_paths.append(
                _unquote(_strip_value_prefixes(value)))
            return
        # working-directory under defaults: / defaults: run:
        if key == "working-directory" and len(popped_path) >= 2 \
                and popped_path[-1] == "run" and popped_path[-2] == "defaults":
            wd = _unquote(_strip_value_prefixes(value))
            if popped_path[0] == "jobs" and job_index >= 0:
                job_defaults[job_index] = wd
            else:
                workflow_default = wd
            refresh_defaults()
            return
        # Job-level `if: false` disables the whole job.
        if key == "if" and len(popped_path) == 2 and popped_path[0] == "jobs":
            if _is_false_value(value):
                job_disabled[job_index] = True
                for s in steps:
                    if s.job_index == job_index:
                        s.disabled = True
                if current is not None and current.job_index == job_index:
                    current.disabled = True
            return

    for idx, raw in enumerate(raw_lines):
        lineno = idx + 1
        if len(raw) > 20000:
            errors.append(f"line {lineno}: line exceeds size cap")
            finish_block()
            finish_pending()
            continue
        stripped = raw.strip()

        # Inside a block scalar (for ANY key)?
        if block is not None:
            if stripped == "":
                if block["entry"] is not None:
                    block["buffer"].append((lineno, ""))
                    block_content_lines.add(lineno)
                continue
            indent_b = len(raw) - len(raw.lstrip(" "))
            if "\t" in raw[:len(raw) - len(raw.lstrip())]:
                errors.append(
                    f"line {lineno}: tab indentation inside block scalar")
                finish_block()
                continue
            if block["content_indent"] is None:
                if indent_b > block["key_indent"]:
                    block["content_indent"] = indent_b
                else:
                    finish_block()  # empty block; reprocess this line
            if block is not None:
                if indent_b >= block["content_indent"]:
                    block["buffer"].append(
                        (lineno, raw[block["content_indent"]:].rstrip()))
                    block_content_lines.add(lineno)
                    continue
                finish_block()      # block ended; reprocess this line

        # Plain multi-line scalar continuation for `run:`?
        if pending is not None:
            if stripped == "" or stripped.startswith("#"):
                continue
            indent_p = len(raw) - len(raw.lstrip(" "))
            if indent_p > pending["key_indent"]:
                cont = stripped
                pending["text"] = (pending["text"] + " " + cont).strip() \
                    if pending["text"] else cont
                pending["entry"].lines = [(pending["line"], pending["text"])]
                continue
            finish_pending()

        if stripped == "" or stripped.startswith("#"):
            continue
        leading = raw[:len(raw) - len(raw.lstrip())]
        if "\t" in leading:
            errors.append(f"line {lineno}: tab indentation (YAML forbids tabs)")
            continue
        indent = len(raw) - len(raw.lstrip(" "))

        # Dash line?
        dash = re.match(r"^(\s*)-(\s+(.*)|\s*)$", raw)
        if dash:
            d_indent = len(dash.group(1))
            while stack and stack[-1][0] > d_indent:
                stack.pop()
            popped = path_now()
            if popped and popped[-1] == "steps" and "jobs" in popped \
                    and job_index >= 0:
                # A dash inside a job-level steps: list starts a step,
                # whatever its first key is.
                current = Step()
                current.job_index = job_index
                current.disabled = job_disabled.get(job_index, False)
                if job_index in job_defaults:
                    current.default_wd = job_defaults[job_index]
                else:
                    current.default_wd = workflow_default
                steps.append(current)
                content = (dash.group(3) or "").strip()
                step_key_indent = d_indent + 2
                if content:
                    km = _KEY_RE.match(content)
                    if km:
                        process_key(km.group(1).strip("\"'"), km.group(2),
                                    lineno, step_key_indent, popped)
                        stack.append([step_key_indent,
                                      km.group(1).strip("\"'")])
                continue
            # Any other dash (matrix include, with: args, out-of-job
            # steps:, ...) never creates a step.
            current = None
            continue

        # Ordinary key line: pop the stack to this indent.
        while stack and stack[-1][0] >= indent:
            stack.pop()
        popped = path_now()
        km = _KEY_RE.match(stripped)
        if not km:
            continue                    # stray scalar content; ignore
        key = km.group(1).strip("\"'")
        value = km.group(2)

        if "steps" not in popped:
            current = None
        if popped == ["jobs"]:
            job_index += 1              # a new job begins; defaults reset
            current = None
        process_key(key, value, lineno, indent, popped)
        stack.append([indent, key])

        # A block scalar header on ANY key opens a block (unless the
        # run: handling above already opened one).
        if block is None:
            v = _strip_value_prefixes(value)
            if v[:1] in ("|", ">"):
                hdr = _parse_block_header(v)
                digit = hdr[1] if hdr else None
                block = {"entry": None, "key_indent": indent,
                         "content_indent": (indent + digit if digit
                                            else None),
                         "style": v[0], "buffer": []}
    finish_block()
    finish_pending()
    # A file that mentions `run:` outside block bodies but produced no
    # run entries uses a YAML form we do not support (flow style etc.):
    # report it as unscanned, never as clean.
    total_runs = sum(len(s.runs) for s in steps)
    if total_runs == 0:
        for idx, raw in enumerate(raw_lines):
            if (idx + 1) in block_content_lines:
                continue
            if re.search(r"(^|[\s\-\{,])run\s*:", raw):
                errors.append(
                    "contains 'run:' but no run steps could be extracted "
                    "(unsupported YAML form, e.g. flow style)")
                break
    return steps, errors, workflow_default


# --------------------------------------------------------------------------
# Shell segment handling (a deliberately small, conservative subset)
# --------------------------------------------------------------------------
def split_with_ops(script_line):
    """Split one script line on &&, ||, ; and | respecting simple quotes.

    Returns [(segment, op_before)] where op_before is the operator that
    preceded the segment (None for the first).
    """
    parts, buf, quote, i, op = [], [], None, 0, None
    while i < len(script_line):
        c = script_line[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
            buf.append(c)
            i += 1
            continue
        two = script_line[i:i + 2]
        if two in ("&&", "||"):
            parts.append(("".join(buf), op)); buf = []; op = two
            i += 2; continue
        if c in ";|":
            parts.append(("".join(buf), op)); buf = []; op = c
            i += 1; continue
        if c == "&":
            parts.append(("".join(buf), op)); buf = []; op = "&"
            i += 1; continue
        buf.append(c); i += 1
    parts.append(("".join(buf), op))
    return parts


def split_segments(script_line):
    return [p for p, _ in split_with_ops(script_line)]


def strip_comment(line):
    """Remove a trailing # comment, respecting quotes. A # only starts
    a comment at a word boundary (start, or after whitespace/;&|())."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
            i += 1
            continue
        if c == "#" and (i == 0 or line[i - 1] in " \t;&|()"):
            return line[:i].rstrip()
        i += 1
    return line


def _match_paren(text, start):
    """text[start] == '('; return index just past the matching ')'."""
    depth, quote, i = 0, None, start
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def strip_substitutions(text):
    """Replace $(...), `...`, <(...) and >(...) contents with $SUBST.

    Their contents are not analysed (they may contain separators that
    must not split the outer command). Single quotes disable
    substitution in shell, so contents there are left alone.
    """
    out, i, quote = [], 0, None
    while i < len(text):
        c = text[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\" and quote == '"':
            out.append(text[i:i + 2])
            i += 2
            continue
        if c == '"' and quote is None:
            quote = '"'
            out.append(c)
            i += 1
            continue
        if c == '"' and quote == '"':
            quote = None
            out.append(c)
            i += 1
            continue
        if c == "`":
            j = text.find("`", i + 1)
            out.append("$SUBST")
            i = (j + 1) if j >= 0 else len(text)
            continue
        if c == "$" and i + 1 < len(text) and text[i + 1] == "(":
            out.append("$SUBST")
            i = _match_paren(text, i + 1)
            continue
        if c in "<>" and i + 1 < len(text) and text[i + 1] == "(" \
                and quote is None:
            out.append("$SUBST")
            i = _match_paren(text, i + 1)
            continue
        out.append(c)
        i += 1
    return "".join(out)


_HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def find_heredocs(line):
    return [m.group(2) for m in _HEREDOC_RE.finditer(line)]


def net_parens(text):
    """Net '(' minus ')' outside quotes (subshell/grouping depth)."""
    depth, quote = 0, None
    for c in text:
        if quote:
            if c == quote:
                quote = None
            continue
        if c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
    return depth


_BS_SENTINEL = "\x01"


def _protect_backslashes(segment):
    """Protect Windows-path backslashes from shlex's escape handling.

    A backslash followed by a path character (letter, digit, ., _, -)
    is a path separator, not a shell escape; swap it for a sentinel
    before tokenizing and restore it in the tokens afterwards.
    """
    out, i = [], 0
    while i < len(segment):
        c = segment[i]
        if c == "\\" and i + 1 < len(segment) \
                and (segment[i + 1].isalnum() or segment[i + 1] in "._-"):
            out.append(_BS_SENTINEL)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _shlex(segment):
    toks = shlex.split(_protect_backslashes(segment), posix=True)
    return [t.replace(_BS_SENTINEL, "\\") for t in toks]


def tokenize(segment):
    try:
        toks = _shlex(segment)
    except ValueError:
        return None
    # Truncate at redirections.
    out = []
    skip_next = False
    for t in toks:
        if skip_next:
            skip_next = False
            continue
        if t in (">", ">>", "<", "<<", "1>", "2>", "&>"):
            skip_next = True
            continue
        if re.match(r"^\d*>>?&?\d*$", t) or t.startswith(">") or t.startswith("<"):
            continue
        out.append(t)
    return out


def tokenize_raw(segment):
    try:
        return _shlex(segment)
    except ValueError:
        return None


_LEADING_STRIP = {"then", "else", "do", "!", "time", "exec", "command"}
_ENV_VALUE_FLAGS = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}


def normalise_tokens(toks):
    """Strip subshell parens, if/then words, env prefixes, sudo, env cmd."""
    toks = list(toks)
    while toks:
        t = toks[0]
        t2 = t.lstrip("({").strip()
        if t2 == "":
            toks.pop(0); continue
        if t2 != t:
            toks[0] = t2
            t = t2
        if t in _LEADING_STRIP or t in ("if", "elif", "while", "until"):
            toks.pop(0); continue
        if t == "for":
            return []  # loop header: nothing resolvable
        break
    # env-var prefixes FOO=bar cmd ...
    while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) and len(toks) > 1:
        toks.pop(0)
    # sudo (with simple flags)
    while toks and toks[0] == "sudo":
        toks.pop(0)
        while toks and toks[0].startswith("-") and toks[0] not in ("-",):
            flag = toks.pop(0)
            if flag in ("-u", "-g", "-h", "-p") and toks:
                toks.pop(0)
        while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) and len(toks) > 1:
            toks.pop(0)
    # `env FOO=bar cmd` / `env -i cmd` / `env -u NAME cmd` / `env -C dir cmd`
    if toks and toks[0] == "env":
        toks.pop(0)
        while toks:
            t = toks[0]
            if t == "--":
                toks.pop(0)
                break
            if t in _ENV_VALUE_FLAGS:
                toks.pop(0)
                if toks:
                    toks.pop(0)
                continue
            if t.startswith("--unset=") or t.startswith("--chdir="):
                toks.pop(0)
                continue
            if t.startswith("-u") and not t.startswith("--") and len(t) > 2:
                toks.pop(0)
                continue
            if t.startswith("-"):
                toks.pop(0)
                continue
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
                toks.pop(0)
                continue
            break
    return [t.rstrip(");") if not t.startswith(("'", '"')) else t for t in toks]


# --------------------------------------------------------------------------
# Repo model: package.json scripts, Makefile targets, justfile recipes,
# Taskfile tasks
#
# A resolver file that exists but cannot be read/parsed is reported as
# "unknown" (checks depending on it are skipped with a reason), except
# a malformed package.json, which is a hard error state (exit 2).
# --------------------------------------------------------------------------
class RepoModel:
    def __init__(self, root):
        self.root = root
        self._pkg_cache = {}
        self._pkg_data_cache = {}
        self._make_cache = {}
        self._make_rules = {}
        self._just_cache = {}
        self._task_cache = {}
        self._members_cache = {}
        self.warnings = []

    def _path(self, base, *parts):
        return os.path.normpath(os.path.join(base, *parts))

    # -- package.json -----------------------------------------------------
    def package_data(self, base):
        """(data dict | 'malformed' | 'unknown' | None, package.json path)"""
        if base in self._pkg_data_cache:
            return self._pkg_data_cache[base]
        p = self._path(base, "package.json")
        result = (None, p)
        if os.path.isfile(p):
            text, err = read_capped(p)
            if text is None:
                self.warnings.append(
                    f"unreadable resolver file: {p} ({err}); "
                    "resolution treated as unknown")
                result = ("unknown", p)
            else:
                try:
                    data = json.loads(text)
                    result = (data if isinstance(data, dict) else {}, p)
                except (ValueError, RecursionError):
                    # Deep nesting can raise RecursionError in the JSON
                    # parser; both are a malformed-file error state.
                    result = ("malformed", p)
        self._pkg_data_cache[base] = result
        return result

    def package_scripts(self, base):
        """Scripts dict for base/package.json, or a sentinel/None."""
        if base in self._pkg_cache:
            return self._pkg_cache[base]
        data, p = self.package_data(base)
        if isinstance(data, dict):
            scripts = data.get("scripts")
            if isinstance(scripts, dict):
                # Non-string script values do not count as present.
                result = ({k: v for k, v in scripts.items()
                           if isinstance(v, str)}, p)
            else:
                result = ({}, p)
        elif data is None:
            result = (None, p)
        else:                       # 'malformed' or 'unknown'
            result = (data, p)
        self._pkg_cache[base] = result
        return result

    def package_name(self, base):
        data, _ = self.package_data(base)
        if isinstance(data, dict):
            name = data.get("name")
            if isinstance(name, str):
                return name
        return None

    def workspace_members(self, base):
        """Workspace member dirs (with a package.json) under base."""
        if base in self._members_cache:
            return self._members_cache[base]
        patterns = []
        data, _ = self.package_data(base)
        if isinstance(data, dict):
            ws = data.get("workspaces")
            if isinstance(ws, list):
                patterns += [x for x in ws if isinstance(x, str)]
            elif isinstance(ws, dict) and isinstance(ws.get("packages"), list):
                patterns += [x for x in ws["packages"] if isinstance(x, str)]
        # pnpm-workspace.yaml: simple `packages:` list of quoted globs.
        ypath = self._path(base, "pnpm-workspace.yaml")
        if os.path.isfile(ypath):
            text, _ = read_capped(ypath)
            if text:
                in_pkgs = False
                for line in text.splitlines():
                    if re.match(r"^packages\s*:", line):
                        in_pkgs = True
                        continue
                    if in_pkgs:
                        m = re.match(r"^\s+-\s+['\"]?([^'\"]+?)['\"]?\s*$", line)
                        if m:
                            patterns.append(m.group(1))
                        elif line.strip() and not line.startswith((" ", "\t")):
                            in_pkgs = False
        members = []
        for pat in patterns:
            if pat.startswith("!"):
                continue
            for cand in sorted(glob.glob(os.path.join(base, pat))):
                if os.path.isdir(cand) and os.path.isfile(
                        os.path.join(cand, "package.json")):
                    members.append(os.path.normpath(cand))
        self._members_cache[base] = members
        return members

    # -- Makefile -----------------------------------------------------------
    def make_targets(self, base):
        """(targets:set|'unknown'|None, makefile_path, first_target)"""
        if base in self._make_cache:
            return self._make_cache[base]
        chosen = None
        for name in ("Makefile", "makefile", "GNUmakefile"):
            cand = self._path(base, name)
            if os.path.isfile(cand):
                chosen = cand
                break
        if chosen is None:
            result = (None, self._path(base, "Makefile"), None)
            self._make_rules[base] = ([], set())
        else:
            result = self._load_makefile(chosen, base)
        self._make_cache[base] = result
        return result

    def make_targets_for(self, path):
        base = os.path.dirname(path)
        key = ("file", path)
        if key in self._make_cache:
            return self._make_cache[key]
        if not os.path.isfile(path):
            result = (None, path, None)
            self._make_rules[key] = ([], set())
        else:
            result = self._load_makefile(path, key)
        self._make_cache[key] = result
        return result

    def _load_makefile(self, path, cache_key):
        acc = {"targets": set(), "first": None, "patterns": [],
               "suffix_dests": set(), "unknown": False}
        self._parse_make_into(path, os.path.dirname(path), set(), acc, 0)
        self._make_rules[cache_key] = (acc["patterns"], acc["suffix_dests"])
        if acc["unknown"] and not acc["targets"]:
            return ("unknown", path, None)
        return (acc["targets"], path, acc["first"])

    def make_rules(self, base_or_key):
        return self._make_rules.get(base_or_key, ([], set()))

    def _parse_make_into(self, path, base_dir, visited, acc, depth):
        if path in visited or depth > 8:
            return
        visited.add(path)
        text, err = read_capped(path)
        if text is None:
            acc["unknown"] = True
            self.warnings.append(
                f"unreadable resolver file: {path} ({err}); "
                "resolution treated as unknown")
            return
        # Join backslash continuations on non-recipe lines.
        joined, buf = [], ""
        for raw in text.splitlines():
            if buf:
                buf += raw
            else:
                buf = raw
            if buf.endswith("\\") and not buf.startswith("\t"):
                buf = buf[:-1] + " "
                continue
            joined.append(buf)
            buf = ""
        if buf:
            joined.append(buf)
        in_define = False
        for line in joined:
            if in_define:
                if line.strip() == "endef":
                    in_define = False
                continue
            if re.match(r"^define\b", line):
                in_define = True
                continue
            if line.startswith("\t"):
                continue                    # recipe body
            code = re.sub(r"(?<!\\)#.*$", "", line)   # strip comments
            s = code.strip()
            if not s:
                continue
            inc = re.match(r"^(-?include|sinclude)\s+(.+)$", s)
            if inc:
                for tok in inc.group(2).split():
                    if "$" in tok or "%" in tok:
                        continue
                    cand = os.path.normpath(os.path.join(base_dir, tok))
                    if os.path.isfile(cand):
                        self._parse_make_into(
                            cand, os.path.dirname(cand), visited, acc,
                            depth + 1)
                continue
            if re.match(r"^[A-Za-z_][\w]*\s*[:+?!]?=", code):
                continue                    # variable assignment
            m = re.match(r"^([^:=]+?)\s*:(?![=])\s*(.*)$", code)
            if not m:
                continue
            names = m.group(1).split()
            if names == [".PHONY"]:
                for n in m.group(2).split():
                    acc["targets"].add(n)
                continue
            for n in names:
                if n.startswith("$"):
                    continue
                if "%" in n:
                    acc["patterns"].append(n)
                    continue
                sm = re.fullmatch(r"\.([A-Za-z0-9]+)\.([A-Za-z0-9]+)", n)
                if sm:
                    acc["suffix_dests"].add("." + sm.group(2))
                    continue
                acc["targets"].add(n)
                if acc["first"] is None and not n.startswith("."):
                    acc["first"] = n

    # -- justfile -----------------------------------------------------------
    def just_recipes(self, base):
        if base in self._just_cache:
            return self._just_cache[base]
        chosen = None
        for name in ("justfile", "Justfile", ".justfile"):
            cand = self._path(base, name)
            if os.path.isfile(cand):
                chosen = cand
                break
        if chosen is None:
            result = (None, self._path(base, "justfile"))
        else:
            result = self._load_justfile(chosen)
        self._just_cache[base] = result
        return result

    def just_recipes_for(self, path):
        key = ("file", path)
        if key in self._just_cache:
            return self._just_cache[key]
        if not os.path.isfile(path):
            result = (None, path)
        else:
            result = self._load_justfile(path)
        self._just_cache[key] = result
        return result

    def _load_justfile(self, path):
        acc = {"recipes": set(), "unknown": False}
        self._parse_just_into(path, set(), acc, 0)
        if acc["unknown"] and not acc["recipes"]:
            return ("unknown", path)
        return (acc["recipes"], path)

    def _parse_just_into(self, path, visited, acc, depth):
        if path in visited or depth > 8:
            return
        visited.add(path)
        text, err = read_capped(path)
        if text is None:
            acc["unknown"] = True
            self.warnings.append(
                f"unreadable resolver file: {path} ({err}); "
                "resolution treated as unknown")
            return
        base_dir = os.path.dirname(path)
        for line in text.splitlines():
            if not line or line[0] in " \t#":
                continue                    # bodies, comments, blanks
            s = line.strip()
            if s.startswith("["):
                continue                    # attribute line
            am = re.match(r"^alias\s+([A-Za-z_][\w\-]*)\s*:?=", s)
            if am:
                acc["recipes"].add(am.group(1))
                continue
            mm = re.match(r"^mod\s+(\S+)(?:\s+(\S+))?", s)
            if mm:
                name = mm.group(1).strip("'\"")
                rel = mm.group(2).strip("'\"") if mm.group(2) else None
                cands = []
                if rel:
                    cands = [os.path.join(base_dir, rel),
                             os.path.join(base_dir, rel + ".just"),
                             os.path.join(base_dir, rel, "mod.just")]
                else:
                    cands = [os.path.join(base_dir, name + ".just"),
                             os.path.join(base_dir, name, "mod.just")]
                for cand in cands:
                    if os.path.isfile(cand):
                        self._parse_just_into(
                            os.path.normpath(cand), visited, acc, depth + 1)
                        break
                continue
            im = re.match(r"^import\s+['\"]([^'\"]+)['\"]", s)
            if im:
                cand = os.path.normpath(os.path.join(base_dir, im.group(1)))
                if os.path.isfile(cand):
                    self._parse_just_into(cand, visited, acc, depth + 1)
                continue
            first = s.split(None, 1)[0] if s.split() else ""
            if first.rstrip(":") in ("set", "export", "mod", "import",
                                      "alias"):
                continue
            colon = _just_top_colon(s)
            if colon is None or s[colon + 1:colon + 2] == "=":
                continue                    # no colon, or an assignment
            header = s[:colon]
            if not header.split():
                continue
            nm = re.match(r"^@?([A-Za-z_][\w\-]*)", header.split()[0])
            if nm:
                acc["recipes"].add(nm.group(1))

    # -- Taskfile ---------------------------------------------------------
    # Taskfiles are YAML and there is no YAML parser in the stdlib, so
    # task names are enumerated line-wise from the v3 `tasks:` mapping
    # (the same pragmatic-subset approach as the pnpm-workspace.yaml
    # reader above). A Taskfile whose tasks cannot be enumerated that
    # way — a v2-layout file (tasks at top level), a flow-style or
    # anchor/merge-key-built mapping, a tab-indented file — is reported
    # as "unknown" and its checks are skipped, never flagged.
    TASKFILE_NAMES = ("Taskfile.yml", "Taskfile.yaml", "Taskfile.dist.yml",
                      "Taskfile.dist.yaml", "taskfile.yml", "taskfile.yaml",
                      "taskfile.dist.yml", "taskfile.dist.yaml")

    def task_tasks(self, base):
        """(names:set|'unknown'|None, taskfile_path, includes:dict)

        ``names`` is every name callable from the CLI in this file:
        task names plus their `aliases:` entries, with `flatten:`
        includes merged in; tasks marked `internal:` are excluded
        (Task refuses them from the command line). ``includes`` maps a
        namespace to the candidate path of the included Taskfile, or
        None for a remote (http/https) include, which cannot be
        resolved statically.
        """
        if base in self._task_cache:
            return self._task_cache[base]
        chosen = None
        for name in self.TASKFILE_NAMES:
            cand = self._path(base, name)
            if os.path.isfile(cand):
                chosen = cand
                break
        if chosen is None:
            result = (None, self._path(base, "Taskfile.yml"), {})
        else:
            result = self._load_taskfile(chosen)
        self._task_cache[base] = result
        return result

    def task_tasks_for(self, path):
        key = ("file", path)
        if key in self._task_cache:
            return self._task_cache[key]
        if not os.path.isfile(path):
            result = (None, path, {})
        else:
            result = self._load_taskfile(path)
        self._task_cache[key] = result
        return result

    def _load_taskfile(self, path):
        acc = {"names": set(), "includes": {}, "unknown": False,
               "saw_tasks": False}
        self._parse_taskfile_into(path, set(), acc, 0)
        if acc["unknown"] and not acc["names"]:
            return ("unknown", path, acc["includes"])
        if not acc["saw_tasks"]:
            return ("unknown", path, acc["includes"])
        return (acc["names"], path, acc["includes"])

    def _parse_taskfile_into(self, path, visited, acc, depth):
        if path in visited or depth > 8:
            return
        visited.add(path)
        text, err = read_capped(path)
        if text is None:
            acc["unknown"] = True
            self.warnings.append(
                f"unreadable resolver file: {path} ({err}); "
                "resolution treated as unknown")
            return
        base_dir = os.path.dirname(path)
        section = None            # current top-level key
        entry_indent = None       # indent of entries in this section
        cur = None                # current task entry being collected
        alias_indent = None       # indent of an open `aliases:` list
        cur_inc = None            # current include entry being collected
        inc_entries = []

        def flush_task():
            nonlocal cur
            if cur is not None and not cur["internal"]:
                acc["names"].add(cur["name"])
                acc["names"].update(cur["aliases"])
            cur = None

        for raw in text.splitlines():
            if "\t" in raw[:len(raw) - len(raw.lstrip())]:
                # YAML forbids tab indentation; a tab-indented file
                # cannot be enumerated line-wise with confidence.
                acc["unknown"] = True
                return
            stripped = raw.strip()
            if not stripped or stripped.startswith("#") \
                    or stripped in ("---", "..."):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent == 0:
                flush_task()
                cur_inc = None
                alias_indent = None
                entry_indent = None
                m = re.match(r"^['\"]?([^'\":]+?)['\"]?\s*:(?:\s+(.*))?$",
                             stripped)
                section = m.group(1).strip() if m else None
                if section == "tasks":
                    acc["saw_tasks"] = True
                    val = (m.group(2) or "").strip()
                    if val.startswith("#"):
                        val = ""
                    if val and val != "{}":
                        # Flow-style tasks mapping on one line: not
                        # enumerable line-wise.
                        acc["unknown"] = True
                continue
            if section == "tasks":
                if entry_indent is None:
                    entry_indent = indent
                if indent == entry_indent:
                    flush_task()
                    alias_indent = None
                    name = _yaml_key_name(stripped)
                    if name is not None:
                        cur = {"name": name, "aliases": [],
                               "internal": False}
                    continue
                if cur is None or indent < entry_indent:
                    continue
                if alias_indent is not None and indent <= alias_indent:
                    alias_indent = None
                am = re.match(r"^aliases\s*:\s*(.*)$", stripped)
                if am:
                    val = am.group(1).strip()
                    if val.startswith("["):
                        inner = val[1:val.index("]")] if "]" in val \
                            else val[1:]
                        for part in inner.split(","):
                            part = part.strip().strip("'\"")
                            if part:
                                cur["aliases"].append(part)
                    elif val:
                        cur["aliases"].append(val.strip("'\""))
                    else:
                        alias_indent = indent
                    continue
                if alias_indent is not None and indent > alias_indent:
                    im = re.match(r"^-\s*(.+?)\s*$", stripped)
                    if im:
                        cur["aliases"].append(im.group(1).strip("'\""))
                        continue
                if re.match(r"^internal\s*:\s*(?i:true)\s*$", stripped):
                    cur["internal"] = True
                continue
            if section == "includes":
                if entry_indent is None:
                    entry_indent = indent
                if indent == entry_indent:
                    name = _yaml_key_name(stripped)
                    if name is not None:
                        cur_inc = {"ns": name,
                                   "scalar": _yaml_key_value(stripped),
                                   "props": {}}
                        inc_entries.append(cur_inc)
                    else:
                        cur_inc = None
                    continue
                if cur_inc is not None and indent > entry_indent:
                    pm = re.match(r"^(taskfile|dir|flatten)\s*:\s*(.*)$",
                                  stripped)
                    if pm:
                        cur_inc["props"][pm.group(1)] = \
                            _yaml_scalar(pm.group(2).strip())
                    continue
                continue
        flush_task()
        for ent in inc_entries:
            scalar = ent["scalar"]
            if scalar.startswith("{"):
                fm = re.search(r"taskfile\s*:\s*([^,}]+)", scalar)
                if fm:
                    ent["props"].setdefault("taskfile",
                                            fm.group(1).strip())
                if re.search(r"flatten\s*:\s*true", scalar):
                    ent["props"].setdefault("flatten", "true")
            raw_ref = ent["props"].get("taskfile") or scalar \
                or ent["props"].get("dir")
            if not raw_ref or raw_ref.startswith("{"):
                continue
            raw_ref = raw_ref.strip("'\"")
            if raw_ref.startswith(("http://", "https://")):
                acc["includes"].setdefault(ent["ns"], None)
                continue
            cand = os.path.normpath(os.path.join(base_dir, raw_ref))
            if os.path.isdir(cand):
                found = None
                for nm in self.TASKFILE_NAMES:
                    c2 = os.path.join(cand, nm)
                    if os.path.isfile(c2):
                        found = c2
                        break
                cand = found if found else os.path.join(cand,
                                                        "Taskfile.yml")
            if ent["props"].get("flatten") == "true":
                if os.path.isfile(cand):
                    self._parse_taskfile_into(cand, visited, acc,
                                              depth + 1)
            else:
                acc["includes"].setdefault(ent["ns"], cand)


def _yaml_key_name(s):
    """Name of the YAML mapping key at the start of s, or None.

    The key colon is the first ':' followed by a space or end of line
    (YAML's plain-key rule), so a namespaced key like `logs:api:` and
    a value containing ': ' both parse correctly. Quoted keys are
    unwrapped.
    """
    if s[:1] in ("'", '"'):
        q = s[0]
        end = s.find(q, 1)
        if end > 0 and re.match(r"^\s*:(\s.*)?$", s[end + 1:]):
            return s[1:end]
        return None
    for i, c in enumerate(s):
        if c == ":" and (i + 1 == len(s) or s[i + 1] in " \t"):
            name = s[:i].strip()
            return name or None
    return None


def _yaml_scalar(v):
    """A plain YAML scalar value: unwrapped quotes, comment stripped."""
    if not v:
        return ""
    if v[:1] in ("'", '"'):
        end = v.find(v[0], 1)
        return v[1:end] if end > 0 else v.strip("'\"")
    return re.sub(r"\s+#.*$", "", v).strip()


def _yaml_key_value(s):
    """The scalar value after the key colon in s ('' when absent)."""
    if s[:1] in ("'", '"'):
        end = s.find(s[0], 1)
        if end == -1:
            return ""
        rest = s[end + 1:].lstrip()
        return _yaml_scalar(rest[1:].strip()) if rest.startswith(":") \
            else ""
    for i, c in enumerate(s):
        if c == ":" and (i + 1 == len(s) or s[i + 1] in " \t"):
            return _yaml_scalar(s[i + 1:].strip())
    return ""


def _just_top_colon(s):
    """Index of the first ':' at bracket depth 0 outside quotes."""
    depth, quote = 0, None
    for i, c in enumerate(s):
        if quote:
            if c == quote:
                quote = None
            continue
        if c in "'\"":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ":" and depth == 0:
            return i
    return None


# --------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------
_INSTALL_RE = re.compile(
    r"(\bpip3?\s+install\b|\buv\s+pip\s+install\b|\bpoetry\s+install\b"
    r"|\bpipenv\s+install\b)")


class Checker:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.model = RepoModel(self.root)
        self.findings = []
        self.checked = 0
        self.skipped = {}   # reason -> count
        self.fatal_errors = []      # [{file, reason}] -> exit 2 state
        self._downgrade = False     # current segment's findings are warnings
        # Per-workflow state, reset by begin_workflow():
        self.created_files = set()
        self.created_dirs = []
        self.checkout_seen = 0
        self.workflow_installs_python = False

    def begin_workflow(self, steps):
        self.created_files = set()
        self.created_dirs = []
        self.checkout_seen = 0
        self.workflow_installs_python = False
        for step in steps:
            for entry in step.runs:
                for _, txt in entry.lines:
                    if _INSTALL_RE.search(txt):
                        self.workflow_installs_python = True
                        return

    def skip(self, reason):
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def fatal(self, path, reason):
        rel = os.path.relpath(path, self.root) if os.path.isabs(path) else path
        entry = {"file": rel, "reason": reason}
        if entry not in self.fatal_errors:
            self.fatal_errors.append(entry)

    def finding(self, wf, line, segment, kind, expected, looked_in,
                suggestion=None):
        message = (f"{kind}: expected {expected} (looked in: "
                   + ", ".join(os.path.relpath(p, self.root)
                               if os.path.isabs(p) else p
                               for p in looked_in) + ")")
        if suggestion:
            message += f" — did you mean '{suggestion}'?"
        self.findings.append({
            "file": wf, "line": line, "segment": segment, "kind": kind,
            "expected": expected,
            "severity": "warning" if self._downgrade else "error",
            "suggestion": suggestion,
            "looked_in": [os.path.relpath(p, self.root) if os.path.isabs(p) else p
                          for p in looked_in],
            "message": message,
        })

    def _within_root(self, path):
        path = os.path.normpath(path)
        return path == self.root or path.startswith(self.root + os.sep)

    def _is_created(self, abspath):
        if abspath in self.created_files:
            return True
        return any(abspath == d or abspath.startswith(d + os.sep)
                   for d in self.created_dirs)

    def _register_created_file(self, base, token):
        if not token or "$" in token or token == "-" \
                or token.startswith("/dev/") or token.startswith("&"):
            return
        cand = token if os.path.isabs(token) else os.path.normpath(
            os.path.join(base, token))
        self.created_files.add(cand)

    def _register_created_dir(self, base, token):
        if not token or "$" in token:
            return
        cand = token if os.path.isabs(token) else os.path.normpath(
            os.path.join(base, token))
        if cand not in self.created_dirs:
            self.created_dirs.append(cand)

    # -- dynamic creation tracking -----------------------------------------
    def detect_creations(self, seg_text, base):
        """Record files this segment visibly creates (>, >>, cp, mv,
        touch, curl -o, wget -O, git clone). mkdir alone does not
        create files and is deliberately not tracked."""
        toks = tokenize_raw(seg_text)
        if not toks:
            return
        # Redirections: > path, >> path, >path, 2>path, ...
        for i, t in enumerate(toks):
            m = re.match(r"^\d*(>>?)(.*)$", t)
            if m:
                target = m.group(2)
                if not target and i + 1 < len(toks):
                    target = toks[i + 1]
                if target:
                    self._register_created_file(base, target)
        toks = normalise_tokens(toks)
        if not toks:
            return
        head = toks[0]
        if head in ("cp", "mv"):
            if "-t" in toks:
                j = toks.index("-t")
                if j + 1 < len(toks):
                    self._register_created_dir(base, toks[j + 1])
                return
            operands = [t for t in toks[1:] if not t.startswith("-")]
            if len(operands) >= 2:
                dst = operands[-1]
                if dst.endswith("/") or len(operands) > 2 \
                        or os.path.isdir(os.path.join(base, dst)):
                    self._register_created_dir(base, dst)
                else:
                    self._register_created_file(base, dst)
            return
        if head == "touch":
            prev = None
            for t in toks[1:]:
                if prev in ("-d", "-t", "-r"):
                    prev = t
                    continue
                prev = t
                if not t.startswith("-"):
                    self._register_created_file(base, t)
            return
        if head == "curl":
            for i, t in enumerate(toks):
                if t in ("-o", "--output") and i + 1 < len(toks):
                    self._register_created_file(base, toks[i + 1])
                elif t.startswith("--output="):
                    self._register_created_file(base, t.split("=", 1)[1])
                elif re.match(r"^-o\S", t):
                    self._register_created_file(base, t[2:])
                elif t in ("-O", "--remote-name"):
                    for u in toks[1:]:
                        if "://" in u:
                            name = u.rstrip("/").rsplit("/", 1)[-1]
                            if name:
                                self._register_created_file(base, name)
            return
        if head == "wget":
            for i, t in enumerate(toks):
                if t in ("-O", "--output-document") and i + 1 < len(toks):
                    self._register_created_file(base, toks[i + 1])
                elif t.startswith("--output-document="):
                    self._register_created_file(base, t.split("=", 1)[1])
                elif re.match(r"^-O\S", t):
                    self._register_created_file(base, t[2:])
            return
        if head == "git" and len(toks) >= 2 and toks[1] == "clone":
            value_flags = {"--depth", "-b", "--branch", "--template",
                           "-c", "--config", "-o", "--origin", "-u",
                           "--upload-pack", "--separate-git-dir"}
            operands = []
            i = 2
            while i < len(toks):
                t = toks[i]
                if t in value_flags:
                    i += 2
                    continue
                if t.startswith("-"):
                    i += 1
                    continue
                operands.append(t)
                i += 1
            if operands:
                if len(operands) >= 2:
                    dest = operands[1]
                else:
                    dest = operands[0].rstrip("/").rsplit("/", 1)[-1]
                    if dest.endswith(".git"):
                        dest = dest[:-4]
                if dest:
                    self._register_created_dir(base, dest)
            return

    # -- individual resolution rules -------------------------------------
    def check_package_script(self, wf, line, segment, base, manager, name):
        self.checked += 1
        if not self._within_root(base):
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        scripts, pkg_path = self.model.package_scripts(base)
        if scripts is None:
            self.finding(wf, line, segment, f"missing-{manager}-script",
                         f"script '{name}' in a package.json for {manager}",
                         [pkg_path])
        elif scripts == "malformed":
            self.fatal(pkg_path, "malformed package.json")
            self.checked -= 1
        elif scripts == "unknown":
            self.skip("resolver-file-unknown")
            self.checked -= 1
        elif name not in scripts:
            self.finding(wf, line, segment, f"missing-{manager}-script",
                         f"script '{name}'", [pkg_path],
                         suggestion=_suggest(name, scripts.keys()))

    def check_make(self, wf, line, segment, base, target, mkfile=None):
        self.checked += 1
        if not self._within_root(base):
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        if mkfile is not None and not self._within_root(mkfile):
            # Auditor H1: `make -f ../x.mk` must never read (or leak)
            # files outside the repo root.
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        if mkfile is not None:
            targets, mk_path, first = self.model.make_targets_for(mkfile)
            rules_key = ("file", mkfile)
        else:
            targets, mk_path, first = self.model.make_targets(base)
            rules_key = base
        if targets == "unknown":
            self.skip("resolver-file-unknown")
            self.checked -= 1
            return
        if targets is None:
            exp = f"Makefile (for target '{target}')" if target else "Makefile (for bare `make`)"
            self.finding(wf, line, segment, "missing-makefile", exp, [mk_path])
        elif target is None:
            if first is None:
                self.finding(wf, line, segment, "missing-make-target",
                             "at least one (default) target in Makefile",
                             [mk_path])
        elif target in targets:
            pass
        else:
            patterns, suffix_dests = self.model.make_rules(rules_key)
            ok = False
            for pat in patterns:
                if "%" in pat:
                    pre, post = pat.split("%", 1)
                    if target.startswith(pre) and target.endswith(post) \
                            and len(target) > len(pre) + len(post):
                        ok = True
                        break
            if not ok:
                for dest in suffix_dests:
                    if target.endswith(dest) and len(target) > len(dest):
                        ok = True
                        break
            if not ok and os.path.exists(os.path.join(base, target)):
                ok = True       # target exists as a file/dir on disk
            if not ok:
                self.finding(wf, line, segment, "missing-make-target",
                             f"make target '{target}'", [mk_path],
                             suggestion=_suggest(target, targets))

    def check_just(self, wf, line, segment, base, recipe, justfile=None):
        self.checked += 1
        if not self._within_root(base):
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        if justfile is not None and not self._within_root(justfile):
            # Auditor H1: same outside-root guard as `make -f`.
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        if justfile is not None:
            recipes, jf_path = self.model.just_recipes_for(justfile)
        else:
            recipes, jf_path = self.model.just_recipes(base)
        if recipes == "unknown":
            self.skip("resolver-file-unknown")
            self.checked -= 1
            return
        if recipes is None:
            exp = f"justfile (for recipe '{recipe}')" if recipe else "justfile (for bare `just`)"
            self.finding(wf, line, segment, "missing-justfile", exp, [jf_path])
        elif recipe is not None and recipe not in recipes:
            self.finding(wf, line, segment, "missing-just-recipe",
                         f"just recipe '{recipe}'", [jf_path],
                         suggestion=_suggest(recipe, recipes))

    def check_task(self, wf, line, segment, base, target, taskfile=None,
                   bare=False):
        self.checked += 1
        if not self._within_root(base):
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        if taskfile is not None and not self._within_root(taskfile):
            # Same outside-root guard as `just -f`.
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        if taskfile is not None:
            names, tf_path, includes = self.model.task_tasks_for(taskfile)
        else:
            names, tf_path, includes = self.model.task_tasks(base)
        if names == "unknown":
            self.skip("resolver-file-unknown")
            self.checked -= 1
            return
        if names is None:
            exp = f"Taskfile (for task '{target}')" if target \
                else "Taskfile (for bare `task`)"
            self.finding(wf, line, segment, "missing-taskfile", exp,
                         [tf_path])
            return
        if target is None:
            # A listing invocation only needs the file. Bare `task`
            # runs the task named `default`.
            if bare and self._resolve_task(names, includes, tf_path,
                                           "default")[0] == "missing":
                self.finding(wf, line, segment, "missing-task-target",
                             "a 'default' task in Taskfile "
                             "(bare `task` runs it)", [tf_path])
            return
        status, where, pool = self._resolve_task(names, includes,
                                                 tf_path, target)
        if status == "unknown":
            self.skip("resolver-file-unknown")
            self.checked -= 1
        elif status == "missing-file":
            self.finding(wf, line, segment, "missing-taskfile",
                         f"included Taskfile (for task '{target}')",
                         [where])
        elif status == "missing":
            self.finding(wf, line, segment, "missing-task-target",
                         f"Taskfile task '{target}'", [where],
                         suggestion=_suggest(target, pool))

    def _resolve_task(self, names, includes, tf_path, target, depth=0):
        """Resolve a (possibly namespaced) Taskfile task name.

        Returns (status, path, pool): status is 'ok', 'missing',
        'missing-file' (an included Taskfile does not exist) or
        'unknown' (an include cannot be enumerated statically);
        pool is the name set the lookup failed against, for
        suggestions.
        """
        if target in names:
            return ("ok", tf_path, names)
        for n in names:
            if "*" in n and fnmatch.fnmatchcase(target, n):
                return ("ok", tf_path, names)
        if ":" in target and depth < 8:
            ns, rest = target.split(":", 1)
            if ns in includes:
                inc = includes[ns]
                if inc is None:
                    return ("unknown", tf_path, names)  # remote include
                sub, sub_path, sub_inc = self.model.task_tasks_for(inc)
                if sub == "unknown":
                    return ("unknown", sub_path, names)
                if sub is None:
                    return ("missing-file", inc, names)
                return self._resolve_task(sub, sub_inc, sub_path, rest,
                                          depth + 1)
        return ("missing", tf_path, names)

    def check_file(self, wf, line, segment, base, rel, kind="missing-file"):
        self.checked += 1
        if "$" in rel:
            self.skip("variable-argument")
            self.checked -= 1
            return
        rel_n = rel.replace("\\", "/") if "\\" in rel else rel
        parts = [p for p in rel_n.split("/") if p not in ("", ".")]
        if "node_modules" in parts and ".bin" in parts:
            self.skip("installed artifact")
            self.checked -= 1
            return
        cand = os.path.normpath(os.path.join(base, rel_n))
        if not self._within_root(cand):
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        if self._is_created(cand):
            self.skip("created earlier in workflow")
            self.checked -= 1
            return
        if not os.path.isfile(cand):
            self.finding(wf, line, segment, kind, f"file '{rel}'", [cand])

    def _module_exists(self, base, top):
        return self._top_location(base, top) is not None

    def _top_location(self, base, top):
        """Locate a top-level module under base or base/src.

        Returns (path, is_dir) or None. A directory counts whether or
        not it has __init__.py (regular or namespace package), matching
        the v1 model; a plain ``top.py`` file is a module, not a package.
        """
        for root_base in (base, os.path.join(base, "src")):
            d = os.path.join(root_base, top)
            if os.path.isdir(d):
                return d, True
            f = os.path.join(root_base, top + ".py")
            if os.path.isfile(f):
                return f, False
        return None

    def _local_top_names(self, base):
        names = set()
        for root_base in (base, os.path.join(base, "src")):
            try:
                entries = os.listdir(root_base)
            except OSError:
                continue
            for e in entries:
                if e.startswith(".") or e == "__pycache__":
                    continue
                full = os.path.join(root_base, e)
                if os.path.isdir(full):
                    # Only package-like directories are candidates
                    # (red team: a docs/ dir of markdown is not a
                    # top-level Python package suggestion).
                    try:
                        inner = os.listdir(full)
                    except OSError:
                        continue
                    if any(x.endswith(".py") or
                           os.path.isdir(os.path.join(full, x))
                           for x in inner):
                        names.add(e)
                elif e.endswith(".py") and e != "__init__.py":
                    names.add(e[:-3])
        return names

    @staticmethod
    def _dir_child(dirpath, part):
        """(path, is_dir) for a submodule part inside dirpath, or None.

        Accepts ``part.py``, a ``part/`` directory (regular or namespace
        package portion), and compiled modules (``part.so`` /
        ``part.<abi>.so`` / ``part.pyd``).
        """
        # CPython's finder gives a package directory precedence over
        # a same-named module file in the same directory (auditor L7).
        d = os.path.join(dirpath, part)
        if os.path.isdir(d):
            return d, True
        f = os.path.join(dirpath, part + ".py")
        if os.path.isfile(f):
            return f, False
        try:
            entries = os.listdir(dirpath)
        except OSError:
            return None
        for e in sorted(entries):
            # Compiled modules must be real files whose suffix is a
            # genuine extension suffix on this platform (red team:
            # `miss.notreal.so`, `miss..so` and directories named
            # `miss.abi3.so` are not importable modules).
            if _compiled_stem(e) == part and os.path.isfile(
                    os.path.join(dirpath, e)):
                return os.path.join(dirpath, e), False
        return None

    @staticmethod
    def _submodule_names(dirpath):
        names = set()
        try:
            entries = os.listdir(dirpath)
        except OSError:
            return names
        for e in entries:
            if e.startswith(".") or e == "__pycache__":
                continue
            full = os.path.join(dirpath, e)
            if os.path.isdir(full):
                names.add(e)
            elif e.endswith(".py") and e != "__init__.py":
                names.add(e[:-3])
            else:
                stem = _compiled_stem(e)
                if stem:
                    names.add(stem)
        return names

    @staticmethod
    def _package_is_dynamic(dirpath):
        """True when the package's __init__.py can invent submodules
        at runtime (PEP 562 __getattr__ / sys.modules tricks). Such
        submodules cannot be resolved statically, so we skip.

        AST-based (red team): a comment or docstring merely mentioning
        __getattr__ must NOT disable checking — only a real definition,
        import or assignment of __getattr__, or a real sys.modules
        use, counts. An unparseable __init__.py stays dynamic
        (uncertain → skip).
        """
        init = os.path.join(dirpath, "__init__.py")
        if not os.path.isfile(init):
            return False
        text, err = read_capped(init)
        if text is None:
            return True           # unreadable: resolution is uncertain
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return True
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == "__getattr__":
                return True
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name == "__getattr__" or \
                            alias.asname == "__getattr__":
                        return True
                    if isinstance(node, ast.ImportFrom) \
                            and node.module == "sys" \
                            and alias.name == "modules":
                        return True
                    if isinstance(node, ast.Import) \
                            and alias.name == "sys.modules":
                        return True
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "__getattr__":
                        return True
            if isinstance(node, ast.Attribute) and node.attr == "modules" \
                    and isinstance(node.value, ast.Name) \
                    and node.value.id == "sys":
                return True
        return False

    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    @staticmethod
    def _is_regular_package(dirpath):
        return os.path.isfile(os.path.join(dirpath, "__init__.py"))

    def _top_locations(self, base, top):
        """All locations of a top-level module, PEP 420 style.

        Roots are scanned in order (base, then base/src). A regular
        package (dir with __init__.py) or a module file is a *winner*:
        it shadows any namespace portions collected before it and is
        returned alone. Namespace portions (dirs without __init__.py)
        accumulate — Python merges them across sys.path entries, so a
        submodule may live in ANY portion.
        """
        portions = []
        for root_base in (base, os.path.join(base, "src")):
            d = os.path.join(root_base, top)
            if os.path.isdir(d):
                if self._is_regular_package(d):
                    return [(d, True)]
                portions.append((d, True))
                continue
            f = os.path.join(root_base, top + ".py")
            if os.path.isfile(f):
                return [(f, False)]
        return portions

    def _advance(self, dirs, part):
        """One PEP 420 step across portion dirs, in path order.

        Returns ("winner", path, is_dir) for a file or regular package,
        ("portions", [dirs]) when only namespace portions matched, or
        (None,) when the part exists in no portion.
        """
        portions = []
        for d in dirs:
            child = self._dir_child(d, part)
            if child is None:
                continue
            path, is_dir = child
            if is_dir and not self._is_regular_package(path):
                portions.append(path)
                continue
            return ("winner", path, is_dir)
        if portions:
            return ("portions", portions)
        return (None,)

    def _resolve_module(self, base, module):
        """Resolve a dotted module against the local tree.

        Returns ("exists",) / ("missing-top",) / ("dynamic",) /
        ("missing-sub", dirs, prefix) /
        ("not-package", path, dotted_name).
        """
        parts = module.split(".")
        tops = self._top_locations(base, parts[0])
        if not tops:
            return ("missing-top",)
        if len(parts) == 1:
            if len(tops) == 1 and not tops[0][1]:
                return ("exists",)            # a plain module file
            dirs = [p for p, _ in tops]
            # `python -m <package>` executes <package>/__main__.py; a
            # directory without one is a guaranteed runtime failure,
            # not an uncertainty (red team).
            if any(os.path.isfile(os.path.join(d, "__main__.py"))
                   for d in dirs):
                return ("exists",)
            return ("missing-main", dirs, parts[0])
        if len(tops) == 1 and not tops[0][1]:
            return ("not-package", tops[0][0], parts[0])
        dirs = [p for p, _ in tops]
        prefix = parts[0]
        for idx, part in enumerate(parts[1:], start=1):
            if any(self._package_is_dynamic(d) for d in dirs):
                return ("dynamic",)
            adv = self._advance(dirs, part)
            if adv[0] is None:
                return ("missing-sub", dirs, prefix)
            is_last = idx == len(parts) - 1
            if adv[0] == "portions":
                if is_last:
                    if any(os.path.isfile(os.path.join(d, "__main__.py"))
                           for d in adv[1]):
                        return ("exists",)
                    return ("missing-main", adv[1], module)
                dirs = adv[1]
                prefix = prefix + "." + part
                continue
            _, path, is_dir = adv
            if is_last:
                if not is_dir:
                    return ("exists",)
                if os.path.isfile(os.path.join(path, "__main__.py")):
                    return ("exists",)
                return ("missing-main", [path], module)
            if not is_dir:
                return ("not-package", path, prefix + "." + part)
            dirs = [path]
            prefix = prefix + "." + part
        return ("exists",)

    def _module_fully_resolves(self, base, module):
        return self._resolve_module(base, module)[0] == "exists"

    def _top_shadows_stdlib(self, base, top):
        """True when the local top-level entry would shadow a stdlib
        module of the same name at runtime: a single winning location
        that is a module file or a regular package. Merged namespace
        portions do not shadow a stdlib regular package."""
        locs = self._top_locations(base, top)
        if len(locs) != 1:
            return False
        path, is_dir = locs[0]
        return (not is_dir) or self._is_regular_package(path)

    def check_python_module(self, wf, line, segment, base, module):
        self.checked += 1
        if not self._within_root(base):
            # Red team: every other checker has this guard; a `cd`
            # out of the repo must not resolve or flag outside paths.
            self.skip("outside-repo-root")
            self.checked -= 1
            return
        parts = module.split(".")
        top = parts[0]
        if any(not self._IDENT_RE.match(p) for p in parts):
            # Not a valid dotted module name (e.g. contains dashes or
            # empty parts): the parts cannot be resolved — but only
            # when the literal top-level entry exists on disk. A top
            # that exists in NO form is a plain missing top (red team:
            # `python -m totallymissing-thing` failed at runtime too).
            literal_top = any(
                os.path.isdir(os.path.join(rb, top))
                or os.path.isfile(os.path.join(rb, top + ".py"))
                for rb in (base, os.path.join(base, "src")))
            if literal_top:
                self.skip("unresolvable-module-name")
                self.checked -= 1
                return
        roots = [os.path.join(base, top),
                 os.path.join(base, "src", top)]
        res = self._resolve_module(base, module)
        status = res[0]
        if status == "exists":
            return
        if status == "dynamic":
            self.skip("dynamic-module")
            self.checked -= 1
            return
        if status == "missing-top":
            # Top level is not repo-local: existing v1 finding, with a
            # did-you-mean only when correcting the top level alone
            # yields a module that fully resolves (never a guess).
            suggestion = None
            sug_top = _suggest(top, self._local_top_names(base))
            if sug_top is not None:
                corrected = ".".join([sug_top] + parts[1:])
                if self._module_fully_resolves(base, corrected):
                    suggestion = corrected
            self.finding(wf, line, segment, "missing-python-module",
                         f"top-level Python package '{top}' "
                         f"(from -m {module})", roots,
                         suggestion=suggestion)
            return
        if status == "not-package":
            self.finding(wf, line, segment, "missing-python-module",
                         f"Python submodule '{module}' (from -m {module}): "
                         f"'{res[2]}' is a module file, not a package",
                         [res[1]])
            return
        if status == "missing-main":
            _, dirs, _name = res
            self.finding(wf, line, segment, "missing-python-module",
                         f"Python package '{module}' has no __main__.py "
                         f"(from -m {module})",
                         [os.path.join(d, "__main__.py") for d in dirs])
            return
        # missing-sub: the parent package is repo-local but this part
        # exists in none of its (possibly merged namespace) portions.
        # Similarity is judged on the differing segment only (red
        # team: the shared dotted prefix inflated full-string ratios
        # until unrelated siblings always cleared the cutoff).
        _, dirs, prefix = res
        names = set()
        for d in dirs:
            names |= self._submodule_names(d)
        missing_part = parts[len(prefix.split("."))]
        sug_part = _suggest(missing_part, names)
        suggestion = (prefix + "." + sug_part) if sug_part else None
        self.finding(wf, line, segment, "missing-python-module",
                     f"Python submodule '{module}' (from -m {module})",
                     list(dirs), suggestion=suggestion)

    def resolve_workspace_member(self, base, val):
        """Resolve a --workspace/--filter value to a member dir or None."""
        v = val.strip().strip("'\"")
        if v.endswith("..."):
            v = v[:-3]
        if v.startswith("./"):
            v = v[2:]
        if "$" in v:
            return None
        cand = os.path.normpath(os.path.join(base, v))
        if os.path.isdir(cand) and os.path.isfile(
                os.path.join(cand, "package.json")):
            return cand
        for member in self.model.workspace_members(base):
            if self.model.package_name(member) == val:
                return member
            if os.path.basename(member) == val:
                return member
        return None

    # -- segment dispatch ---------------------------------------------------
    def check_segment(self, wf, line, segment, base):
        seg = segment.strip()
        if not seg or seg.startswith("#"):
            return
        if "${{" in seg:
            self.skip("github-expression")
            return
        toks = tokenize(seg)
        if toks is None:
            self.skip("unparsable-shell")
            return
        toks = normalise_tokens(toks)
        if not toks:
            self.skip("shell-construct")
            return
        # Runner wrappers: `uv run make lint`, `poetry run pytest`,
        # `bundle exec rake`, ... — unwrap and resolve the inner command.
        _WRAPPERS = {("uv", "run"), ("poetry", "run"), ("pipenv", "run"),
                     ("bundle", "exec"), ("conda", "run")}
        _FLAG_WITH_VALUE = {"-n", "-p", "--name", "--prefix", "--extra",
                            "--with", "--group", "--env", "-e"}
        for _ in range(2):
            if len(toks) >= 3 and (toks[0], toks[1]) in _WRAPPERS:
                inner = toks[2:]
                while inner and inner[0].startswith("-"):
                    flag = inner.pop(0)
                    if flag in _FLAG_WITH_VALUE and inner:
                        inner.pop(0)
                if not inner:
                    self.skip("external-tool")
                    return
                toks = inner
            else:
                break
        head = toks[0]
        if "$" in head or head.startswith("`"):
            self.skip("variable-command")
            return
        if any("$" in t for t in toks[:2]) and head in (
                "npm", "pnpm", "yarn", "bun", "make", "just", "task",
                "python", "python3", "bash", "sh", "node", "pip", "pip3"):
            self.skip("variable-argument")
            return

        # npm-family
        if head in ("npm", "pnpm", "yarn", "bun"):
            self._check_pkg_manager(wf, line, seg, base, head, toks)
            return
        # make
        if head == "make":
            self._check_make(wf, line, seg, base, toks)
            return
        # just
        if head == "just":
            self._check_just(wf, line, seg, base, toks)
            return
        # task (Taskfile)
        if head == "task":
            self._check_task(wf, line, seg, base, toks)
            return
        # pip file arguments (also `python -m pip ...`)
        if head in ("pip", "pip3") or (head in PY_NAMES and toks[1:3] == ["-m", "pip"]):
            rest = toks[1:] if head in ("pip", "pip3") else toks[3:]
            did = False
            for i, t in enumerate(rest):
                target = None
                if t in ("-r", "--requirement", "-c", "--constraint") \
                        and i + 1 < len(rest):
                    target = rest[i + 1]
                elif t.startswith(("--requirement=", "--constraint=")):
                    target = t.split("=", 1)[1]
                if target is not None:
                    if "$" in target:
                        self.skip("variable-argument")
                        return
                    self.check_file(wf, line, seg, base, target,
                                    "missing-requirements-file")
                    did = True
            if not did:
                self.skip("external-tool")
            return
        # interpreters with file / module args
        if head in FILE_INTERPRETERS:
            self._check_interpreter(wf, line, seg, base, head, toks)
            return
        # explicit relative path invocation ./x, ../x, .\x, or path/with/slash
        head_norm = head.replace("\\", "/") if "\\" in head else head
        if head_norm.startswith("./") or head_norm.startswith("../") or (
                "/" in head_norm and not head_norm.startswith("/")):
            if "$" in head_norm:
                self.skip("variable-argument")
                return
            self.check_file(wf, line, seg, base, head_norm,
                            "missing-script-file")
            return
        if head.startswith("/"):
            self.skip("absolute-path")
            return
        if head in BUILTINS or head in KEYWORDS:
            self.skip("shell-builtin")
            return
        if head in EXTERNAL:
            self.skip("external-tool")
            return
        # General rule: a bare command with no repo-local resolution
        # target is NOT checked.
        self.skip("bare-command-no-local-target")

    def _check_pkg_manager(self, wf, line, seg, base, head, toks):
        # Extract workspace / filter flags wherever they appear.
        ws_vals, ws_all, filter_val = [], False, None
        args = []
        i = 1
        while i < len(toks):
            t = toks[i]
            if t in ("--workspace", "-w") and i + 1 < len(toks):
                ws_vals.append(toks[i + 1])
                i += 2
                continue
            if t.startswith("--workspace="):
                ws_vals.append(t.split("=", 1)[1])
                i += 1
                continue
            if t == "--workspaces":
                ws_all = True
                i += 1
                continue
            if head == "pnpm" and t == "--filter" and i + 1 < len(toks):
                filter_val = toks[i + 1]
                i += 2
                continue
            if head == "pnpm" and t.startswith("--filter="):
                filter_val = t.split("=", 1)[1]
                i += 1
                continue
            args.append(t)
            i += 1
        toks = [head] + args

        def located_check(name):
            """Check a script name honouring workspace/filter selection."""
            if ws_all:
                self.skip("workspace")
                return
            if filter_val is not None:
                member = self.resolve_workspace_member(base, filter_val)
                if member is None:
                    self.skip("workspace")
                    return
                self.check_package_script(wf, line, seg, member, head, name)
                return
            if ws_vals:
                for val in ws_vals:
                    member = self.resolve_workspace_member(base, val)
                    if member is None:
                        self.skip("workspace")
                        return
                    self.check_package_script(
                        wf, line, seg, member, head, name)
                return
            self.check_package_script(wf, line, seg, base, head, name)

        if len(toks) < 2:
            self.skip("external-tool")  # bare yarn/pnpm = install
            return
        sub = toks[1]
        # yarn workspace <name> [run] X
        if head == "yarn" and sub == "workspace":
            if len(toks) < 3:
                self.skip("workspace")
                return
            member = self.resolve_workspace_member(base, toks[2])
            if member is None:
                self.skip("workspace")
                return
            rest = toks[3:]
            if rest and rest[0] == "run":
                rest = rest[1:]
            if not rest or rest[0].startswith("-") or rest[0] in YARN_BUILTINS:
                self.skip("external-tool")
                return
            if "$" in rest[0]:
                self.skip("variable-argument")
                return
            self.check_package_script(wf, line, seg, member, head, rest[0])
            return
        if head == "yarn" and sub == "workspaces":
            self.skip("workspace")
            return
        if sub == "run" or (head == "npm" and sub == "run-script"):
            if len(toks) < 3 or toks[2].startswith("-"):
                self.skip("no-script-name")
                return
            if "$" in toks[2]:
                self.skip("variable-argument")
                return
            located_check(toks[2])
            return
        if head == "npm" and sub in NPM_SCRIPT_SHORTCUTS:
            located_check(sub)
            return
        if head == "npm" and sub in NPM_BUILTINS:
            self.skip("external-tool"); return
        if head == "pnpm":
            if sub in PNPM_BUILTINS or sub.startswith("-"):
                self.skip("external-tool"); return
            if "$" in sub:
                self.skip("variable-argument"); return
            located_check(sub); return
        if head == "yarn":
            if sub in YARN_BUILTINS or sub.startswith("-"):
                self.skip("external-tool"); return
            if "$" in sub:
                self.skip("variable-argument"); return
            located_check(sub); return
        # bun: only `bun run X` (handled above); everything else external.
        self.skip("external-tool")

    def _check_make(self, wf, line, seg, base, toks):
        make_dir, mkfile, target, i = base, None, None, 1
        value_flags = {"-f", "--file", "-C", "--directory"}
        while i < len(toks):
            t = toks[i]
            if t in ("-C", "--directory") and i + 1 < len(toks):
                if "$" in toks[i + 1]:
                    self.skip("variable-argument"); return
                make_dir = os.path.normpath(os.path.join(make_dir, toks[i + 1]))
                i += 2; continue
            if t.startswith("-C") and len(t) > 2:
                if "$" in t[2:]:
                    self.skip("variable-argument"); return
                make_dir = os.path.normpath(os.path.join(make_dir, t[2:]))
                i += 1; continue
            if t in ("-f", "--file") and i + 1 < len(toks):
                if "$" in toks[i + 1]:
                    self.skip("variable-argument"); return
                mkfile = os.path.normpath(os.path.join(make_dir, toks[i + 1]))
                i += 2; continue
            if t.startswith("--file="):
                val = t.split("=", 1)[1]
                if "$" in val:
                    self.skip("variable-argument"); return
                mkfile = os.path.normpath(os.path.join(make_dir, val))
                i += 1; continue
            if t.startswith("-f") and len(t) > 2:
                if "$" in t[2:]:
                    self.skip("variable-argument"); return
                mkfile = os.path.normpath(os.path.join(make_dir, t[2:]))
                i += 1; continue
            if t in ("-j", "--jobs", "-l", "--load-average"):
                # -j/-l take an optional numeric argument.
                if i + 1 < len(toks) and re.fullmatch(r"\d+", toks[i + 1]):
                    i += 2
                else:
                    i += 1
                continue
            if t.startswith("-") or "=" in t:  # flags and VAR=value overrides
                i += 1; continue
            target = t
            break
        if target and "$" in target:
            self.skip("variable-argument"); return
        self.check_make(wf, line, seg, make_dir, target, mkfile)

    def _check_just(self, wf, line, seg, base, toks):
        recipe, justfile, i = None, None, 1
        value_flags = {"-f", "--justfile", "-d", "--working-directory",
                       "--set", "--dotenv-path", "--dotenv-filename",
                       "--tempdir", "--chooser", "--shell", "--shell-arg",
                       "--command-color", "--timestamp-format"}
        while i < len(toks):
            t = toks[i]
            if t in value_flags and i + 1 < len(toks):
                val = toks[i + 1]
                if "$" in val:
                    self.skip("variable-argument"); return
                if t in ("-f", "--justfile"):
                    justfile = os.path.normpath(os.path.join(base, val))
                elif t in ("-d", "--working-directory"):
                    base = os.path.normpath(os.path.join(base, val))
                i += 2; continue
            if t.startswith("--justfile="):
                val = t.split("=", 1)[1]
                if "$" in val:
                    self.skip("variable-argument"); return
                justfile = os.path.normpath(os.path.join(base, val))
                i += 1; continue
            if t.startswith("--working-directory="):
                val = t.split("=", 1)[1]
                if "$" in val:
                    self.skip("variable-argument"); return
                base = os.path.normpath(os.path.join(base, val))
                i += 1; continue
            if t.startswith("-") or "=" in t:
                i += 1; continue
            recipe = t; break
        if recipe and "$" in recipe:
            self.skip("variable-argument"); return
        self.check_just(wf, line, seg, base, recipe, justfile)

    def _check_task(self, wf, line, seg, base, toks):
        taskfile, targets, list_mode, i = None, [], False, 1
        value_flags = {"-t", "--taskfile", "-d", "--dir",
                       "-C", "--concurrency", "-o", "--output",
                       "--interval", "--tempdir", "--sort"}

        def use_taskfile(val):
            nonlocal taskfile
            if val == "-":
                return False        # Taskfile read from stdin
            taskfile = os.path.normpath(os.path.join(base, val))
            return True

        while i < len(toks):
            t = toks[i]
            if t == "--":
                break                   # the rest is CLI_ARGS, not tasks
            if t in ("-g", "--global"):
                # The global Taskfile lives in the user's home
                # directory, not in this repo.
                self.skip("outside-repo-root")
                return
            if t in ("--list", "-l", "--list-all", "-a", "--help",
                     "-h", "--version", "--init"):
                list_mode = True
                i += 1
                continue
            if t in value_flags and i + 1 < len(toks):
                val = toks[i + 1]
                if "$" in val:
                    self.skip("variable-argument"); return
                if t in ("-t", "--taskfile"):
                    if not use_taskfile(val):
                        self.skip("stdin-taskfile"); return
                elif t in ("-d", "--dir"):
                    base = os.path.normpath(os.path.join(base, val))
                i += 2
                continue
            if t.startswith("--taskfile=") or t.startswith("--dir="):
                val = t.split("=", 1)[1]
                if "$" in val:
                    self.skip("variable-argument"); return
                if t.startswith("--taskfile="):
                    if not use_taskfile(val):
                        self.skip("stdin-taskfile"); return
                else:
                    base = os.path.normpath(os.path.join(base, val))
                i += 1
                continue
            if t.startswith(("-t", "-d")) and len(t) > 2 \
                    and not t.startswith("--"):
                val = t[2:]
                if "$" in val:
                    self.skip("variable-argument"); return
                if t.startswith("-t"):
                    if not use_taskfile(val):
                        self.skip("stdin-taskfile"); return
                else:
                    base = os.path.normpath(os.path.join(base, val))
                i += 1
                continue
            if t.startswith("-"):
                i += 1
                continue                # other flags: no static effect
            if "=" in t:
                i += 1
                continue                # VAR=value assignment
            targets.append(t)
            i += 1
        if any("$" in t or "{{" in t for t in targets):
            self.skip("variable-argument")
            return
        if not targets:
            # `task --list` only needs the file to exist; bare `task`
            # runs the task named `default`.
            self.check_task(wf, line, seg, base, None, taskfile,
                            bare=not list_mode)
            return
        for target in targets:          # `task lint test` runs both
            self.check_task(wf, line, seg, base, target, taskfile)

    def _check_interpreter(self, wf, line, seg, base, head, toks):
        args = toks[1:]
        if head in PY_NAMES:
            self._check_python(wf, line, seg, base, head, args)
            return
        if head == "node":
            value_flags = {"--input-type", "-r", "--require", "--import",
                           "--loader", "--experimental-loader",
                           "--conditions", "-C", "--env-file",
                           "--max-old-space-size", "--cpu-prof-dir"}
            file_arg = None
            i = 0
            while i < len(args):
                t = args[i]
                if t in ("-e", "--eval"):
                    self.skip("inline-code"); return
                if t == "--":
                    if i + 1 < len(args):
                        file_arg = args[i + 1]
                    break
                if t in value_flags:
                    i += 2; continue
                if "=" in t and t.split("=", 1)[0] in value_flags:
                    i += 1; continue
                if t.startswith("-"):
                    i += 1; continue
                file_arg = t
                break
            self._check_interp_file(wf, line, seg, base, file_arg)
            return
        # bash / sh / zsh / dash: only -c is inline code; -e/-x/-u are
        # plain mode flags. -o takes an option name as its value.
        i = 0
        file_arg = None
        while i < len(args):
            t = args[i]
            if t == "-c" or (t.startswith("-") and not t.startswith("--")
                             and len(t) > 1 and "c" in t[1:]
                             and all(ch in "cexluvsrio" for ch in t[1:])):
                self.skip("inline-code"); return
            if t == "--":
                if i + 1 < len(args):
                    file_arg = args[i + 1]
                break
            if t == "-o":
                i += 2; continue
            if t in ("--rcfile", "--init-file"):
                i += 2; continue
            if t.startswith("-"):
                i += 1; continue
            file_arg = t
            break
        self._check_interp_file(wf, line, seg, base, file_arg)

    def _check_python(self, wf, line, seg, base, head, args):
        value_flags = {"-W", "-X", "-Q"}
        i = 0
        while i < len(args):
            t = args[i]
            if t == "-c":
                self.skip("inline-code"); return
            if t == "-m":
                if i + 1 >= len(args):
                    self.skip("no-module-name"); return
                module = args[i + 1]
                if "$" in module:
                    self.skip("variable-argument"); return
                top = module.split(".")[0]
                # Stdlib modules (http.server, unittest, ...) are not
                # repo-local — UNLESS a local regular package or module
                # file shadows the stdlib name (auditor M1). A mere
                # namespace portion does NOT shadow it: the stdlib
                # regular package wins over namespace portions, so
                # those keep the v1 skip.
                stdlib = getattr(sys, "stdlib_module_names", frozenset())
                if top in stdlib:
                    if self._top_shadows_stdlib(base, top):
                        self.check_python_module(
                            wf, line, seg, base, module)
                    else:
                        self.skip("external-tool")
                    return
                # Repo-local existence is checked FIRST.
                if self._module_exists(base, top):
                    self.check_python_module(wf, line, seg, base, module)
                    return
                # Fallback: known installed tools are assumed installed.
                if top in KNOWN_EXTERNAL_MODULES:
                    self.skip("external-tool"); return
                # If the workflow itself installs Python packages, an
                # unknown module plausibly comes from one of them.
                if self.workflow_installs_python:
                    self.skip("assumed installed (workflow installs packages)")
                    return
                self.check_python_module(wf, line, seg, base, module)
                return
            if t == "--":
                if i + 1 < len(args):
                    self._check_interp_file(wf, line, seg, base, args[i + 1])
                else:
                    self.skip("external-tool")
                return
            if t in value_flags:
                i += 2; continue
            if any(t.startswith(f) and len(t) > len(f) for f in value_flags):
                i += 1; continue        # attached form, e.g. -Wignore
            if t.startswith("-"):
                i += 1; continue
            self._check_interp_file(wf, line, seg, base, t)
            return
        self.skip("external-tool")

    def _check_interp_file(self, wf, line, seg, base, arg):
        if arg is None:
            self.skip("external-tool"); return
        if "$" in arg:
            self.skip("variable-argument"); return
        if "/" in arg or "\\" in arg or arg.endswith(
                (".py", ".js", ".mjs", ".cjs", ".sh", ".bash")):
            self.check_file(wf, line, seg, base, arg, "missing-script-file")
        else:
            self.skip("bare-command-no-local-target")

    # -- steps ---------------------------------------------------------------
    def check_step(self, wf, step):
        if step.disabled:
            for entry in step.runs:
                self.skip("if-false")
            return
        # A second actions/checkout with a path: fetches another tree
        # there — everything under that path counts as created.
        if step.uses and "actions/checkout" in step.uses:
            self.checkout_seen += 1
            if self.checkout_seen >= 2:
                for p in step.checkout_paths:
                    if p and p not in (".", "./"):
                        self._register_created_dir(self.root, p)
        if step.shell:
            shell_name = os.path.basename(
                step.shell.strip().split()[0].strip("'\"").replace("\\", "/")
                .lower()) if step.shell.strip() else ""
            if shell_name.endswith(".exe"):
                shell_name = shell_name[:-4]
            if shell_name not in SHELL_NAMES:
                for entry in step.runs:
                    self.skip("non-shell run body")
                return
        wd = step.wd if step.wd is not None else step.default_wd
        if wd is not None and ("${{" in wd or "$" in wd):
            for entry in step.runs:
                n_lines = sum(1 for _, t in entry.lines if t.strip())
                for _ in range(max(n_lines, 1)):
                    self.skip("expression-working-directory")
            return
        base = self.root if wd is None else os.path.normpath(
            os.path.join(self.root, _unquote(wd)))
        if not self._within_root(base):
            for entry in step.runs:
                n_lines = sum(1 for _, t in entry.lines if t.strip())
                for _ in range(max(n_lines, 1)):
                    self.skip("outside-repo-root")
            return
        for entry in step.runs:
            # Join backslash continuations, keeping the starting line no.
            logical = []
            buf, buf_line = None, None
            for ln, txt in entry.lines:
                if buf is None:
                    buf, buf_line = txt, ln
                else:
                    buf += txt
                if buf.rstrip().endswith("\\"):
                    buf = buf.rstrip()[:-1] + " "
                    continue
                logical.append((buf_line, buf)); buf = None
            if buf is not None:
                logical.append((buf_line, buf))
            # A `cd <dir>` segment shifts the resolution base for the
            # rest of this run block, exactly as it would in a shell —
            # except inside a subshell group or an if/while condition,
            # where it does not persist.
            entry_base = base
            prev_base = None
            paren_depth = 0
            in_condition = False
            heredocs = []
            sub_bases = {}          # paren depth -> base inside subshell
            for ln, txt in logical:
                if heredocs:
                    # Heredoc body lines are data, never commands.
                    if txt.strip() == heredocs[0]:
                        heredocs.pop(0)
                    continue
                line = strip_comment(txt)
                heredocs.extend(find_heredocs(line))
                clean = strip_substitutions(line)
                seg_list = split_with_ops(clean)
                for si, (seg_text, op) in enumerate(seg_list):
                    seg = seg_text.strip()
                    depth_at_start = paren_depth
                    paren_depth += net_parens(seg_text)
                    if not seg:
                        continue
                    # Subshell bases only apply while we stay at or
                    # below the depth where their `cd` happened.
                    for k in [k for k in sub_bases if k > depth_at_start]:
                        del sub_bases[k]
                    eff_base = entry_base
                    for k in sorted(sub_bases):
                        if k <= depth_at_start:
                            eff_base = sub_bases[k]
                    op_after = seg_list[si + 1][1] if si + 1 < len(seg_list) \
                        else None
                    raw_first = seg.split(None, 1)[0].lstrip("({").strip()
                    cond_segment = raw_first in ("if", "elif", "while",
                                                 "until")
                    if raw_first in ("then", "do"):
                        in_condition = False
                    toks_try = tokenize(seg)
                    toks_norm = normalise_tokens(toks_try) if toks_try else None
                    if toks_norm and toks_norm[0] == "cd":
                        starts_subshell = seg.lstrip().startswith("(")
                        args = toks_norm[1:]
                        if args and args[0] == "--":
                            args = args[1:]
                        single = len(args) == 1 and "$" not in args[0]
                        if depth_at_start == 0 and not in_condition \
                                and not cond_segment and not starts_subshell:
                            if single:
                                if args[0] == "-":
                                    if prev_base is not None:
                                        entry_base, prev_base = \
                                            prev_base, entry_base
                                elif args[0] != "~":
                                    prev_base = entry_base
                                    entry_base = os.path.normpath(
                                        os.path.join(entry_base, args[0]))
                        elif single and args[0] not in ("-", "~"):
                            # cd inside a subshell: applies to the
                            # rest of that subshell only.
                            key = depth_at_start + (1 if starts_subshell
                                                    else 0)
                            sub_bases[key] = os.path.normpath(
                                os.path.join(eff_base, args[0]))
                        self.skip("shell-builtin")
                        if cond_segment:
                            in_condition = True
                        continue
                    # A segment joined by || on either side has its
                    # failure tolerated (e.g. `cmd || true`).
                    self._downgrade = bool(
                        op == "||" or op_after == "||" or step.coe)
                    self.check_segment(wf, ln, seg, eff_base)
                    self._downgrade = False
                    self.detect_creations(seg, eff_base)
                    if cond_segment:
                        in_condition = True


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def discover(root):
    wf_dir = os.path.join(root, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        return None, []
    files = []
    for name in sorted(os.listdir(wf_dir)):
        path = os.path.join(wf_dir, name)
        # Top-level only: files in subdirectories are ignored by GitHub
        # too. Symlinks are included on purpose: a symlink loop must
        # surface as unscanned, not be silently dropped.
        if (os.path.isfile(path) or os.path.islink(path)) \
                and name.lower().endswith((".yml", ".yaml")):
            files.append(path)
    return wf_dir, files


def scan(root):
    root = os.path.abspath(root)
    wf_dir, files = discover(root)
    result = {"root": root, "workflows": [], "unscanned": [],
              "findings": [], "checked": 0, "skipped": {},
              "warnings": [], "exit": 0}
    if wf_dir is None:
        result["unscanned"].append({
            "file": ".github/workflows", "reason": "no .github/workflows directory"})
        result["exit"] = 2
        return result
    if not files:
        result["unscanned"].append({
            "file": ".github/workflows",
            "reason": "no workflow files (.yml/.yaml) found"})
        result["exit"] = 2
        return result
    checker = Checker(root)
    for path in files:
        rel = os.path.relpath(path, root)
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            result["unscanned"].append({"file": rel, "reason": str(exc)})
            continue
        if size > MAX_FILE_BYTES:
            result["unscanned"].append({"file": rel, "reason": "file exceeds 1MB cap"})
            continue
        text, err = read_capped(path)
        if text is None:
            result["unscanned"].append({"file": rel, "reason": err or "unreadable"})
            continue
        if "\x00" in text:
            result["unscanned"].append(
                {"file": rel, "reason": "binary content (NUL byte)"})
            continue
        if text.strip() == "":
            result["unscanned"].append({"file": rel, "reason": "empty file"})
            continue
        steps, errors, default_wd = extract_steps(text)
        if errors:
            result["unscanned"].append(
                {"file": rel, "reason": "; ".join(errors[:5])})
            continue
        result["workflows"].append(rel)
        checker.begin_workflow(steps)
        for step in steps:
            checker.check_step(rel, step)
    for entry in checker.fatal_errors:
        if entry not in result["unscanned"]:
            result["unscanned"].append(entry)
    result["findings"] = checker.findings
    result["checked"] = checker.checked
    result["skipped"] = checker.skipped
    result["warnings"] = checker.model.warnings
    error_findings = any(f.get("severity", "error") == "error"
                         for f in result["findings"])
    if result["unscanned"]:
        result["exit"] = 2
    elif error_findings:
        result["exit"] = 1
    return result


def render_text(r):
    out = []
    out.append(f"CI Command Truth — root: {r['root']}")
    out.append(f"Workflows scanned: {len(r['workflows'])}")
    for w in r["workflows"]:
        out.append(f"  scanned: {w}")
    for u in r["unscanned"]:
        out.append(f"  UNSCANNED: {u['file']} — {u['reason']}")
    for w in r["warnings"]:
        out.append(f"  warning: {w}")
    out.append(f"Segments checked: {r['checked']}")
    total_skip = sum(r["skipped"].values())
    out.append(f"Segments skipped: {total_skip}")
    for reason, n in sorted(r["skipped"].items()):
        out.append(f"  skipped[{reason}]: {n}")
    if r["findings"]:
        out.append(f"Findings: {len(r['findings'])}")
        for f in r["findings"]:
            tag = " [warning]" if f.get("severity") == "warning" else ""
            out.append(f"  {f['file']}:{f['line']}: `{f['segment']}` — "
                       f"{f['message']}{tag}")
    else:
        out.append("Findings: 0")
    parts = []
    if any(f.get("severity", "error") == "error" for f in r["findings"]):
        parts.append("FAIL — missing commands/targets/files found.")
    if r["unscanned"]:
        parts.append("ERROR — some workflow files could not be scanned.")
    if not parts:
        parts.append("OK — every checked command resolves.")
    out.append(" ".join(parts))
    return "\n".join(out)


def _escape_annotation_data(text):
    return (str(text).replace("%", "%25").replace("\r", "%0D")
            .replace("\n", "%0A"))


def _escape_annotation_prop(text):
    # GitHub workflow-command property values additionally escape
    # ':' and ',' (auditor M3).
    return (_escape_annotation_data(text)
            .replace(":", "%3A").replace(",", "%2C"))


def render_annotations(r):
    lines = []
    for f in r["findings"]:
        msg = _escape_annotation_data(f["message"])
        level = "warning" if f.get("severity") == "warning" else "error"
        lines.append(f"::{level} file={_escape_annotation_prop(f['file'])}"
                     f",line={f['line']}::{msg}")
    for u in r["unscanned"]:
        lines.append(
            f"::warning file={_escape_annotation_prop(u['file'])}::"
            f"unscanned: {_escape_annotation_data(u['reason'])}")
    return lines


# --------------------------------------------------------------------------
# SARIF 2.1.0 output
#
# Findings become results (error findings -> level "error",
# warning-severity findings -> level "warning"). Unscanned files are
# NOT results and never fabricate a clean pass: they are carried as
# tool-execution notifications (level "error") on the run's invocation,
# with the count also in run properties, mirroring exit code 2.
# Artifact locations are repo-relative URIs, percent-encoded, so no
# absolute path and no control character from workflow text can break
# or leak through the document.
# --------------------------------------------------------------------------
_SARIF_KIND_TEXT = {
    "missing-npm-script": "npm script referenced by a workflow does not exist",
    "missing-pnpm-script": "pnpm script referenced by a workflow does not exist",
    "missing-yarn-script": "yarn script referenced by a workflow does not exist",
    "missing-bun-script": "bun script referenced by a workflow does not exist",
    "missing-makefile": "Makefile referenced by a workflow does not exist",
    "missing-make-target": "make target referenced by a workflow does not exist",
    "missing-justfile": "justfile referenced by a workflow does not exist",
    "missing-just-recipe": "just recipe referenced by a workflow does not exist",
    "missing-taskfile": "Taskfile referenced by a workflow does not exist",
    "missing-task-target": "Taskfile task referenced by a workflow does not exist",
    "missing-file": "file referenced by a workflow does not exist",
    "missing-script-file": "script file referenced by a workflow does not exist",
    "missing-requirements-file": "requirements file referenced by a workflow does not exist",
    "missing-python-module": "Python module referenced by a workflow does not exist",
    "unscanned-workflow": "workflow file could not be scanned",
}


def _sarif_uri(rel_path):
    # quote_from_bytes over the filesystem encoding: a legal but
    # non-UTF-8 filename (surrogates under surrogateescape) must
    # percent-encode, never crash the whole SARIF document (red team).
    rel = str(rel_path).replace(os.sep, "/")
    return urllib.parse.quote_from_bytes(os.fsencode(rel), safe="/")


def render_sarif(r):
    # Stable taxonomy (auditor L3): the full rule table is emitted on
    # every run, plus any kind this run produced that is not in it, so
    # every result/notification ruleId always resolves.
    kinds = sorted(set(_SARIF_KIND_TEXT)
                   | {f["kind"] for f in r["findings"]})
    rules = []
    for kind in kinds:
        text = _SARIF_KIND_TEXT.get(
            kind, "workflow reference does not resolve: " + kind)
        rules.append({
            "id": kind,
            "name": kind,
            "shortDescription": {"text": text},
            "fullDescription": {"text": text},
            "properties": {"precision": "high"},
        })
    results = []
    for f in r["findings"]:
        props = {
            "kind": f["kind"],
            "segment": f["segment"],
            "expected": f["expected"],
            "severity": f.get("severity", "error"),
            "lookedIn": [_sarif_uri(p) for p in f.get("looked_in", [])],
        }
        if f.get("suggestion"):
            props["suggestion"] = f["suggestion"]
        results.append({
            "ruleId": f["kind"],
            "level": "warning" if f.get("severity") == "warning" else "error",
            "message": {"text": f["message"]},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": _sarif_uri(f["file"])},
                    "region": {"startLine": max(1, int(f["line"]))},
                },
            }],
            "properties": props,
        })
    notifications = [{
        "level": "error",
        "message": {"text": f"unscanned: {u['file']} — {u['reason']}"},
        "associatedRule": {"id": "unscanned-workflow"},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": _sarif_uri(u["file"])},
                "region": {"startLine": 1},
            },
        }],
        "properties": {"file": u["file"], "reason": u["reason"]},
    } for u in r["unscanned"]]
    run = {
        "tool": {"driver": {
            "name": "CI Command Truth",
            "version": VERSION,
            "semanticVersion": VERSION,
            "informationUri": "https://github.com/RakTikoo/ci-command-truth",
            "rules": rules,
        }},
        "invocations": [{
            # The scan itself did not complete cleanly when files were
            # left unscanned (auditor L2).
            "executionSuccessful": not r["unscanned"],
            "toolExecutionNotifications": notifications,
        }],
        "results": results,
        "properties": {
            "checked": r["checked"],
            "skipped": r["skipped"],
            "unscannedCount": len(r["unscanned"]),
            "exitCode": r["exit"],
        },
    }
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [run],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Prove every run: command in .github/workflows exists.")
    ap.add_argument("root", nargs="?", default=".",
                    help="repository root (default: current directory)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--sarif", action="store_true",
                    help="SARIF 2.1.0 output (mutually exclusive with --json)")
    ap.add_argument("--github-annotations", action="store_true",
                    help="also emit ::error/::warning workflow commands")
    args = ap.parse_args(argv)
    if args.json and args.sarif:
        ap.error("--json and --sarif are mutually exclusive output modes")
    if args.github_annotations and (args.json or args.sarif):
        # Auditor M2: appending annotation lines to a JSON/SARIF
        # document corrupts it for machine consumers. Annotations pair
        # with the default text output (as the bundled Action uses).
        ap.error("--github-annotations cannot be combined with "
                 "--json or --sarif (it would corrupt the document)")
    if not os.path.isdir(args.root):
        if args.sarif:
            bad = {"root": args.root, "workflows": [],
                   "unscanned": [{"file": args.root,
                                  "reason": "root is not a directory"}],
                   "findings": [], "checked": 0, "skipped": {},
                   "warnings": [], "exit": 2}
            print(json.dumps(render_sarif(bad), indent=2, sort_keys=True))
        elif args.json:
            print(json.dumps(
                {"error": f"root {args.root!r} is not a directory",
                 "exit": 2}, indent=2, sort_keys=True))
        print(f"error: root {args.root!r} is not a directory", file=sys.stderr)
        return 2
    r = scan(args.root)
    if args.sarif:
        print(json.dumps(render_sarif(r), indent=2, sort_keys=True))
    elif args.json:
        print(json.dumps(r, indent=2, sort_keys=True))
    else:
        print(render_text(r))
    if args.github_annotations:
        for line in render_annotations(r):
            print(line)
    return r["exit"]


if __name__ == "__main__":
    sys.exit(main())
