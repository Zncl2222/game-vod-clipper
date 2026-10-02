"""Offline, journaled media relocation. Originals survive until explicit cleanup.

Usage: plan ROOT DESTINATION, then copy/switch/cleanup MANIFEST.
Stop the local server before every phase except plan. After switch, start it and
verify playback, then stop it again before cleanup. No recursive deletion occurs.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile
import time


PATH_KEYS = {"source", "work", "path", "output", "file", "video", "packet", "worker_result",
             "workspace", "source_path", "output_path", "image_path", "frame_path", "sheet_path"}
MEDIA = {".mp4", ".mkv", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp"}
last_progress = 0


def progress(message, force=False):
    global last_progress
    if force or time.monotonic() - last_progress >= 15:
        print(message, flush=True)
        last_progress = time.monotonic()


def stamp(path):
    if path.is_symlink() or path.resolve() != path:
        raise ValueError(f"Refusing linked path: {path}")
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino]


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(8 * 1024 * 1024):
            result.update(block)
            progress(f"hashing {path.name}: {f.tell() / 1e9:.2f} GB")
    return result.hexdigest()


def plan(root, destination):
    root, destination = root.resolve(), destination.resolve()
    if destination == destination.parent or destination == root or root.is_relative_to(destination):
        raise ValueError("Destination must be a dedicated media directory")
    pairs = [(root / name, destination / name) for name in ("downloads", "clips")]
    for path in sorted((root / "runs").iterdir()):
        if path.name == "web":
            pairs.extend((child, destination / "runs/web" / child.name) for child in sorted(path.iterdir())
                         if child.is_dir() and child.name not in {"youtube", "profiles"})
        elif path.is_dir() and not path.name.startswith(("browser-deps-", "storage-migration-", "codex-check-")):
            pairs.append((path, destination / "runs" / path.name))
        elif path.is_file() and path.suffix.lower() in MEDIA:
            pairs.append((path, destination / "runs" / path.name))
    entries, identities = [], set()
    for source, target in pairs:
        if source.is_symlink() or source.resolve() != source or target.resolve() != target:
            raise ValueError(f"Unsafe mapping: {source}")
        for file in ([source] if source.is_file() else sorted(source.rglob("*"))):
            if file.is_symlink():
                raise ValueError(f"Symlink in media tree: {file}")
            if not file.is_file():
                continue
            out = target if source.is_file() else target / file.relative_to(source)
            normalized = str(out).casefold()
            if normalized in identities or out.exists():
                raise ValueError(f"Destination collision (nothing overwritten): {out}")
            identities.add(normalized)
            entries.append({"source": str(file), "destination": str(out), "original": stamp(file)})
    size = sum(entry["original"][0] for entry in entries)
    if shutil.disk_usage(destination).free < size + 1024**3:
        raise ValueError("Insufficient destination space including 1 GiB safety margin")
    report = Path(tempfile.mkdtemp(prefix="storage-migration-", dir=root / "runs"))
    manifest = report / "manifest.json"
    data = {"root": str(root), "destination": str(destination), "phase": "planned", "bytes": size,
            "pairs": [[str(s), str(t)] for s, t in pairs], "files": entries}
    atomic_json(manifest, data)
    progress(f"PLAN {manifest}: {len(entries)} files, {size / 1e9:.3f} GB", True)
    return manifest


def copy_entry(entry):
    source, destination = Path(entry["source"]), Path(entry["destination"])
    if stamp(source) != entry["original"]:
        raise ValueError(f"Source changed: {source}")
    if entry.get("verified"):
        if stamp(destination) != entry["verified"]:
            raise ValueError(f"Verified destination changed: {destination}")
        return {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.resolve() != destination:
        raise ValueError(f"Destination became linked: {destination}")
    if destination.exists():
        # Recovery from interruption after rename but before journaling.
        original_hash = digest(source)
        if digest(destination) != original_hash:
            raise ValueError(f"Destination conflict: {destination}")
    else:
        hasher = hashlib.sha256()
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".bosscut-moving-", delete=False) as out:
            temporary = Path(out.name)
            try:
                with source.open("rb") as incoming:
                    while block := incoming.read(8 * 1024 * 1024):
                        out.write(block)
                        hasher.update(block)
                        progress(f"COPY {source.name}: {incoming.tell() / 1e9:.2f}/{entry['original'][0] / 1e9:.2f} GB")
                out.flush()
                os.fsync(out.fileno())
                os.utime(temporary, ns=(source.stat().st_atime_ns, entry["original"][1]))
                if destination.exists():
                    raise ValueError(f"Destination appeared during copy: {destination}")
                temporary.rename(destination)
            finally:
                temporary.unlink(missing_ok=True)
        original_hash = hasher.hexdigest()
        if digest(destination) != original_hash:
            raise ValueError(f"Checksum mismatch: {destination}")
    if stamp(source) != entry["original"]:
        raise ValueError(f"Source changed during copy: {source}")
    return {"sha256": original_hash, "verified": stamp(destination)}


def copy_files(manifest, data):
    if data["phase"] not in {"planned", "copied"}:
        raise ValueError("Cannot copy after references have been switched")
    completed, checkpoint = 0, time.monotonic()
    # Bounded I/O concurrency hides WSL/Windows per-file metadata latency.
    # Every file still gets an independent fsync and SHA-256 readback.
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(copy_entry, entry): entry for entry in data["files"]}
        for index, future in enumerate(as_completed(pending), 1):
            entry = pending[future]
            entry.update(future.result())
            completed += entry["original"][0]
            progress(f"VERIFIED {index}/{len(data['files'])}: {completed / 1e9:.2f}/{data['bytes'] / 1e9:.2f} GB")
            if index % 100 == 0 or time.monotonic() - checkpoint >= 15:
                atomic_json(manifest, data)
                checkpoint = time.monotonic()
    data["phase"] = "copied"
    atomic_json(manifest, data)
    progress(f"All {len(data['files'])} files copied and SHA-256 verified; originals retained", True)


def remap(value, data):
    path = Path(value)
    if not path.is_absolute():
        path = Path(data["root"]) / path
    for source, target in data["pairs"]:
        if path == Path(source) or path.is_relative_to(Path(source)):
            return str(Path(target) / path.relative_to(Path(source)))
    return value


def rewrite(value, data, key=""):
    if isinstance(value, dict):
        return {k: rewrite(v, data, k) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite(v, data, key) for v in value]
    if isinstance(value, str) and key in PATH_KEYS:
        return remap(value, data)
    return value


def verify_pair(entry):
    if stamp(Path(entry["source"])) != entry["original"] or stamp(Path(entry["destination"])) != entry["verified"]:
        raise ValueError(f"File changed since verification: {entry['source']}")


def preflight(entries):
    with ThreadPoolExecutor(max_workers=8) as pool:
        for index, _ in enumerate(pool.map(verify_pair, entries), 1):
            progress(f"Preflight verified {index}/{len(entries)} files")


def switch_paths(manifest, data):
    if data["phase"] != "copied":
        raise ValueError("All files must be verified before changing references")
    preflight(data["files"])
    root, report = Path(data["root"]), manifest.parent
    state = root / "runs/web/state.sqlite3"
    backup = report / "state-before.sqlite3"
    with sqlite3.connect(state) as db:
        if not backup.exists():
            with sqlite3.connect(backup) as dest:
                db.backup(dest)
        before = dict(db.execute("SELECT id,data FROM youtube_history"))
        paths = {Path(entry["destination"]): entry for entry in data["files"]}
        # Export receipts already created at the new location can still mention
        # an old source. Include them without recopying their media.
        for (raw,) in db.execute("SELECT data FROM jobs"):
            job = json.loads(raw)
            if job.get("kind") == "export" and job.get("output"):
                output = Path(job["output"])
                if not output.is_absolute():
                    output = root / output
                output = Path(remap(str(output), data)).with_suffix(".json")
                if output.exists():
                    paths.setdefault(output, None)
        for file in (root / "runs/web/youtube").glob("upload-*.json"):
            paths.setdefault(file, None)
        metadata_count = 0
        migrated_sources = {entry["destination"] for entry in data["files"] if entry.get("verified")}
        for file, entry in paths.items():
            if file.suffix != ".json":
                continue
            if file.is_symlink() or file.resolve() != file:
                raise ValueError(f"Linked metadata: {file}")
            try:
                old = json.loads(file.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                continue
            changed = rewrite(old, data)
            if file.name == "checkpoint.json" and isinstance(changed, dict):
                identity = changed.get("identity", {})
                if isinstance(identity, dict) and identity.get("source") in migrated_sources:
                    stat = Path(identity["source"]).stat()
                    if identity.get("size") != stat.st_size:
                        raise ValueError(f"Checkpoint source size changed: {file}")
                    identity["mtime"] = stat.st_mtime_ns
            if changed != old:
                saved = report / "metadata-before" / hashlib.sha256(str(file).encode()).hexdigest()
                if not saved.exists():
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(file, saved)
                    saved.chmod(0o600)
                atomic_json(file, changed)
                metadata_count += 1
                if entry is not None:
                    entry.update(verified=stamp(file), final_sha256=digest(file))
        atomic_json(manifest, data)
        db.execute("BEGIN IMMEDIATE")
        for table in ("projects", "jobs", "retained_media"):
            for key, raw in db.execute(f"SELECT id,data FROM {table}").fetchall():  # nosec B608 # table comes from the fixed tuple above; values are bound.
                old = json.loads(raw)
                changed = rewrite(old, data)
                if table == "projects" and not old.get("work"):
                    old_work = str(root / "runs/web" / key)
                    new_work = remap(old_work, data)
                    if old_work != new_work:
                        changed["work"] = new_work
                if changed != old:
                    db.execute(f"UPDATE {table} SET data=? WHERE id=?", (json.dumps(changed, ensure_ascii=False), key))  # nosec B608 # table comes from the fixed tuple above; values are bound.
        if dict(db.execute("SELECT id,data FROM youtube_history")) != before:
            raise ValueError("History unexpectedly changed")
        db.commit()
    data.update(phase="switched", metadata_updated=metadata_count, history_count=len(before))
    atomic_json(manifest, data)
    progress(f"Paths switched; {metadata_count} metadata files updated; all {len(before)} YouTube histories preserved", True)


def cleanup(manifest, data):
    if data["phase"] != "switched":
        raise ValueError("Switch paths and verify playback before cleanup")
    # Preflight the entire manifest before removing any original. Recheck each
    # exact source and verified destination again immediately before unlink.
    for entry in data["files"]:
        if entry.get("removed"):
            continue
        if not Path(entry["source"]).exists():
            destination = Path(entry["destination"])
            if stamp(destination) != entry["verified"] or digest(destination) != entry.get("final_sha256", entry["sha256"]):
                raise ValueError(f"Missing source without verified replacement: {entry['source']}")
            entry["removed"] = True
            continue
    remaining = [entry for entry in data["files"] if not entry.get("removed")]
    preflight(remaining)
    freed = sum(entry["original"][0] for entry in data["files"] if entry.get("removed"))

    def remove_entry(entry):
        verify_pair(entry)
        Path(entry["source"]).unlink()
        return entry

    with ThreadPoolExecutor(max_workers=8) as pool:
        for index, entry in enumerate(pool.map(remove_entry, remaining), 1):
            entry["removed"] = True
            freed += entry["original"][0]
            if index % 100 == 0:
                atomic_json(manifest, data)
            progress(f"Removing verified old copies: {index}/{len(remaining)}, {freed / 1e9:.2f} GB")
    data.update(phase="complete", removed_bytes=freed)
    atomic_json(manifest, data)
    progress(f"Relocation complete: {len(data['files'])} files, {freed / 1e9:.3f} GB; no directories recursively deleted", True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "copy", "switch", "cleanup"))
    parser.add_argument("path", type=Path)
    parser.add_argument("destination", nargs="?", type=Path)
    args = parser.parse_args()
    if args.phase == "plan":
        if args.destination is None:
            parser.error("plan requires a destination")
        plan(args.path, args.destination)
        return
    with socket.socket() as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", 8001)) == 0:
            parser.error("Stop the local service on port 8001 before changing media")
    data = json.loads(args.path.read_text())
    {"copy": copy_files, "switch": switch_paths, "cleanup": cleanup}[args.phase](args.path.resolve(), data)


if __name__ == "__main__":
    main()
