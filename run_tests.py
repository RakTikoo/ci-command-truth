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
         "clean-install-python-m", "clean-block-indicator"]
MISSING = {  # fixture -> expected finding kind
    "missing-npm-script": "missing-npm-script",
    "missing-make-target": "missing-make-target",
    "missing-just-recipe": "missing-just-recipe",
    "missing-script-file": "missing-script-file",
    "missing-python-module": "missing-python-module",
    "missing-requirements": "missing-requirements-file",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
