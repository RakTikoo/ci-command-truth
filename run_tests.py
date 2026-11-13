#!/usr/bin/env python3
"""Self-contained tests for CI Command Truth. Zero dependencies.

Run:  python3 run_tests.py
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "ci_command_truth.py")
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, HERE)

import ci_command_truth as cct  # noqa: E402


def run_tool(fixture):
    proc = subprocess.run(
        [sys.executable, TOOL, os.path.join(FIXTURES, fixture), "--json"],
        capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


CLEAN = ["clean-npm", "clean-make", "clean-just", "clean-scripts",
         "clean-chains-env", "clean-expressions", "clean-multiline",
         "clean-working-dir", "clean-wrappers",
         # Fix-pass regression fixtures (adversarial-review findings):
         "clean-pnpm-yarn-bun", "clean-folded", "clean-per-job-defaults",
         "clean-python-known", "clean-nested-run", "clean-matrix-steps",
         "clean-just-advanced", "clean-make-advanced", "clean-heredoc",
         "clean-trailing-comment", "clean-if-false", "clean-workspaces",
         "clean-backslash", "clean-created", "clean-shell-skip",
         "clean-python-flags", "clean-env-subst", "clean-cd-advanced",
         "clean-install-python-m", "clean-block-indicator",
         # v0.2: python -m submodule fixtures
         "clean-python-submodule", "clean-python-namespace"]
MISSING = {  # fixture -> expected finding kind
    "missing-npm-script": "missing-npm-script",
    "missing-make-target": "missing-make-target",
    "missing-just-recipe": "missing-just-recipe",
    "missing-script-file": "missing-script-file",
    "missing-python-module": "missing-python-module",
    "missing-requirements": "missing-requirements-file",
    # v0.2: planted missing submodule in a repo-local package
    "missing-python-submodule": "missing-python-module",
}


class CorpusTests(unittest.TestCase):
    def test_clean_fixtures_have_zero_findings(self):
        for name in CLEAN:
            with self.subTest(fixture=name):
                code, r = run_tool(name)
                self.assertEqual(r["findings"], [], f"{name}: {r['findings']}")
                self.assertEqual(code, 0, f"{name} exit {code}")
                if name == "clean-expressions":
                    # By design every segment there is an expression or a
                    # variable, so the correct behaviour is all-skipped.
                    self.assertGreater(sum(r["skipped"].values()), 0)
                else:
                    self.assertGreater(r["checked"], 0, f"{name} checked nothing")

    def test_missing_fixtures_find_exactly_the_planted_one(self):
        for name, kind in MISSING.items():
            with self.subTest(fixture=name):
                code, r = run_tool(name)
                self.assertEqual(code, 1)
                self.assertEqual(len(r["findings"]), 1, r["findings"])
                self.assertEqual(r["findings"][0]["kind"], kind)
                f = r["findings"][0]
                self.assertTrue(f["file"].endswith("ci.yml"))
                self.assertGreaterEqual(f["line"], 1)
                self.assertTrue(f["expected"])
                self.assertTrue(f["looked_in"])

    def test_expressions_are_skipped_not_flagged(self):
        code, r = run_tool("clean-expressions")
        self.assertEqual(code, 0)
        skipped = sum(r["skipped"].values())
        self.assertGreaterEqual(skipped, 2)


class EdgeTests(unittest.TestCase):
    def test_no_run_steps(self):
        code, r = run_tool("edge-no-run")
        self.assertEqual((code, r["findings"], r["checked"]), (0, [], 0))

    def test_uses_only(self):
        code, r = run_tool("edge-uses-only")
        self.assertEqual((code, r["findings"]), (0, []))

    def test_empty_file_is_listed_unscanned_never_silent(self):
        code, r = run_tool("edge-empty")
        self.assertEqual(code, 2)
        self.assertEqual(len(r["unscanned"]), 1)
        self.assertIn("empty", r["unscanned"][0]["reason"])

    def test_malformed_is_listed_unscanned(self):
        code, r = run_tool("edge-malformed")
        self.assertEqual(code, 2)
        self.assertEqual(len(r["unscanned"]), 1)
        self.assertIn("tab", r["unscanned"][0]["reason"])

    def test_crlf_workflow_parses_clean(self):
        code, r = run_tool("edge-crlf")
        self.assertEqual((code, r["findings"]), (0, []))
        self.assertGreater(r["checked"], 0)

    def test_nested_workflow_subdir_ignored(self):
        # GitHub only loads top-level files in .github/workflows; the
        # nested file deliberately references a missing script and must
        # not produce a finding.
        code, r = run_tool("edge-nested-subdir")
        self.assertEqual((code, r["findings"]), (0, []))
        self.assertEqual(len(r["workflows"]), 1)

    def test_missing_workflows_dir_is_exit_2(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run([sys.executable, TOOL, d, "--json"],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            r = json.loads(proc.stdout)
            self.assertEqual(len(r["unscanned"]), 1)

    def test_empty_workflows_dir_is_unscanned_exit_2(self):
        code, r = run_tool("edge-empty-workflows-dir")
        self.assertEqual(code, 2)
        self.assertEqual(len(r["unscanned"]), 1)
        self.assertIn("no workflow files", r["unscanned"][0]["reason"])

    def test_malformed_package_json_is_exit_2_not_a_warning(self):
        code, r = run_tool("edge-malformed-package-json")
        self.assertEqual(code, 2)
        self.assertEqual(r["findings"], [])
        self.assertTrue(any("package.json" in u["file"]
                            and "malformed" in u["reason"]
                            for u in r["unscanned"]), r["unscanned"])

    def test_downgraded_findings_are_warnings_and_do_not_fail(self):
        code, r = run_tool("special-downgrade")
        self.assertEqual(code, 0, r)
        self.assertEqual(len(r["findings"]), 2)
        self.assertTrue(all(f["severity"] == "warning"
                            for f in r["findings"]))

    def test_binary_workflow_is_unscanned(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wf = os.path.join(d, ".github", "workflows")
            os.makedirs(wf)
            with open(os.path.join(wf, "ci.yml"), "wb") as fh:
                fh.write(b"name: x\n\x00\x01\x02garbage")
            r = cct.scan(d)
            self.assertEqual(r["exit"], 2)
            self.assertIn("binary", r["unscanned"][0]["reason"])

    def test_symlink_loop_workflow_is_unscanned_not_dropped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wf = os.path.join(d, ".github", "workflows")
            os.makedirs(wf)
            os.symlink("loop.yml", os.path.join(wf, "loop.yml"))
            r = cct.scan(d)
            self.assertEqual(r["exit"], 2)
            self.assertEqual(len(r["unscanned"]), 1)
            self.assertIn("loop.yml", r["unscanned"][0]["file"])

    def test_exit_precedence_findings_plus_unscanned_is_2(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wf = os.path.join(d, ".github", "workflows")
            os.makedirs(wf)
            with open(os.path.join(d, "package.json"), "w") as fh:
                fh.write('{"scripts": {"test": "x"}}')
            with open(os.path.join(wf, "a.yml"), "w") as fh:
                fh.write("name: t\non: push\njobs:\n  t:\n"
                         "    runs-on: ubuntu-latest\n    steps:\n"
                         "      - run: npm run nosuchscript\n")
            with open(os.path.join(wf, "b.yml"), "w") as fh:
                fh.write("")
            r = cct.scan(d)
            self.assertEqual(r["exit"], 2)
            self.assertEqual(len(r["findings"]), 1)
            text = cct.render_text(r)
            self.assertIn("FAIL", text)
            self.assertIn("ERROR", text)


class FixPassUnitTests(unittest.TestCase):
    def test_read_capped_reads_up_to_real_1mb_cap(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "big.txt")
            with open(p, "w") as fh:
                fh.write("x" * 500_000)   # > old bogus 200_001 truncation
            text, err = cct.read_capped(p)
            self.assertIsNone(err)
            self.assertEqual(len(text), 500_000)
            with open(p, "w") as fh:
                fh.write("x" * 1_100_000)
            text, err = cct.read_capped(p)
            self.assertIsNone(text)
            self.assertEqual(err, "oversized")

    def test_nonstring_script_value_does_not_count_as_present(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "package.json"), "w") as fh:
                fh.write('{"scripts": {"test": 42}}')
            scripts, _ = cct.RepoModel(d).package_scripts(d)
            self.assertNotIn("test", scripts)

    def test_deeply_nested_package_json_is_malformed_not_crash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "package.json"), "w") as fh:
                fh.write('{"a": ' + "[" * 20000 + "]" * 20000 + "}")
            data, _ = cct.RepoModel(d).package_data(d)
            self.assertEqual(data, "malformed")

    def test_bare_dash_step_and_unknown_first_key(self):
        text = ("jobs:\n  t:\n    steps:\n      -\n"
                "        timeout-minutes: 5\n        run: npm run test\n"
                "      - something-custom: 1\n        run: npm run test\n")
        steps, errors, _ = cct.extract_steps(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(steps), 2)
        self.assertTrue(all(len(s.runs) == 1 for s in steps))

    def test_anchor_and_tag_on_run_are_stripped(self):
        text = ("jobs:\n  t:\n    steps:\n"
                "      - run: &cmd npm run test\n"
                "      - run: !!str npm run build\n")
        steps, errors, _ = cct.extract_steps(text)
        self.assertEqual(errors, [])
        self.assertEqual(steps[0].runs[0].lines[0][1], "npm run test")
        self.assertEqual(steps[1].runs[0].lines[0][1], "npm run build")

    def test_flow_style_mentions_run_but_no_steps_is_error(self):
        text = "jobs: {t: {steps: [{run: npm run test}]}}\n"
        steps, errors, _ = cct.extract_steps(text)
        self.assertTrue(errors)

    def test_strip_substitutions_removes_separators(self):
        out = cct.strip_substitutions("echo $(a; b | c) && ls `x; y`")
        self.assertNotIn(";", out.split("&&")[0])
        self.assertIn("$SUBST", out)

    def test_strip_comment_respects_quotes(self):
        self.assertEqual(cct.strip_comment('echo "a # b" # c'),
                         'echo "a # b"')
        self.assertEqual(cct.strip_comment("npm run test#x"),
                         "npm run test#x")

    def test_env_value_flags_consume_values(self):
        toks = cct.normalise_tokens(["env", "-u", "FOO", "-C", ".",
                                     "npm", "run", "test"])
        self.assertEqual(toks, ["npm", "run", "test"])

    def test_cd_root_and_sub_makefiles_differ(self):
        # Regression guard: the cd fixture pair must NOT be identical,
        # or the cd test proves nothing.
        import filecmp
        root = os.path.join(FIXTURES, "clean-cd-advanced", "Makefile")
        sub = os.path.join(FIXTURES, "clean-cd-advanced", "sub", "Makefile")
        self.assertFalse(filecmp.cmp(root, sub, shallow=False))
        root2 = os.path.join(FIXTURES, "clean-chains-env", "Makefile")
        sub2 = os.path.join(FIXTURES, "clean-chains-env", "sub", "Makefile")
        self.assertFalse(filecmp.cmp(root2, sub2, shallow=False))


class ParserUnitTests(unittest.TestCase):
    def test_block_scalar_line_numbers(self):
        text = ("jobs:\n  t:\n    steps:\n      - run: |\n"
                "          npm run a\n          npm run b\n")
        steps, errors, _ = cct.extract_steps(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(steps), 1)
        entry = steps[0].runs[0]
        self.assertEqual(entry.line, 4)
        self.assertEqual([ln for ln, _ in entry.lines], [5, 6])

    def test_inline_dash_run_and_working_directory(self):
        text = ("jobs:\n  t:\n    steps:\n"
                "      - working-directory: app\n        run: make test\n")
        steps, errors, _ = cct.extract_steps(text)
        self.assertEqual(errors, [])
        self.assertEqual(steps[0].wd, "app")
        self.assertEqual(steps[0].runs[0].lines[0][1], "make test")

    def test_split_segments_respects_quotes(self):
        parts = cct.split_segments('echo "a && b" && npm run test | tee log')
        self.assertEqual(len(parts), 3)
        self.assertIn("npm run test", parts[1])

    def test_normalise_strips_env_and_sudo(self):
        toks = cct.normalise_tokens(["FOO=bar", "sudo", "npm", "run", "test"])
        self.assertEqual(toks, ["npm", "run", "test"])

    def test_make_targets_ignore_assignments_and_recipes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Makefile"), "w") as fh:
                fh.write("FOO := bar\ntest: deps\n\techo ok\n.PHONY: test\n")
            targets, _, first = cct.RepoModel(d).make_targets(d)
            self.assertIn("test", targets)
            self.assertNotIn("FOO", targets)
            self.assertEqual(first, "test")

    def test_annotations_format(self):
        _, r = run_tool("missing-npm-script")
        lines = cct.render_annotations(r)
        self.assertTrue(any(l.startswith("::error file=.github/workflows/ci.yml,line=")
                            for l in lines), lines)

    def test_tool_never_executes_scanned_code(self):
        # A fixture script contains a command that would create a file if
        # executed; scanning must not create it. (Guard by construction:
        # the tool has no subprocess/eval/exec usage at all.)
        src = open(TOOL).read()
        for bad in ("subprocess", "os.system", "eval(", "exec(",
                    "os.popen", "check_output"):
            self.assertNotIn(bad, src, f"tool must stay static: found {bad}")


def run_tool_mode(fixture, *flags):
    proc = subprocess.run(
        [sys.executable, TOOL, os.path.join(FIXTURES, fixture), *flags],
        capture_output=True, text=True)
    return proc


def build_sandbox(files):
    import tempfile
    d = tempfile.mkdtemp(prefix="cct-v02-")
    for rel, content in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(content)
    return d


WF_HDR = "name: t\non: push\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n"


class V02Tests(unittest.TestCase):
    # -- did-you-mean ------------------------------------------------------
    def test_npm_typo_gets_suggestion_everywhere(self):
        _, r = run_tool("missing-python-submodule")
        f = r["findings"][0]
        self.assertEqual(f["suggestion"], "pkg.mod")
        self.assertIn("did you mean 'pkg.mod'?", f["message"])
        self.assertIn("did you mean 'pkg.mod'?",
                      cct.render_text(r))
        ann = cct.render_annotations(r)
        self.assertTrue(any("did you mean 'pkg.mod'?" in a for a in ann))

    def test_npm_script_typo_suggestion(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: npm run test:unit\n",
            "package.json": '{"scripts": {"test:units": "x", "build": "y"}}',
        })
        r = cct.scan(d)
        self.assertEqual(r["exit"], 1)
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["findings"][0]["suggestion"], "test:units")

    def test_no_suggestion_for_unrelated_name(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: npm run zzzqqqwww\n",
            "package.json": '{"scripts": {"test": "x", "build": "y"}}',
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 1)
        self.assertIsNone(r["findings"][0]["suggestion"])
        self.assertNotIn("did you mean", r["findings"][0]["message"])
        # The pre-existing planted fixtures use unrelated names and
        # must stay suggestion-free too.
        _, r2 = run_tool("missing-npm-script")
        self.assertIsNone(r2["findings"][0]["suggestion"])

    def test_make_and_just_suggestions(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: make tets\n      - run: just biuld\n",
            "Makefile": "test:\n\techo ok\n\nbuild:\n\techo ok\n",
            "justfile": "test:\n  echo ok\n\nbuild:\n  echo ok\n",
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 2)
        by_kind = {f["kind"]: f["suggestion"] for f in r["findings"]}
        self.assertEqual(by_kind["missing-make-target"], "test")
        self.assertEqual(by_kind["missing-just-recipe"], "build")

    def test_suggestion_is_deterministic(self):
        a = cct._suggest("testt", ["tests", "test", "build"])
        b = cct._suggest("testt", ["build", "test", "tests"])
        self.assertEqual(a, b)
        self.assertIsNotNone(a)

    def test_suggestion_never_changes_verdict_or_exit(self):
        # special-downgrade findings stay warnings / exit 0 even when a
        # suggestion is attached (there is none here by construction:
        # 'nope' is unrelated to 'test').
        code, r = run_tool("special-downgrade")
        self.assertEqual(code, 0)
        self.assertTrue(all(f["severity"] == "warning"
                            for f in r["findings"]))

    # -- python -m submodules ----------------------------------------------
    def test_dynamic_module_is_skipped_not_flagged(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.lazything\n",
            "pkg/__init__.py":
                "def __getattr__(name):\n    return object()\n",
        })
        r = cct.scan(d)
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["exit"], 0)
        self.assertGreaterEqual(r["skipped"].get("dynamic-module", 0), 1)

    def test_submodule_of_plain_module_file_is_missing(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.sub\n",
            "pkg.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(r["exit"], 1)
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["findings"][0]["kind"], "missing-python-module")

    def test_nonlocal_module_behaviour_unchanged(self):
        # stdlib / known-tool / install-step cases keep v1 behaviour:
        # no submodule check, no new findings.
        code, r = run_tool("clean-python-known")
        self.assertEqual((code, r["findings"]), (0, []))
        code, r = run_tool("clean-install-python-m")
        self.assertEqual((code, r["findings"]), (0, []))

    def test_split_namespace_across_root_and_src_is_clean(self):
        # FP-hunter HIGH (v0.2 review): PEP 420 merges namespace
        # portions across base and base/src; a single-root walk falsely
        # flagged pkg.b and even suggested the wrong module.
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.a\n"
            "      - run: python -m pkg.b\n",
            "pkg/a.py": "x = 1\n",
            "src/pkg/b.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["exit"], 0)

    def test_split_namespace_subpackage_is_clean(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.sub.a\n"
            "      - run: python -m pkg.sub.b\n",
            "pkg/sub/a.py": "x = 1\n",
            "src/pkg/sub/b.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(r["findings"], [])

    def test_data_only_root_portion_does_not_shadow_src_package(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.sub\n",
            "pkg/data.txt": "data\n",
            "src/pkg/__init__.py": "",
            "src/pkg/sub.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(r["findings"], [])

    def test_missing_in_split_namespace_still_found_once(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.zzzqqq\n",
            "pkg/a.py": "x = 1\n",
            "src/pkg/b.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["findings"][0]["kind"], "missing-python-module")
        self.assertIsNone(r["findings"][0]["suggestion"])

    def test_unresolvable_module_name_is_skipped(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.some-thing\n",
            "pkg/__init__.py": "",
        })
        r = cct.scan(d)
        self.assertEqual(r["findings"], [])
        self.assertGreaterEqual(
            r["skipped"].get("unresolvable-module-name", 0), 1)

    # -- SARIF ---------------------------------------------------------------
    def _sarif(self, fixture):
        proc = run_tool_mode(fixture, "--sarif")
        return proc, json.loads(proc.stdout)

    def test_sarif_structure_and_rule_crossrefs(self):
        proc, doc = self._sarif("missing-npm-script")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("$schema", doc)
        self.assertEqual(doc["version"], "2.1.0")
        run = doc["runs"][0]
        driver = run["tool"]["driver"]
        self.assertEqual(driver["name"], "CI Command Truth")
        self.assertEqual(driver["version"], cct.VERSION)
        rule_ids = {rule["id"] for rule in driver["rules"]}
        self.assertTrue(run["results"])
        for res in run["results"]:
            self.assertIn(res["ruleId"], rule_ids)
            self.assertEqual(res["level"], "error")
            loc = res["locations"][0]["physicalLocation"]
            uri = loc["artifactLocation"]["uri"]
            self.assertFalse(os.path.isabs(uri), uri)
            self.assertNotIn("\\", uri)
            self.assertGreaterEqual(loc["region"]["startLine"], 1)

    def test_sarif_warning_level_for_downgraded_findings(self):
        proc, doc = self._sarif("special-downgrade")
        self.assertEqual(proc.returncode, 0)
        results = doc["runs"][0]["results"]
        self.assertEqual(len(results), 2)
        self.assertTrue(all(x["level"] == "warning" for x in results))

    def test_sarif_zero_findings_is_valid(self):
        proc, doc = self._sarif("clean-npm")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(doc["runs"][0]["results"], [])

    def test_sarif_unscanned_are_notifications_not_results(self):
        proc, doc = self._sarif("edge-empty")
        self.assertEqual(proc.returncode, 2)
        run = doc["runs"][0]
        self.assertEqual(run["results"], [])
        notifs = run["invocations"][0]["toolExecutionNotifications"]
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["associatedRule"]["id"],
                         "unscanned-workflow")
        rule_ids = {x["id"] for x in run["tool"]["driver"]["rules"]}
        self.assertIn("unscanned-workflow", rule_ids)
        self.assertEqual(run["properties"]["unscannedCount"], 1)

    def test_sarif_carries_suggestion(self):
        _, doc = self._sarif("missing-python-submodule")
        res = doc["runs"][0]["results"][0]
        self.assertEqual(res["properties"]["suggestion"], "pkg.mod")
        self.assertIn("did you mean 'pkg.mod'?", res["message"]["text"])

    def test_sarif_escapes_space_in_path_and_control_in_text(self):
        d = build_sandbox({
            ".github/workflows/my ci.yml": WF_HDR +
            "      - run: npm run nope\x07script\n",
            "package.json": '{"scripts": {"test": "x"}}',
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 1)
        doc = cct.render_sarif(r)
        blob = json.dumps(doc)          # must round-trip as JSON
        parsed = json.loads(blob)
        uri = (parsed["runs"][0]["results"][0]["locations"][0]
               ["physicalLocation"]["artifactLocation"]["uri"])
        self.assertNotIn(" ", uri)
        self.assertIn("%20", uri)
        self.assertFalse(os.path.isabs(uri))

    def test_sarif_and_json_are_mutually_exclusive(self):
        proc = run_tool_mode("clean-npm", "--json", "--sarif")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn('"runs"', proc.stdout)

    # -- adversarial-review fix pass (auditor / FP hunter) -------------------
    def test_outside_root_makefile_and_justfile_are_skipped(self):
        # Auditor H1: -f must never read outside the repo root.
        import tempfile
        outside = tempfile.mkdtemp(prefix="cct-outside-")
        mk = os.path.join(outside, "secret.mk")
        with open(mk, "w") as fh:
            fh.write("exfiltarget:\n\techo x\n")
        jf = os.path.join(outside, "secret.just")
        with open(jf, "w") as fh:
            fh.write("exfilrecipe:\n  echo x\n")
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            f"      - run: make -f {mk} exfiltarget\n"
            f"      - run: just -f {jf} exfilrecipe\n",
        })
        r = cct.scan(d)
        self.assertEqual(r["findings"], [])
        self.assertGreaterEqual(r["skipped"].get("outside-repo-root", 0), 2)
        self.assertNotIn("secret", json.dumps(r))

    def test_stdlib_named_local_package_is_submodule_checked(self):
        # Auditor M1: a local regular package shadowing a stdlib name
        # gets the v0.2 submodule check.
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m json.tool\n"
            "      - run: python -m json.nosuchsub\n",
            "json/__init__.py": "",
            "json/tool.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 1)
        self.assertIn("nosuchsub", r["findings"][0]["expected"])

    def test_stdlib_namespace_portion_does_not_shadow(self):
        # A namespace-only local dir named like a stdlib package must
        # NOT be submodule-checked (stdlib regular package wins).
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m json.tool\n",
            "json/data.txt": "data\n",
        })
        r = cct.scan(d)
        self.assertEqual(r["findings"], [])
        self.assertGreaterEqual(r["skipped"].get("external-tool", 0), 1)

    def test_annotations_escape_property_values(self):
        d = build_sandbox({
            ".github/workflows/we,ird: na%me.yml": WF_HDR +
            "      - run: npm run nope\n",
            "package.json": '{"scripts": {"test": "x"}}',
        })
        r = cct.scan(d)
        lines = cct.render_annotations(r)
        self.assertEqual(len(lines), 1)
        prop = lines[0].split("::", 2)[2].split("::")[0]
        self.assertNotIn(",", prop.replace("%2C", ""))
        self.assertNotIn(" na%me", lines[0])
        self.assertIn("%2C", lines[0])
        self.assertIn("%3A", lines[0])

    def test_package_dir_wins_over_same_named_module_file(self):
        # Auditor L7: CPython gives the package precedence.
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.sub.leaf\n",
            "pkg/__init__.py": "",
            "pkg/sub.py": "x = 1\n",
            "pkg/sub/__init__.py": "",
            "pkg/sub/leaf.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(r["findings"], [])

    def test_machine_modes_reject_annotations_flag(self):
        for flags in (("--json", "--github-annotations"),
                      ("--sarif", "--github-annotations")):
            proc = run_tool_mode("clean-npm", *flags)
            self.assertEqual(proc.returncode, 2, flags)

    # -- adversarial-review fix pass (red team) -------------------------------
    def test_sarif_survives_non_utf8_workflow_filename(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="cct-nutf8-")
        wf = os.path.join(d, ".github", "workflows")
        os.makedirs(wf)
        fd = os.open(os.path.join(os.fsencode(wf), b"bad-\xff.yml"),
                     os.O_CREAT | os.O_WRONLY)
        os.write(fd, (WF_HDR + "      - run: npm run nope\n").encode())
        os.close(fd)
        with open(os.path.join(d, "package.json"), "w") as fh:
            fh.write('{"scripts": {"test": "x"}}')
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 1)
        doc = cct.render_sarif(r)               # must not raise
        blob = json.dumps(doc)
        uri = (json.loads(blob)["runs"][0]["results"][0]["locations"][0]
               ["physicalLocation"]["artifactLocation"]["uri"])
        self.assertIn("%FF", uri)
        self.assertFalse(os.path.isabs(uri))

    def test_python_m_cd_outside_root_is_skipped(self):
        import tempfile
        parent = tempfile.mkdtemp(prefix="cct-parent-")
        repo = os.path.join(parent, "repo")
        outside = os.path.join(parent, "outside")
        os.makedirs(os.path.join(repo, ".github", "workflows"))
        os.makedirs(os.path.join(outside, "secretpkg"))
        with open(os.path.join(outside, "secretpkg", "__init__.py"),
                  "w") as fh:
            fh.write("")
        with open(os.path.join(outside, "secretpkg", "real.py"),
                  "w") as fh:
            fh.write("x = 1\n")
        with open(os.path.join(repo, ".github", "workflows", "ci.yml"),
                  "w") as fh:
            fh.write(WF_HDR +
                     "      - run: cd ../outside && python -m "
                     "secretpkg.real\n"
                     "      - run: cd ../outside && python -m "
                     "secretpkg.missing\n")
        r = cct.scan(repo)
        self.assertEqual(r["findings"], [])
        self.assertGreaterEqual(
            r["skipped"].get("outside-repo-root", 0), 2)

    def test_package_without_main_is_flagged_dir_with_main_is_clean(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg\n"
            "      - run: python -m runnable\n"
            "      - run: python -m pkg.data\n",
            "pkg/__init__.py": "",
            "pkg/data/notes.txt": "x\n",
            "runnable/__init__.py": "",
            "runnable/__main__.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 2)
        self.assertTrue(all("__main__" in f["expected"]
                            for f in r["findings"]))

    def test_comment_mentioning_getattr_does_not_disable_checking(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m pkg.missing_xyz\n",
            "pkg/__init__.py": "# TODO: add __getattr__ later\nx = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["skipped"].get("dynamic-module", 0), 0)

    def test_bogus_compiled_modules_do_not_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "pkg")
            os.makedirs(pkg)
            with open(os.path.join(pkg, "miss.notreal.so"), "w") as fh:
                fh.write("")
            os.makedirs(os.path.join(pkg, "other.abi3.so"))
            self.assertIsNone(cct.Checker._dir_child(pkg, "miss"))
            self.assertIsNone(cct.Checker._dir_child(pkg, "other"))

    def test_wholly_missing_nonidentifier_top_is_flagged(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m totallymissing-thing\n",
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["findings"][0]["kind"], "missing-python-module")

    def test_long_prefix_does_not_inflate_submodule_suggestion(self):
        d = build_sandbox({
            ".github/workflows/ci.yml": WF_HDR +
            "      - run: python -m myapplication.zzzz\n",
            "myapplication/__init__.py": "",
            "myapplication/apple.py": "x = 1\n",
        })
        r = cct.scan(d)
        self.assertEqual(len(r["findings"]), 1)
        self.assertIsNone(r["findings"][0]["suggestion"])

    def test_suggest_tie_breaks_alphabetically(self):
        self.assertEqual(cct._suggest("builx", ["built", "build"]), "build")

    def test_sarif_rule_table_is_stable_on_clean_runs(self):
        # Auditor L3: full taxonomy every run, not per-run kinds.
        _, doc = self._sarif("clean-npm")
        ids = {x["id"] for x in doc["runs"][0]["tool"]["driver"]["rules"]}
        self.assertIn("missing-python-module", ids)
        self.assertIn("unscanned-workflow", ids)
        _, doc2 = self._sarif("missing-npm-script")
        ids2 = {x["id"] for x in doc2["runs"][0]["tool"]["driver"]["rules"]}
        self.assertEqual(ids, ids2)

    def test_exit_codes_preserved_in_sarif_mode(self):
        self.assertEqual(run_tool_mode("clean-npm", "--sarif").returncode, 0)
        self.assertEqual(
            run_tool_mode("missing-npm-script", "--sarif").returncode, 1)
        self.assertEqual(run_tool_mode("edge-empty", "--sarif").returncode, 2)


class ActionManifestTests(unittest.TestCase):
    """The published action.yml must stay loadable by GitHub.

    Regression (v0.2.1): the v0.2 manifest shipped an unquoted colon
    inside the plain-scalar description ("Prove every run: command
    ..."), which is invalid YAML. GitHub failed every consumer run
    at "Set up job" with "Mapping values are not allowed in this
    context", and the suite never noticed because nothing parsed the
    manifest. Parse it here, strictly: PyYAML when the test
    environment has it, plus a stdlib scan for the same defect class
    so the suite stays zero-dependency everywhere else.
    """

    def test_action_yml_parses_as_strict_yaml(self):
        with open(os.path.join(HERE, "action.yml"), encoding="utf-8") as fh:
            text = fh.read()
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None:
            doc = yaml.safe_load(text)  # raises on the v0.2 defect
            self.assertIsInstance(doc, dict)
            self.assertEqual(doc["name"], "CI Command Truth")
            self.assertIsInstance(doc["description"], str)
            self.assertEqual(doc["runs"]["using"], "composite")
        in_block = False
        block_indent = 0
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            if in_block:
                if stripped and indent <= block_indent:
                    in_block = False
                else:
                    continue  # literal block-scalar text, not a scalar
            if not stripped or stripped.startswith("#"):
                continue
            _key, sep, value = stripped.partition(":")
            if not sep:
                continue
            value = value.strip()
            if value in ("|", ">", "|-", ">-", "|+", ">+"):
                in_block, block_indent = True, indent
                continue
            if not value or value[0] in "\"'[{&*!>@`":
                continue  # quoted / flow / anchor — not a plain scalar
            self.assertNotIn(
                ": ", value,
                f"action.yml:{lineno}: unquoted ':' inside a plain "
                "scalar — quote the value or drop the colon")
            self.assertFalse(
                value.endswith(":"),
                f"action.yml:{lineno}: plain scalar ends in ':'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
