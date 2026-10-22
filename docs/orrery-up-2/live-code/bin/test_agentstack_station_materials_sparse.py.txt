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

HELPER = Path(__file__).with_name("agentstack-station-materials")
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
                  required_count=len(matches), verified_count=len(matches), required=matches,
                  all_selected_count=len(refs), materialized_record_count=len(present),
                  excluded_tracked_count=len(records) - len(refs), extra_record_files=0,
                  excluded_by_directory={directory: sum(path.startswith(directory + "/") and path not in refs
                                                       for path in records)
                                         for directory in materials.RECORD_DIRECTORIES},
                  actual_sparse_patterns=subprocess.check_output(
                      ["git", "-C", str(args.destination), "sparse-checkout", "list"], text=True).splitlines(),
                  clean=True, heavy=0, dependency_copy_bytes=result["dependency_copy_bytes"])
    if args.verify_folder:
        report.update(folder=args.verify_folder, folder_verified_files=folder_matches,
                      folder_verified_count=len(folder_matches),
                      included_test_folders=result["included_test_folders"],
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
