"""R-087 advisory directory citations; no policy, acceptance or deletion changes."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path

KINDS = {"derived-data", "source-worktree", "bench-output"}
BASES = (Path("/Volumes/DevSSD-Private/DevStorageGovernor/artifacts"),
         Path("/Volumes/DevSSD/DevStorageGovernor/artifacts"),
         Path.home()/".dev-storage-governor")
RECORD_SUFFIXES = {".json", ".jsonl", ".md", ".log", ".txt", ".csv", ".tsv"}
BULK_PARTS = {"scratch", "dd", "deriveddata", "derived-data", "build",
              "intermediates.noindex", "sourcepackages", "modulecache.noindex",
              "index.noindex", "products", "worktree", "source", "bench",
              "bench-output", "output", "outputs", "bulk", "reproduction"}

def canonical_reader():
    source = Path.home()/"tools/dev-storage-governor/src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from dev_storage_governor.retention import references, reference_strings
    return references, reference_strings

def discover_roots():
    roots, errors = [], []
    for base in BASES:
        if not base.is_dir():
            errors.append({"path":str(base), "error":"base unavailable"})
            continue
        for p in sorted(base.glob("*/*/.dev-storage.json")):
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                value = json.loads(p.read_bytes())
                if value.get("kind") not in KINDS:
                    continue
                root = p.parent.absolute()
                roots.append({"path":str(root), "resolved":str(root.resolve()),
                    "kind":value["kind"], "station":value.get("task"),
                    "owner":value.get("owner"), "metadata_path":str(p),
                    "scratch":[str(root/row["path"]) for row in value.get("content_layout",[])
                               if row.get("retention_category")=="scratch"],
                    "record_layout":[str(root/row["path"]) for row in value.get("content_layout",[])
                                     if row.get("retention_category")=="record"]})
            except (OSError, ValueError) as e:
                errors.append({"path":str(p),"error":type(e).__name__+": "+str(e)})
    return roots, errors

def lookup(roots):
    out = {}
    for root in roots:
        out[root["path"]] = root
        out[root["resolved"]] = root
    return out

def find_root(path, by_path):
    # Prefer lexical identity. Resolve foreign aliases read-only when needed.
    p = Path(path).absolute()
    for ancestor in (p,*p.parents):
        if str(ancestor) in by_path:
            return by_path[str(ancestor)],p
    try:
        p = p.resolve()
    except (OSError,RuntimeError):
        return None,None
    for ancestor in (p,*p.parents):
        if str(ancestor) in by_path:
            return by_path[str(ancestor)],p
    return None,None

def directory_hit(path, by_path):
    root, p = find_root(path,by_path)
    if root is None:
        return None
    try:
        st = p.stat()
        if not stat.S_ISDIR(st.st_mode):
            return None
        base = Path(root["path"])
        if not p.is_relative_to(base):
            base = Path(root["resolved"])
        rel = p.relative_to(base).parts
        # Explicit record directories/bundles are intentional evidence.
        if any(x.lower() in {"receipts","records"} for x in rel):
            return None
        if any(Path(x).suffix.lower() in {".xcresult",".xcarchive"} for x in rel):
            return None
        registered = any(p==Path(x) or p.is_relative_to(Path(x))
                         for x in root["scratch"])
        bulk = not rel or registered or any(x.lower() in BULK_PARTS for x in rel)
        if not bulk:
            return None
        return {"target":str(p),"quoted_path":str(path),"root":root["path"],
                "kind":root["kind"],"station":root["station"],
                "citation_type":"root" if not rel else "bulk-directory"}
    except (OSError,ValueError):
        return None

def record_candidates(root, limit=5):
    found = {}
    folders = [Path(root["path"])/"receipts",Path(root["path"])/"records",
               *(Path(x) for x in root.get("record_layout",[]))]
    for folder in folders:
        if not folder.is_dir() or folder.is_symlink():
            continue
        for current, dirs, files in os.walk(folder,followlinks=False):
            here = Path(current)
            depth = len(here.relative_to(folder).parts)
            dirs[:] = sorted(d for d in dirs if not (here/d).is_symlink()) if depth<2 else []
            for name in sorted(files):
                p = here/name
                if p.suffix.lower() not in RECORD_SUFFIXES or p.is_symlink():
                    continue
                try:
                    st = p.stat()
                    if not stat.S_ISREG(st.st_mode):
                        continue
                except OSError:
                    continue
                score = (0 if re.search(r"receipt|summary|result|census|identity|manifest|run",name,re.I) else 1,
                         -st.st_mtime_ns,str(p))
                found[str(p)] = (score,{"path":str(p),"bytes":st.st_size})
    return [x[1] for x in sorted(found.values(),key=lambda x:x[0])[:limit]]

def warnings_for_text(text, roots=None):
    if roots is None:
        roots, errors = discover_roots()
    else:
        errors = []
    _, reader = canonical_reader()
    by_path = lookup(roots)
    hits = {}
    for p in sorted(reader(text.splitlines()),key=str):
        hit = directory_hit(p,by_path)
        if hit is not None:
            hits.setdefault(hit["target"],hit)
    roots_by_path = {r["path"]:r for r in roots}
    for hit in hits.values():
        hit["record_file_candidates"] = record_candidates(roots_by_path[hit["root"]])
    return {"advisory_only":True,"warnings":list(hits.values()),"discovery_errors":errors}

def emit_report(report, stream=sys.stderr):
    for row in report["warnings"]:
        print("RECEIPT-CITE-1 警告: "+row["kind"]+" のディレクトリ全体が引用されています: "+row["target"],file=stream)
        print("  受理は続行します。既存の引用と保護判定は変更しません。記録fileを個別に引用することを勧めます。",file=stream)
        if row["record_file_candidates"]:
            for p in row["record_file_candidates"]:
                print("  記録file候補: "+p["path"],file=stream)
        else:
            print("  確認できた記録file候補はありません。結果のjson・md・log等を記録し、そのfileを引用してください。",file=stream)
    if report["discovery_errors"]:
        print("RECEIPT-CITE-1 警告検査: 読めない登録情報があります（既存の受理は続行）。",file=stream)

def advise(text, stream=sys.stderr):
    try:
        report = warnings_for_text(text)
        emit_report(report,stream)
        return report
    except Exception as e:
        print("RECEIPT-CITE-1 警告検査を完了できません（受理は続行）: "+type(e).__name__,file=stream)
        return {"advisory_only":True,"warnings":[],"scan_error":type(e).__name__}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt-file",required=True,type=Path)
    a = ap.parse_args()
    text = a.receipt_file.read_text(encoding="utf-8")
    report = advise(text)
    print(json.dumps(report,ensure_ascii=False))

if __name__=="__main__":
    main()
