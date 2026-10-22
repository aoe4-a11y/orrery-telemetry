#!/usr/bin/env python3
"""head-evidence-export: R-087 / storage v5.9 の「head の正規の参照の export」を作る。

dev-storage-governor retire-scratch が読む index.json（version 1・complete）を書く。
参照元は 5 種類（mail・task・ledger・review・catalog）。mail は orrery の DB から 1 通 1 file の md に、
catalog は governor の root の中の catalog／manifest／known-inputs の json を写す（path で引けるように）。
events は便の件名の [tag] から、tasks は ~/.agentstack/runtime/tasks/STATE.json（head が開閉を書く）から。
使い方: head-evidence-export.py            # export を作り index の path を出す
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import stat as stat_module
import sys
import sqlite3
from pathlib import Path

HOME = Path.home()
MODULE_SOURCE = Path(__file__).resolve().parent.parent / 'src'
if not MODULE_SOURCE.is_dir():
    MODULE_SOURCE = HOME / 'tools/dev-storage-governor/src'
sys.path.insert(0, str(MODULE_SOURCE))
from dev_storage_governor.retention import record_bytes
EXP = Path('/Volumes/DevSSD-Private/DevStorageGovernor/receipts/head-evidence-export')
DB = HOME / '.agentstack/mail/storage.sqlite3'
TASKS = HOME / '.agentstack/runtime/tasks'
STATE = TASKS / 'STATE.json'
LEDGER = Path('/Users/huyuhutaru/tools/osce-trainer-main/docs/ledger')
REVIEW = HOME / 'Documents/ExamForge-Review-2026-09-11'
ARTIFACT_BASES = [Path('/Volumes/DevSSD-Private/DevStorageGovernor/artifacts'),
                  Path('/Volumes/DevSSD/DevStorageGovernor/artifacts'),
                  HOME / '.dev-storage-governor']
CATALOG_NAME = re.compile(r'(catalog|manifest|known-inputs|record-manifest|inputs).*\.json$', re.I)
TAG = re.compile(r'^\s*\[([A-Za-z][\w-]*)\]\s*(.*)$')
STATION = re.compile(r'([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+|[A-Z]{2,}[0-9]+)')
RECEIPT_REF = re.compile(r'receipt[=:＝]\s*(\d+)')


def export_mail():
    out = EXP / 'mail'
    out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    rows = con.execute('select m.id, m.created_ts, a.name, m.subject, m.body_md from messages m '
                       'join agents a on a.id=m.sender_id order by m.id').fetchall()
    events = []
    for mid, ts, sender, subject, body in rows:
        f = out / f'{mid:08d}.md'
        if not f.exists():
            tmp = f.with_suffix('.tmp')
            tmp.write_text(f'id: {mid}\ncreated_ts: {ts}\nfrom: {sender}\nsubject: {subject}\n\n{body or ""}\n', encoding='utf-8')
            os.replace(tmp, f)
        m = TAG.match(subject or '')
        if not m:
            continue
        tag, rest = m.group(1).lower(), m.group(2)
        st = STATION.search(rest)
        ev = {'id': mid, 'tag': tag, 'sender': sender, 'station': st.group(1) if st else None}
        if tag == 'accept':
            r = RECEIPT_REF.search(rest) or RECEIPT_REF.search(body or '')
            ev['receipt_id'] = int(r.group(1)) if r else None
        events.append(ev)
    return out, events


def export_catalog_copy(source: Path, destination: Path, origins: dict):
    """Keep every prior version and avoid writes to an identical readonly copy."""
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    witness = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if witness(before) != witness(after):
        raise ValueError('catalog source changed while reading')
    source_sha = hashlib.sha256(data).hexdigest()
    old_data = None
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError('catalog destination is not a regular file')
        old_data = destination.read_bytes()
    if old_data != data:
        if old_data is not None:
            old_sha = hashlib.sha256(old_data).hexdigest()
            # Keep the key as the stem: the deletion guard validates it against
            # source_path. Both versions retain the same relative-path anchor.
            historical = destination.parent / 'history' / old_sha / destination.name
            historical.parent.mkdir(parents=True, exist_ok=True)
            if historical.exists():
                if historical.is_symlink() or historical.read_bytes() != old_data:
                    raise ValueError('catalog history collision')
            else:
                with historical.open('xb') as stream:
                    stream.write(old_data)
                    stream.flush()
                    os.fsync(stream.fileno())
            historical_stat = historical.stat()
            origins[str(historical)] = {
                'export_path': str(historical), 'source_path': str(source),
                'sha256': old_sha, 'export_size': historical_stat.st_size,
                'export_mtime_ns': historical_stat.st_mtime_ns,
                'historical': True, 'superseded_by': str(destination),
            }
        fd, temporary_name = tempfile.mkstemp(prefix='.' + destination.stem + '-',
                                              suffix='.tmp', dir=destination.parent)
        temporary = Path(temporary_name)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), 0o644)
            stream.flush()
            os.fsync(stream.fileno())
        if (hashlib.sha256(temporary.read_bytes()).hexdigest() != source_sha
                or witness(source.stat()) != witness(after)):
            raise ValueError('catalog source/copy drift')
        os.replace(temporary, destination)
    destination_stat = destination.stat()
    origins[str(destination)] = {
        'export_path': str(destination), 'source_path': str(source), 'sha256': source_sha,
        'source_size': after.st_size, 'source_mtime_ns': after.st_mtime_ns,
        'export_size': destination_stat.st_size,
        'export_mtime_ns': destination_stat.st_mtime_ns,
    }


def export_catalogs():
    out = EXP / 'catalog'
    out.mkdir(parents=True, exist_ok=True)
    seen = set()
    # DELETE-CAUSE-2（2026-10-13・M-060）: 写しごとに元の path と SHA を sidecar に残す。retire は origin の
    # 無い root を消さない（保留）。読めなかった file は origin を付けずに errors へ（fail-closed）。
    origins_path = EXP / 'catalog-origins.json'
    prior = json.loads(origins_path.read_text()) if origins_path.exists() else {'version': 1, 'files': []}
    if prior.get('version') != 1 or not isinstance(prior.get('files'), list):
        raise ValueError('invalid catalog origins sidecar')
    origins = {row['export_path']: row for row in prior['files']}
    errors = []
    for base in ARTIFACT_BASES:
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if not d.endswith(('.xcarchive', '.xcresult', '.app', '.dSYM')) and d != '.git'
                       and d != 'DerivedData' and d != 'head-evidence-export']
            for name in files:
                if not CATALOG_NAME.search(name):
                    continue
                p = Path(current) / name
                if p.is_symlink():
                    continue
                try:
                    st = p.stat()
                    # 普通の file だけ読む。名前付き pipe（試験の fixture の migration-manifest.json）を open して
                    # 書き手を永久に待ち、export が止まった（2026-10-13 15:39〜16:18）。
                    if not stat_module.S_ISREG(st.st_mode) or st.st_size > 64 * 2**20:
                        continue
                except OSError:
                    continue
                key = hashlib.sha256(str(p).encode()).hexdigest()[:24]
                # 壊れた JSON は捨てずに .txt として写す（governor が文字として path を拾う・保守側）
                try:
                    with p.open(encoding='utf-8') as stream:
                        json.load(stream)
                    dst = out / f'{key}.json'
                except Exception:
                    dst = out / f'{key}.txt'
                seen.add(dst.name)
                try:
                    src_stat = p.stat()
                    dst_stat = dst.stat() if dst.exists() else None
                    row = origins.get(str(dst))
                    # 元も写しも大きさと mtime が前回と同じなら、前回の SHA を使う（毎回の全量 hash で 20 分かかった）
                    if not (row and dst_stat and row.get('source_path') == str(p) and row.get('source_size') == src_stat.st_size
                            and row.get('source_mtime_ns') == src_stat.st_mtime_ns and row.get('export_size') == dst_stat.st_size
                            and row.get('export_mtime_ns') == dst_stat.st_mtime_ns):
                        export_catalog_copy(p, dst, origins)
                except (OSError, ValueError) as error:
                    origins.pop(str(dst), None)
                    errors.append({'export_path': str(dst), 'source_path': str(p), 'error': f'{type(error).__name__}: {error}'})
    # 元が消えた後に残る写し（origin を付ける前の旧 export・2026-10-13 時点で 46 件）は、起点不明として
    # unmapped に明記する。中の path の引用は今までどおり参照として守る（retire 全体は止めない）。
    unmapped = sorted(str(q) for q in out.rglob('*')
                      if q.is_file() and q.suffix in ('.json', '.txt') and str(q) not in origins)
    temporary = origins_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps({'version': 1, 'files': [origins[k] for k in sorted(origins)], 'errors': errors,
                                     'unmapped': [{'export_path': q, 'reason': 'source vanished before origin tracking; '
                                                   'source_path not recoverable (export key is a one-way path hash)'}
                                                  for q in unmapped]},
                                    ensure_ascii=False, indent=2) + '\n')
    os.replace(temporary, origins_path)
    # 元が無くなった catalog の写しも消さない（それが唯一の記録かもしれない・storage v5.9 の記録は永久保存。
    # 残った写しは、もう無い path を守るだけで害は無い。GOV-3 便19151）。
    return out


def fixture_role_source(approval_index: Path, destination: Path):
    """Add provenance only; existing catalog copies are never edited or skipped."""
    from dev_storage_governor.fixture_roles import descriptor, FixtureRoles
    value = descriptor(approval_index)
    roles = FixtureRoles(value)
    # Persist per-source refusals too; never drop the ordinary catalog or
    # silently grant recovery to a drifted source. Readers recompute the gate.
    value['source_holds'] = list(roles.holds.values())
    value['provenance_reads'] = list(roles.provenance_reads.values())
    data = (json.dumps(value, sort_keys=True) + "\n").encode()
    sha = hashlib.sha256(data).hexdigest()
    path = destination / ("fixture-roles-" + sha + ".json")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError("fixture role source changed")
    else:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    return {"path": str(path), "sha256": sha}


def preview_index(source: Path, destination: Path, approval_index: Path):
    """New preview record; reference existing source bytes without copying them."""
    destination.mkdir(parents=True, exist_ok=True)
    source_data = record_bytes(source)
    value = json.loads(source_data)
    value["preview_only"] = True
    value["projection_source"] = {"path": str(source), "sha256": hashlib.sha256(source_data).hexdigest()}
    value["fixture_roles"] = fixture_role_source(approval_index, destination)
    value["exported_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    path = destination / "index.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture-approval-index", type=Path)
    ap.add_argument("--preview-source-index", type=Path)
    ap.add_argument("--preview-destination", type=Path)
    args = ap.parse_args()
    if args.preview_source_index:
        if not args.preview_destination or not args.fixture_approval_index:
            ap.error("preview requires destination and fixture approval index")
        print(preview_index(args.preview_source_index, args.preview_destination,
                            args.fixture_approval_index))
        return
    approval = args.fixture_approval_index
    pointer = EXP / "fixture-approval.json"
    if approval is None and pointer.exists():
        value = json.loads(record_bytes(pointer))
        if value.get("version") != 1:
            raise ValueError("invalid fixture approval pointer")
        approval = Path(value["approval_evidence_index"])
    EXP.mkdir(parents=True, exist_ok=True)
    mail_dir, events = export_mail()
    catalog_dir = export_catalogs()
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    tasks = [{'station': k, 'state': v} for k, v in sorted(state.items())]
    index = {
        'version': 1,
        'complete': True,
        'exported_at_utc': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'exported_by': 'ProudTuring',
        'sources': [
            {'kind': 'mail', 'path': str(mail_dir)},
            {'kind': 'task', 'path': str(TASKS)},
            {'kind': 'ledger', 'path': str(LEDGER)},
            {'kind': 'review', 'path': str(REVIEW)},
            {'kind': 'catalog', 'path': str(catalog_dir), 'origins': str(EXP / 'catalog-origins.json')},
        ],
        'events': events,
        'tasks': tasks,
    }
    if approval is not None:
        index['fixture_roles'] = fixture_role_source(approval, EXP)
    tmp = EXP / 'index.json.tmp'
    tmp.write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, EXP / 'index.json')
    print(EXP / 'index.json')


if __name__ == '__main__':
    main()
