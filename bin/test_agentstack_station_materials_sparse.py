#!/usr/bin/env python3
"""OPS-SPARSE-1: isolated tool regression tests and exact destination proof."""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER = Path(os.environ.get("STATION_MATERIALS_HELPER", str(Path(__file__).with_name("agentstack-station-materials"))))
loader = importlib.machinery.SourceFileLoader("station_materials_sparse", str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
materials = importlib.util.module_from_spec(spec)
loader.exec_module(materials)


class SparseInputsTests(unittest.TestCase):
    def test_swift_comments_are_not_literals(self):
        source = '// "docs/receipts/not.json"\n/* nested /* "bad" */ */ let p = "docs/receipts/yes.json"'
        self.assertEqual(materials.test_string_literals(source, ".swift"),
                         {"docs/receipts/yes.json"})

    def test_raw_and_multiline_swift_strings(self):
        source = 'let p = #"docs/receipts/\\#(id).json"#\nlet v = """known"""'
        self.assertEqual(materials.test_string_literals(source, ".swift"),
                         {r"docs/receipts/\#(id).json", "known"})

    def test_python_constants_and_f_strings(self):
        source = '# "ignored"\ncase="known"\np=f"docs/receipts/{case}.json"'
        values = materials.test_string_literals(source, ".py")
        self.assertEqual(materials.named_record_paths(
            {"docs/receipts/known.json", "docs/receipts/unmentioned.json"}, values),
            {"docs/receipts/known.json"})

    def test_exact_and_finite_interpolated_paths(self):
        paths = {"docs/receipts/a.json", "docs/receipts/b.json", "docs/receipts/unused.json"}
        literals = {"docs/receipts/a.json", r"docs/receipts/\(id).json", "b"}
        self.assertEqual(materials.named_record_paths(paths, literals),
                         {"docs/receipts/a.json", "docs/receipts/b.json"})

    def test_directory_alone_does_not_include_records(self):
        self.assertEqual(materials.named_record_paths({"docs/receipts/unused.json"},
                                                      {"docs/receipts"}), set())

    def test_directory_leaf_and_constant_id(self):
        paths = {"docs/receipts/set/a.json", "docs/receipts/set/unused.json"}
        self.assertEqual(materials.named_record_paths(
            paths, {"docs/receipts/set", r"\(id).json", "a"}), {"docs/receipts/set/a.json"})

    def fixture(self):
        temp = tempfile.TemporaryDirectory(dir=os.environ.get("OPS_SPARSE_TEST_ROOT"))
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        for name, text in {
            "apps/ios/Tests/Inputs.swift": 'let p = "docs/receipts/needed[1].json"',
            "docs/receipts/needed[1].json": "{}",
            "docs/receipts/needed1.json": "{}",
            "docs/receipts/unmentioned.json": "{}",
            "docs/evidence/unmentioned.json": "{}",
            "source.swift": "// source\n",
        }.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git(repo, "add", ".")
        self.git(repo, "-c", "user.name=fixture", "-c", "user.email=fixture@local",
                 "commit", "-qm", "fixture")
        return root, repo, self.git(repo, "rev-parse", "HEAD")

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args],
                                       text=True, stderr=subprocess.PIPE).strip()

    def test_real_git_materializes_exact_escaped_file_only(self):
        root, repo, revision = self.fixture()
        destination = root / "lane"
        result = materials.source_worktree(repo, destination, "fixture-lane", revision)
        self.assertEqual([x["path"] for x in result["required_test_inputs"]],
                         ["docs/receipts/needed[1].json"])
        self.assertTrue((destination / "docs/receipts/needed[1].json").is_file())
        self.assertFalse((destination / "docs/receipts/needed1.json").exists())
        self.assertFalse((destination / "docs/receipts/unmentioned.json").exists())
        self.assertFalse((destination / "docs/evidence").exists())
        self.assertEqual(self.git(destination, "status", "--porcelain"), "")

    def test_requested_commit_ignores_dirty_source_literals(self):
        root, repo, revision = self.fixture()
        (repo / "apps/ios/Tests/Inputs.swift").write_text('let p = "docs/receipts/unmentioned.json"')
        result = materials.source_worktree(repo, root / "lane", "fixed-revision", revision)
        self.assertEqual([x["path"] for x in result["required_test_inputs"]],
                         ["docs/receipts/needed[1].json"])
        self.assertTrue(self.git(repo, "status", "--porcelain"))

    def test_unnamed_untracked_file_is_never_copied(self):
        root, repo, revision = self.fixture()
        (repo / "docs/receipts/not-tracked.json").write_text("{}")
        materials.source_worktree(repo, root / "lane", "untracked-refused", revision)
        self.assertFalse((root / "lane/docs/receipts/not-tracked.json").exists())

    def test_named_symlink_refused_before_worktree_creation(self):
        root, repo, revision = self.fixture()
        target = repo / "docs/receipts/needed[1].json"
        target.unlink()
        target.symlink_to("/dev/null")
        self.git(repo, "add", ".")
        self.git(repo, "-c", "user.name=fixture", "-c", "user.email=fixture@local",
                 "commit", "-qm", "symlink")
        with self.assertRaisesRegex(ValueError, "regular tracked file"):
            materials.source_worktree(repo, root / "lane", "unsafe-input", "HEAD")
        self.assertFalse((root / "lane").exists())

    def test_runtime_question_id_keeps_named_folder_and_excludes_others(self):
        root, repo, revision = self.fixture()
        for name in ("from-data.json", "another-data.json"):
            path = repo / "docs/receipts/input-set" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("{}")
        (repo / "apps/ios/Tests/Inputs.swift").write_text(
            'let p = "docs/receipts/input-set/\\(question.id).json"')
        self.git(repo, "add", ".")
        self.git(repo, "-c", "user.name=fixture", "-c", "user.email=fixture@local",
                 "commit", "-qm", "data-driven input")
        result = materials.source_worktree(repo, root / "lane", "runtime-data", "HEAD")
        self.assertEqual({x["path"] for x in result["required_test_inputs"]},
                         {"docs/receipts/input-set/from-data.json",
                          "docs/receipts/input-set/another-data.json"})
        self.assertEqual(result["included_test_folders"][0]["file_count"], 2)
        self.assertFalse((root / "lane/docs/receipts/unmentioned.json").exists())
        # A Python attribute-driven f-string must retain its literal prefix too.
        values = materials.test_string_literals('p=f"docs/receipts/input-set/{question.id}.json"', ".py")
        self.assertEqual(materials.named_record_folders(
            {"docs/receipts/input-set/from-data.json"}, values), {"docs/receipts/input-set"})
        self.assertEqual(materials.named_record_folders(
            {"docs/receipts/input-set/from-data.json"}, {r"docs/receipts/\(question.id).json"}), set())


