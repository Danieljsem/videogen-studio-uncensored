"""Download model packs from Hugging Face into models/.

  python download_models.py video          Wan 2.2 I2V A14B (~71 GB) – image -> video
  python download_models.py image          Chroma1-HD (~27.5 GB) – text -> image, uncensored, Apache 2.0
  python download_models.py sdxl           configs only (~5 MB) for your own SDXL checkpoints in models/checkpoints
  python download_models.py video image    several at once

Interrupted downloads resume where they stopped. Files that are already complete are skipped.
--machine prints "PROGRESS <done bytes> <total bytes>" lines (used by the Studio server) instead of a progress bar.
"""
import argparse
import fnmatch
import os
import shutil
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from catalog import M, PACKS, installed  # noqa: E402

STAGE = M / ".download"   # single files land here first, then move into place


def plan(packs):
    """[(repo, path in repo, local_dir for hf_hub_download, final target, size)] of files still missing."""
    from huggingface_hub import HfApi
    api = HfApi()
    todo = []
    for name in packs:
        p = PACKS[name]
        by_repo = {}
        for repo, path, sub in p["files"]:
            by_repo.setdefault(repo, []).append((path, sub))
        for repo, items in by_repo.items():
            sizes = {i.path: getattr(i, "size", 0) or 0 for i in api.get_paths_info(repo, [x for x, _ in items])}
            for path, sub in items:
                target = M / sub / Path(path).name
                todo.append((repo, path, STAGE, target, sizes.get(path, 0)))
        for repo, patterns, sub in p["snapshots"]:
            info = api.model_info(repo, files_metadata=True)
            for s in info.siblings:
                if any(fnmatch.fnmatch(s.rfilename, pat) for pat in patterns):
                    todo.append((repo, s.rfilename, M / sub, M / sub / s.rfilename, s.size or 0))
    # skip complete files; config/index files last so a half-finished pack never looks installed
    todo = [t for t in todo if not (t[3].exists() and (not t[4] or t[3].stat().st_size == t[4]))]
    todo.sort(key=lambda t: (t[1].endswith(".json"), t[1]))
    return todo


def partial_bytes():
    """Bytes of unfinished downloads (huggingface_hub keeps them as *.incomplete under <local_dir>/.cache)."""
    n = 0
    for cache in M.rglob(".cache"):
        for f in cache.rglob("*.incomplete"):
            try:
                n += f.stat().st_size
            except OSError:
                pass
    return n


def watch_parent():
    """Stop when the Studio server that started us exits (otherwise a 70 GB download would keep running unseen)."""
    pid = int(os.environ.get("WAN_PARENT_PID") or 0)
    if not pid:
        return
    try:
        import psutil
        ct = psutil.Process(pid).create_time()
    except Exception:
        return

    def loop():
        while True:
            time.sleep(5)
            try:
                alive = psutil.Process(pid).create_time() == ct
            except Exception:
                alive = False
            if not alive:
                os._exit(3)   # the partial file stays; the next run resumes it
    threading.Thread(target=loop, daemon=True).start()


def human(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packs", nargs="+", choices=sorted(PACKS))
    ap.add_argument("--machine", action="store_true", help="print PROGRESS lines instead of a progress bar")
    a = ap.parse_args()
    packs = list(dict.fromkeys(a.packs))
    watch_parent()

    print(f"Checking {', '.join(PACKS[p]['name'] for p in packs)}…", flush=True)
    try:
        todo = plan(packs)
    except Exception as e:  # offline, Hugging Face down, …
        print(f"ERROR cannot reach Hugging Face: {e}", flush=True)
        return 1
    total = sum(t[4] for t in todo)
    if not todo:
        print("Everything is already downloaded.", flush=True)
        print("DONE", flush=True)
        return 0
    M.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(M).free
    if free < total + 2e9:
        print(f"ERROR not enough disk space: need {human(total)} + 2 GB, free {human(free)} on the models drive", flush=True)
        return 2
    print(f"Downloading {len(todo)} files, {human(total)}", flush=True)

    from huggingface_hub import hf_hub_download
    done = [0]
    stop = threading.Event()

    def report():
        last = None
        while not stop.wait(1.0):
            cur = min(total, done[0] + partial_bytes())
            if a.machine:
                print(f"PROGRESS {cur} {total}", flush=True)
            elif cur != last:
                w = 30
                k = int(w * cur / max(1, total))
                sys.stdout.write(f"\r  [{'#' * k}{'.' * (w - k)}] {human(cur)} / {human(total)}   ")
                sys.stdout.flush()
            last = cur

    threading.Thread(target=report, daemon=True).start()
    try:
        for repo, path, local_dir, target, size in todo:
            for attempt in range(3):
                try:
                    got = Path(hf_hub_download(repo, path, local_dir=str(local_dir)))
                    break
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    if attempt == 2:
                        raise
                    print(f"\n  retrying {Path(path).name}: {e}", flush=True)
                    time.sleep(5 * (attempt + 1))
            if got.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(got, target)
            done[0] += size
            if not a.machine:
                sys.stdout.write(f"\r  ok  {Path(path).name}{' ' * 40}\n")
            else:
                print(f"FILE {Path(path).name}", flush=True)
    except KeyboardInterrupt:
        stop.set()
        print("\nStopped – run the same command again to resume.", flush=True)
        return 130
    except Exception as e:
        stop.set()
        print(f"\nERROR {e}", flush=True)
        return 1
    stop.set()
    shutil.rmtree(STAGE, ignore_errors=True)
    bad = [p for p in packs if not installed(p)]
    if bad:
        print(f"\nERROR incomplete after download: {', '.join(bad)}", flush=True)
        return 1
    if a.machine:
        print(f"PROGRESS {total} {total}", flush=True)
    print("\nDONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
