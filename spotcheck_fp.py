#!/usr/bin/env python3
"""False-positive spotcheck for CI Command Truth.

Builds the FP hunters' headline cases as fresh temp sandboxes (not the
committed fixtures) and asserts each is either clean or skipped with a
named reason — never an error finding. Run: python3 spotcheck_fp.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ci_command_truth as cct  # noqa: E402

HDR = "name: t\non: push\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n"


def build(files):
    d = tempfile.mkdtemp(prefix="cct-spot-")
    for rel, content in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(content)
    return d


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("workspace npm forms")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: npm run test --workspace=packages/foo\n"
        "      - run: npm run test -w foo\n"
        "      - run: npm run anything --workspaces\n",
        "package.json": '{"name":"root","workspaces":["packages/*"],'
                        '"scripts":{"root":"x"}}',
        "packages/foo/package.json": '{"name":"foo","scripts":{"test":"x"}}',
    }), ()


@case("make include / -f / pattern rule")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: make extra\n"
        "      - run: make -f alt.mk alttarget\n"
        "      - run: make foo.o\n",
        "Makefile": "include extra.mk\n\ntest:\n\techo ok\n\n%.o: %.c\n\tcc -c $<\n",
        "extra.mk": "extra:\n\techo extra\n",
        "alt.mk": "alttarget:\n\techo alt\n",
    }), ()


@case("just defaults / @quiet / alias / mod")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: just build\n"
        "      - run: just quiet\n"
        "      - run: just t\n"
        "      - run: just frommod\n",
        "justfile": "alias t := test\n\nmod foo\n\ntest:\n    echo ok\n\n"
                    "build target='release':\n    echo b\n\n"
                    "@quiet:\n    echo q\n",
        "foo.just": "frommod:\n    echo m\n",
    }), ()


@case("per-job defaults reset")
def _():
    return build({
        ".github/workflows/ci.yml":
        "name: t\non: push\ndefaults:\n  run:\n"
        "    working-directory: app\njobs:\n"
        "  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: npm run test\n"
        "  b:\n    runs-on: ubuntu-latest\n    defaults:\n      run:\n"
        "        working-directory: .\n    steps:\n"
        "      - run: npm run root-test\n"
        "  c:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: npm run test\n",
        "package.json": '{"scripts":{"root-test":"x"}}',
        "app/package.json": '{"scripts":{"test":"x"}}',
    }), ()


@case("heredoc body is data")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: |\n          cat <<'EOF'\n"
        "          npm run not-real\n          ./missing.sh\n"
        "          EOF\n          npm run test\n",
        "package.json": '{"scripts":{"test":"x"}}',
    }), ()


@case("if: false step and job")
def _():
    return build({
        ".github/workflows/ci.yml":
        "name: t\non: push\njobs:\n"
        "  off:\n    runs-on: ubuntu-latest\n    if: ${{ false }}\n"
        "    steps:\n      - run: npm run nope\n"
        "  on:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - if: false\n        run: npm run nope\n"
        "      - run: npm run test\n",
        "package.json": '{"scripts":{"test":"x"}}',
    }), ("if-false",)


@case("|| true downgrade")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: npm run nope || true\n",
        "package.json": '{"scripts":{"test":"x"}}',
    }), ()


@case("windows backslash path")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: .\\scripts\\run.sh\n"
        "      - run: python tools\\check.py\n",
        "scripts/run.sh": "echo ok\n",
        "tools/check.py": "print(1)\n",
    }), ()


@case("dynamic gen.sh (redirect then run)")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: echo \"echo hi\" > gen.sh\n"
        "      - run: bash gen.sh\n",
        "package.json": '{"scripts":{"test":"x"}}',
    }), ("created earlier in workflow",)


@case("v0.2 namespace package submodule")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: python -m nspkg.mod\n"
        "      - run: python -m nspkg.inner.leaf\n",
        "nspkg/mod.py": "x = 1\n",
        "nspkg/inner/leaf.py": "x = 1\n",
    }), ()


@case("v0.2 src-layout submodule")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: python -m spkg.run\n"
        "      - run: python -m spkg.deep.leaf\n",
        "src/spkg/__init__.py": "",
        "src/spkg/run.py": "x = 1\n",
        "src/spkg/deep/__init__.py": "",
        "src/spkg/deep/leaf.py": "x = 1\n",
    }), ()


@case("v0.2 dynamic module (__getattr__) skipped")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: python -m pkg.lazything\n",
        "pkg/__init__.py": "def __getattr__(name):\n    return object()\n",
    }), ("dynamic-module",)


@case("v0.2 split namespace root+src portions")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: python -m pkg.a\n"
        "      - run: python -m pkg.b\n",
        "pkg/a.py": "x = 1\n",
        "src/pkg/b.py": "x = 1\n",
    }), ()


@case("second checkout with path:")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n          path: other\n"
        "      - run: bash other/tool.sh\n",
    }), ("created earlier in workflow",)


@case("taskfile tasks: alias, namespace, flags, bare default")
def _():
    return build({
        ".github/workflows/ci.yml": HDR +
        "      - run: task build\n"
        "      - run: task b\n"
        "      - run: task ci:verify\n"
        "      - run: task --silent test\n"
        "      - run: task --list\n"
        "      - run: task\n",
        "Taskfile.yml": "version: '3'\n"
                        "includes:\n  ci: ./taskfiles/ci.yml\n"
                        "tasks:\n  default:\n    cmds: [task --list]\n"
                        "  build:\n    aliases: [b]\n"
                        "    cmds: [echo build]\n"
                        "  test:\n    cmds: [echo test]\n",
        "taskfiles/ci.yml": "version: '3'\n"
                            "tasks:\n  verify:\n    cmds: [echo v]\n",
    }), ()


def main():
    failures = 0
    for name, fn in CASES:
        root, expect_skips = fn()
        r = cct.scan(root)
        errors = [f for f in r["findings"]
                  if f.get("severity", "error") == "error"]
        ok = not errors and r["exit"] != 2
        for reason in expect_skips:
            ok = ok and r["skipped"].get(reason, 0) >= 1
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"{status}  {name}: exit={r['exit']} "
              f"error_findings={len(errors)} findings={len(r['findings'])} "
              f"skipped={r['skipped']}")
        for f in errors:
            print(f"      FP: {f['file']}:{f['line']} `{f['segment']}` "
                  f"— {f['message']}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} spotcheck cases clean "
          f"or skipped-with-reason")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