class PublishedCloseTests(unittest.TestCase):
    def git(self, cwd, *args):
        return subprocess.check_output(["git", "-C", str(cwd), *args], stderr=subprocess.PIPE).decode().strip()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q")
        self.git(self.repo, "config", "user.name", "fixture")
        self.git(self.repo, "config", "user.email", "fixture@local")
        (self.repo / "file.txt").write_text("one")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "base")
        self.base = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.root, "init", "--bare", "-q", "remote.git")
        self.git(self.repo, "remote", "add", "origin", str(self.root / "remote.git"))
        self.dest = self.root / "lane"
        self.receipt = self.root / "receipt.json"
        # Simulate a mounted private volume entirely within the test scratch root.
        private_root = self.root / "private-volume"
        private_root.mkdir()
        self.private_receipt = private_root / "receipt.json"
        self.helper = self.root / "station-materials-fixture"
        source = HELPER.read_text()
        root_marker = "PRIVATE_ROOT = None  # __FLEET_PRIVATE_ROOT_ASSIGNMENT__"
        mount_marker = "if not os.path.ismount(PRIVATE_ROOT):"
        assert source.count(root_marker) == source.count(mount_marker) == 1
        source = source.replace(root_marker, f"PRIVATE_ROOT = Path({str(private_root)!r})")
        source = source.replace(mount_marker, "if not PRIVATE_ROOT.is_dir():")
        self.helper.write_text(source)
        self.helper.chmod(0o755)
        self.args = ["worktree", "--source", str(self.repo), "--destination", str(self.dest),
                     "--branch", "lane", "--revision", self.base, "--receipt", str(self.receipt),
                     "--private-receipt", str(self.private_receipt)]
        self.run_tool(*self.args, ok=True)
        (self.dest / "file.txt").write_text("two")
        self.git(self.dest, "add", "file.txt")
        self.git(self.dest, "commit", "-qm", "advance")
        self.head = self.git(self.dest, "rev-parse", "HEAD")
        self.git(self.dest, "push", "-q", "origin", "lane")

    def run_tool(self, *args, ok):
        env = dict(os.environ)
        if Path("/usr/sbin/lsof").is_file():
            env["PATH"] = env.get("PATH", "") + os.pathsep + "/usr/sbin"
        result = subprocess.run([str(self.helper), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return result

    def close(self, *extra, ok):
        return self.run_tool(*self.args, "--close-published", *extra, ok=ok)

    def test_advanced_pushed_closes_and_retains_branch(self):
        # Old receipts are accepted by published close without exposing their contents.
        self.receipt.write_text(self.private_receipt.read_text())
        self.close("--dry-run", ok=True)
        self.assertTrue(self.dest.exists())
        self.close(ok=True)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.git(self.repo, "rev-parse", "refs/heads/lane"), self.head)
        self.assertIn("already closed", self.close(ok=True).stdout)

    def test_unpushed_refused(self):
        self.git(self.repo, "push", "-q", "origin", ":lane")
        self.assertIn("origin branch", self.close(ok=False).stderr)
        self.assertTrue(self.dest.exists())

    def test_different_remote_commit_refused(self):
        self.git(self.repo, "push", "-q", "--force", "origin", self.base + ":refs/heads/lane")
        self.assertIn("differs", self.close(ok=False).stderr)
        self.assertTrue(self.dest.exists())

    def test_tracked_change_refused(self):
        (self.dest / "file.txt").write_text("dirty")
        self.assertIn("tracked changes", self.close(ok=False).stderr)

    def test_untracked_and_ignored_refused_without_names(self):
        for name in ("secret-name", "ignored.txt"):
            f = self.dest / name
            f.write_text("unique")
            result = self.close(ok=False)
            self.assertIn("count=", result.stderr)
            self.assertNotIn(name, result.stderr + result.stdout)
            f.unlink()

    def test_resume_after_removal(self):
        from unittest.mock import patch
        args = argparse.Namespace(source=self.repo, destination=self.dest, branch="lane", revision=self.base,
                                  receipt=self.receipt, dry_run=False)
        original = materials.WorktreeState.record
        def interrupted(state, stage, status, exit_code=None):
            if stage == "published-close":
                raise KeyboardInterrupt()
            return original(state, stage, status, exit_code)
        with patch.object(materials.WorktreeState, "record", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                materials.close_published(args)
        self.assertFalse(self.dest.exists())
        self.close(ok=True)
        self.assertEqual(json.loads((self.root / "lane.station-materials-state.json").read_text())["status"], "cleaned")

    def test_resume_when_directory_removed_but_registration_remains(self):
        import shutil
        from unittest.mock import patch
        args = argparse.Namespace(source=self.repo, destination=self.dest, branch="lane", revision=self.base,
                                  receipt=self.receipt, dry_run=False)
        original = materials.worktree_git
        def interrupted(cwd, *git_args, **kwargs):
            if git_args[:2] == ("worktree", "remove"):
                shutil.rmtree(self.dest)
                raise KeyboardInterrupt()
            return original(cwd, *git_args, **kwargs)
        with patch.object(materials, "worktree_git", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                materials.close_published(args)
        self.assertFalse(self.dest.exists())
        self.assertIn(str(self.dest), self.git(self.repo, "worktree", "list", "--porcelain"))
        self.close(ok=True)
        self.assertNotIn(str(self.dest), self.git(self.repo, "worktree", "list", "--porcelain"))
        self.assertEqual(self.git(self.repo, "rev-parse", "refs/heads/lane"), self.head)

    def test_open_process_refused(self):
        process = subprocess.Popen(["sleep", "5"], cwd=self.dest)
        try:
            self.assertIn("in use", self.close(ok=False).stderr)
        finally:
            # The fixture exits by itself; do not signal processes from the isolated suite.
            process.wait(timeout=10)

    def test_legacy_cleanup_still_works(self):
        self.git(self.dest, "reset", "--hard", self.base)
        self.run_tool(*self.args, "--cleanup", ok=True)
        self.assertFalse(self.dest.exists())

    def test_symlink_and_wrong_registration_refused(self):
        link = self.root / "link"
        link.symlink_to(self.dest, target_is_directory=True)
        args = list(self.args)
        args[args.index(str(self.dest))] = str(link)
        self.assertIn("symlink", self.run_tool(*args, "--close-published", ok=False).stderr)
        state = self.root / "lane.station-materials-state.json"
        data = json.loads(state.read_text())
        data["request"]["branch"] = "wrong"
        state.write_text(json.dumps(data))
        self.assertIn("mismatch", self.close(ok=False).stderr)



class PrivacyReceiptTests(SparseInputsTests):
    def test_public_private_and_legacy_resume(self):
        from unittest.mock import patch
        import contextlib
        import io
        root, repo, revision = self.fixture()
        private = root / "private"
        private.mkdir()
        receipt = root / "public.json"
        secret = private / "private.json"
        args = ["worktree", "--source", str(repo), "--destination", str(root / "lane"),
                "--branch", "privacy-lane", "--revision", revision, "--receipt", str(receipt),
                "--private-receipt", str(secret)]
        with patch.object(materials, "PRIVATE_ROOT", private), patch.object(materials.os.path, "ismount", return_value=True):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(materials.main(args), 0)
            full = json.loads(secret.read_text())
            public = receipt.read_text()
            for row in full["required_test_inputs"]:
                self.assertNotIn(row["path"], public)
                self.assertNotIn(row["path"], out.getvalue())
            for row in full["included_test_folders"]:
                self.assertNotIn(row["path"], public)
            self.assertEqual(len(full["required_test_inputs"]), 1)
            self.assertEqual(json.loads(public), materials.public_worktree_receipt(full))
            receipt.write_text(json.dumps(full))
            with contextlib.redirect_stdout(out):
                self.assertEqual(materials.main(args + ["--resume"]), 0)
                self.assertEqual(materials.main(args + ["--cleanup"]), 0)
            self.assertNotIn(full["required_test_inputs"][0]["path"], out.getvalue())

    def test_missing_private_volume_fails_before_creation(self):
        from unittest.mock import patch
        root, repo, revision = self.fixture()
        args = ["worktree", "--source", str(repo), "--destination", str(root / "lane"),
                "--branch", "privacy-lane", "--revision", revision, "--receipt", str(root / "public.json")]
        with patch.object(materials.os.path, "ismount", return_value=False):
            self.assertEqual(materials.main(args), 1)
        self.assertFalse((root / "lane").exists())
        self.assertFalse((root / "public.json").exists())


def verify_destination(args):
    receipt = args.record.parent / "generated-worktree.json"
    subprocess.run([str(HELPER), "worktree", "--source", str(args.source),
                    "--destination", str(args.destination), "--branch", args.branch,
                    "--revision", args.revision, "--receipt", str(receipt)], check=True)
    result = json.loads(receipt.read_text())
    observed_bytes = args.expected.read_bytes()
    observed = json.loads(observed_bytes)
    matches = []
    for row in observed["files"]:
        path = row["relative_path"]
        blob = subprocess.check_output(["git", "-C", str(args.source), "show",
                                        args.revision + ":" + path])
        data = (args.destination / path).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        assert data == blob and len(blob) == row["git_blob_bytes"]
        assert sha == row["git_blob_sha256"]
        matches.append(dict(path=path, sha256=sha, bytes=len(data), blob_equal=True))
    records, refs = materials.committed_test_inputs(args.source, args.revision)
    present = set()
    for directory in materials.RECORD_DIRECTORIES:
        for folder, dirs, files in os.walk(args.destination / directory):
            present.update(str((Path(folder) / file).relative_to(args.destination)) for file in files)
    assert present == set(refs)
    assert all(not os.path.lexists(args.destination / path) for path in records if path not in refs)
    assert subprocess.check_output(["git", "-C", str(args.destination), "status", "--porcelain"]).strip() == b""
    folder_matches = []
    if args.verify_folder:
        listing = subprocess.check_output(["git", "-C", str(args.source), "ls-tree", "-r", "-z",
                                           args.revision, "--", args.verify_folder])
        for row in listing.split(b"\0"):
            if not row:
                continue
            header, name = row.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            assert kind == "blob" and mode in ("100644", "100755")
            path = os.fsdecode(name)
            blob = subprocess.check_output(["git", "-C", str(args.source), "cat-file", "blob", oid])
            data = (args.destination / path).read_bytes()
            assert data == blob
            folder_matches.append(dict(path=path, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        assert folder_matches
    report = dict(commit=result["commit"], destination=str(args.destination),
                  expected_observation_sha256=hashlib.sha256(observed_bytes).hexdigest(),
                  required_count=len(matches), verified_count=len(matches),
                  all_selected_count=len(refs), materialized_record_count=len(present),
                  excluded_tracked_count=len(records) - len(refs), extra_record_files=0,
                  excluded_by_directory={directory: sum(path.startswith(directory + "/") and path not in refs
                                                       for path in records)
                                         for directory in materials.RECORD_DIRECTORIES},
                  clean=True, heavy=0, dependency_copy_bytes=result["dependency_copy_bytes"])
    if args.verify_folder:
        report.update(folder_verified_count=len(folder_matches),
                      included_test_folders_count=result["included_test_folders_count"],
                      previous_excluded_count=623, excluded_count_reduction=623 - report["excluded_tracked_count"])
    args.record.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(required_verified=len(matches), selected_records=len(refs),
                          excluded_records=len(records) - len(refs), extra_records=0)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-destination", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--branch")
    parser.add_argument("--revision")
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--verify-folder")
    args, remainder = parser.parse_known_args()
    if args.verify_destination:
        verify_destination(args)
    else:
        unittest.main(argv=[__file__, *remainder], verbosity=2)
