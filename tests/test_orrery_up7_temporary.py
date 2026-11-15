"""Existing unrelated temporary files are never reused by the MCP merger."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('up7_merge',ROOT/'scripts/lib/merge_claude_mcp.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ResultWriterTest(unittest.TestCase):
    def test_existing_pid_derived_temp_survives(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);target=root/'result.json'; old=root/('result.json.tmp.'+str(os.getpid()))
            old.write_bytes(b'keep synthetic bytes')
            module.write_result(target,{'status':'synthetic'})
            self.assertEqual(old.read_bytes(),b'keep synthetic bytes')
            self.assertEqual(json.loads(target.read_text()),{'status':'synthetic'})
            self.assertEqual(target.stat().st_mode & 0o777,0o600)

if __name__=='__main__':unittest.main()
