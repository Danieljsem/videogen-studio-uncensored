"""Videogen Studio – local web app on top of generate.py.

Start: studio.bat (Electron) or `python server.py` and open http://127.0.0.1:7870.
Standard library + Pillow only.
Queue: only one video renders at a time (single GPU), the rest wait. Every video in output/ has
<name>.json (settings, timing) and <name>.jpg (poster = cropped input image) next to it.
WAN_MOCK=1 -> runs mock_generate.py instead of generate.py (UI testing without a GPU).
User-facing messages are returned as {"en": ..., "cs": ..., "de": ..., "uk": ..., "es": ...}; the UI picks one.
"""
import base64
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
MOCK = os.environ.get("WAN_MOCK") == "1"
OUT = ROOT / ("test/mock_output" if MOCK else "output")   # keep mock runs out of the real library
UPL = ROOT / ("test/mock_uploads" if MOCK else "uploads")
LORAS = ROOT / "models" / "loras"
WEB = ROOT / "web"
PORT = int(os.environ.get("WAN_PORT", "7870"))   # 7860 is taken by Gradio/A1111/Forge
OUT.mkdir(parents=True, exist_ok=True)
UPL.mkdir(parents=True, exist_ok=True)

ASPECTS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "3:2": 3 / 2, "2:3": 2 / 3, "4:5": 4 / 5}
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".mp4": "video/mp4", ".jpg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json"}

jobs = []          # dicts, newest last
_meta_cache = {}   # json path -> (mtime, meta)
lock = threading.Lock()
wake = threading.Event()


LANGS = ("en", "cs", "de", "uk", "es")
# User-facing messages: key -> (en, cs, de, uk, es); "{name}" placeholders are filled by msg(key, name=...)
MESSAGES = {
    "oom": ("Out of GPU memory. Try 480p or a shorter video (and close other apps that use the GPU).",
            "Došla paměť grafiky. Zkus 480p nebo kratší video (a zavři jiné programy, co používají GPU).",
            "Kein GPU-Speicher mehr. Versuche 480p oder ein kürzeres Video (und schließe andere Programme, die die GPU nutzen).",
            "Бракує пам'яті відеокарти. Спробуйте 480p або коротше відео (і закрийте інші програми, що використовують GPU).",
            "Sin memoria de GPU. Prueba 480p o un vídeo más corto (y cierra otras apps que usen la GPU)."),
    "parent_gone": ("Generation stopped because the Studio server exited.",
                    "Generování skončilo, protože se ukončil server Studia.",
                    "Die Generierung wurde beendet, weil der Studio-Server beendet wurde.",
                    "Генерацію зупинено, бо сервер Studio завершив роботу.",
                    "La generación se detuvo porque el servidor de Studio se cerró."),
    "crash": ("The generator crashed ({why}) – most likely the GPU driver or memory. Try again; if it keeps happening, restart the PC.",
              "Generátor spadl ({why}) – nejspíš ovladač grafiky nebo paměť. Zkus to znovu; když se to opakuje, restartuj PC.",
              "Der Generator ist abgestürzt ({why}) – vermutlich GPU-Treiber oder Speicher. Versuche es erneut; wenn es wieder passiert, starte den PC neu.",
              "Генератор аварійно завершився ({why}) – найімовірніше, драйвер відеокарти або пам'ять. Спробуйте ще раз; якщо повторюється, перезавантажте ПК.",
              "El generador falló ({why}): probablemente el driver de la GPU o la memoria. Inténtalo de nuevo; si se repite, reinicia el PC."),
    "failed": ("Generation failed (code {code}). Details in the log {log}.",
               "Generování skončilo s chybou (kód {code}). Podrobnosti v logu {log}.",
               "Generierung fehlgeschlagen (Code {code}). Details im Log {log}.",
               "Помилка генерації (код {code}). Подробиці в журналі {log}.",
               "La generación falló (código {code}). Detalles en el registro {log}."),
    "after_finish": ("Error after finishing: {err}", "Chyba po dokončení: {err}", "Fehler nach dem Abschluss: {err}",
                     "Помилка після завершення: {err}", "Error tras finalizar: {err}"),
    "ph_queued": ("Queued", "Ve frontě", "In der Warteschlange", "У черзі", "En cola"),
    "ph_start": ("Starting", "Spouštím", "Starte", "Запуск", "Iniciando"),
    "ph_prompt": ("Reading prompt", "Čtu prompt", "Lese Prompt", "Читаю промпт", "Leyendo prompt"),
    "ph_model1": ("Loading model 1/2", "Načítám model 1/2", "Lade Modell 1/2", "Завантажую модель 1/2", "Cargando modelo 1/2"),
    "ph_model2": ("Loading model 2/2", "Načítám model 2/2", "Lade Modell 2/2", "Завантажую модель 2/2", "Cargando modelo 2/2"),
    "ph_video": ("Generating video", "Generuji video", "Generiere Video", "Генерую відео", "Generando vídeo"),
    "ph_segment": ("Generating segment {seg}/{n}", "Generuji úsek {seg}/{n}", "Generiere Abschnitt {seg}/{n}",
                   "Генерую сегмент {seg}/{n}", "Generando segmento {seg}/{n}"),
    "ph_decode": ("Decoding frames", "Dekóduji snímky", "Dekodiere Frames", "Декодую кадри", "Decodificando fotogramas"),
    "not_found": ("Not found", "Nenalezeno", "Nicht gefunden", "Не знайдено", "No encontrado"),
    "forbidden": ("Forbidden", "Zakázáno", "Verboten", "Заборонено", "Prohibido"),
    "bad_request": ("Bad request", "Špatná data", "Ungültige Anfrage", "Некоректний запит", "Solicitud no válida"),
    "not_running": ("The job is not running", "Úloha neběží", "Der Auftrag läuft nicht", "Завдання не виконується", "La tarea no está en curso"),
    "bad_file": ("Bad file", "Špatný soubor", "Ungültige Datei", "Некоректний файл", "Archivo no válido"),
    "rendering": ("This video is still rendering", "Video se právě generuje", "Dieses Video wird gerade generiert",
                  "Це відео ще генерується", "Este vídeo aún se está generando"),
    "no_prompt": ("Describe what should happen in the video.", "Napiš, co se má ve videu dít.",
                  "Beschreibe, was im Video passieren soll.", "Опишіть, що має відбуватися у відео.",
                  "Describe lo que debe pasar en el vídeo."),
    "bad_settings": ("Invalid settings.", "Neplatné nastavení.", "Ungültige Einstellungen.", "Некоректні налаштування.",
                     "Ajustes no válidos."),
    "bad_aspect": ("Invalid aspect ratio.", "Neplatný poměr stran.", "Ungültiges Seitenverhältnis.",
                   "Некоректне співвідношення сторін.", "Relación de aspecto no válida."),
    "bad_image": ("Cannot read the image.", "Obrázek nejde přečíst.", "Das Bild kann nicht gelesen werden.",
                  "Не вдається прочитати зображення.", "No se puede leer la imagen."),
    "image_gone": ("The original image no longer exists, upload it again.", "Původní obrázek už neexistuje, nahraj ho znovu.",
                   "Das Originalbild existiert nicht mehr, lade es erneut hoch.",
                   "Оригінального зображення вже немає, завантажте його знову.",
                   "La imagen original ya no existe, súbela de nuevo."),
    "no_image": ("Add an image – Wan 2.2 turns an image into a video.", "Přidej obrázek – Wan 2.2 dělá video z obrázku.",
                 "Füge ein Bild hinzu – Wan 2.2 macht aus einem Bild ein Video.",
                 "Додайте зображення – Wan 2.2 робить відео із зображення.",
                 "Añade una imagen: Wan 2.2 convierte una imagen en vídeo."),
    "bad_seed": ("Seed must be a whole number 0 – 4294967295 (or empty = random).",
                 "Seed musí být celé číslo 0 – 4294967295 (nebo prázdné = náhodný).",
                 "Der Seed muss eine ganze Zahl 0 – 4294967295 sein (oder leer = zufällig).",
                 "Seed має бути цілим числом 0 – 4294967295 (або порожнім = випадковий).",
                 "La semilla debe ser un número entero 0 – 4294967295 (o vacía = aleatoria)."),
    "lora_gone": ("LoRA is no longer in models/loras: {name}", "LoRa už ve složce models/loras není: {name}",
                  "LoRA ist nicht mehr in models/loras: {name}", "LoRA більше немає в models/loras: {name}",
                  "La LoRA ya no está en models/loras: {name}"),
}
CRASH = {3221225477: ("access violation", "přístup do paměti", "Zugriffsverletzung", "порушення доступу", "violación de acceso"),
         3221226505: ("internal error", "vnitřní chyba", "interner Fehler", "внутрішня помилка", "error interno"),
         3221225725: ("stack overflow", "přetečení zásobníku", "Stapelüberlauf", "переповнення стеку", "desbordamiento de pila"),
         3221225794: ("missing DLL", "chybějící DLL", "fehlende DLL", "відсутня DLL", "falta una DLL"),
         3221225626: ("GPU driver", "ovladač grafiky", "GPU-Treiber", "драйвер відеокарти", "driver de la GPU")}


def msg(key, **kw):
    """A user-facing message in all UI languages: {"en": ..., "cs": ..., ...}. The UI picks one."""
    out = {}
    for i, lang in enumerate(LANGS):
        args = {k: (v[i] if isinstance(v, tuple) else v) for k, v in kw.items()}   # per-language args
        out[lang] = MESSAGES[key][i].format(**args)
    return out


# ---------- helpers ----------
def crop_aspect(img, aspect):
    if aspect not in ASPECTS:
        return img
    r = ASPECTS[aspect]
    w, h = img.size
    if w / h > r:
        nw = round(h * r)
        return img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    nh = round(w / r)
    return img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))


def lora_pairs():
    """High/low LoRA pairs from models/loras (except the built-in 4-step lightx2v)."""
    if not LORAS.exists():
        return []
    files = {f.name for f in LORAS.glob("*.safetensors") if "lightx2v" not in f.name}
    pairs = []
    for f in sorted(files):
        m = re.search(r"high", f, re.I)
        if not m:
            continue
        low = f[:m.start()] + ("LOW" if f[m.start():m.end()].isupper() else "low") + f[m.end():]
        if low in files:
            name = re.sub(r"[_\-. ]*high[_\-. ]*(noise)?", " ", f[:-12], flags=re.I).strip(" _-.") or f
            pairs.append({"id": f, "name": name.replace("_", " "), "high": f, "low": low})
    return pairs


def video_list():
    vids = []
    with lock:
        busy = {Path(j["out"]).name for j in jobs if j["status"] in ("queued", "running")}
    for mp4 in sorted(OUT.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        if mp4.name.endswith(".part.mp4") or mp4.name in busy:   # unfinished videos stay out of the library
            continue
        meta = {}
        js = mp4.with_suffix(".json")
        try:
            mt = js.stat().st_mtime
            if _meta_cache.get(js, (None,))[0] != mt:
                _meta_cache[js] = (mt, json.loads(js.read_text(encoding="utf-8")))
            meta = _meta_cache[js][1]
        except Exception:
            pass
        vids.append({"name": mp4.name, "url": f"/output/{mp4.name}",
                     "poster": f"/output/{mp4.stem}.jpg" if mp4.with_suffix(".jpg").exists() else None, "neg": meta.get("neg"),
                     "lora_ids": meta.get("lora_ids") or [],
                     "created": meta.get("finished") or mp4.stat().st_mtime, **{k: meta.get(k) for k in (
                         "prompt", "res", "sec", "aspect", "seed", "steps", "loras", "took", "width", "height", "upload", "partial", "error")}})
    return vids


# Time estimate (default constants, calibrated at runtime from finished videos): tokens N = (w/16)·(h/16)·(1 + (frames−1)/4).
# One step = A·N + B·N² (attention grows quadratically), VAE decode ≈ DEC·N, model loading LOAD_S.
LOAD_S, MODEL_A, MODEL_B, MODEL_DEC = 90, 1.46e-3, 3.42e-7, 0.0147
SEG_S, SEG_FRAMES = 5, 81


def tokens(w, h, frames=SEG_FRAMES):
    return (w // 16) * (h // 16) * (1 + (frames - 1) // 4)


def step_s(n, steps):
    return (MODEL_A * n + MODEL_B * n * n) * (1 if steps <= 8 else 2)   # without the speed-up LoRA, cfg 3.5 = 2 passes


def raw_estimate(w, h, sec, steps):
    n, segs = tokens(w, h), max(1, -(-sec // SEG_S))
    return LOAD_S + segs * (steps * step_s(n, steps) + MODEL_DEC * n)


def calib(vids):
    """Correction factor from real timings of finished videos (median, clamped to 0.5–2×)."""
    ks = sorted(v["took"] / raw_estimate(v["width"], v["height"], v["sec"], v.get("steps") or 4) for v in vids
                if v.get("took") and v.get("width") and v.get("height") and v.get("sec") and not v.get("partial"))
    return min(2.0, max(0.5, ks[len(ks) // 2])) if ks else 1.0


def estimate(w, h, sec, steps, k=1.0):
    return round(raw_estimate(w, h, sec, steps) * k)


def time_left(j, k):
    """Seconds left for a running job – from the speed tqdm reports (s/it), otherwise from the model."""
    if j["status"] != "running" or not j.get("started"):
        return None
    n, n_seg, steps = tokens(j["width"], j["height"]), j.get("n_seg") or max(1, -(-j["sec"] // SEG_S)), j["steps"]
    dec = MODEL_DEC * n * k
    if j.get("s_it"):
        seg, done = j.get("seg") or 1, j.get("k") or 0
        return round((steps - done) * j["s_it"] + dec + (n_seg - seg) * (steps * j["s_it"] + dec))
    return max(0, round(estimate(j["width"], j["height"], j["sec"], steps, k) - (time.time() - j["started"])))


def out_size(img, res):
    """Actual video size – same math as fit() in generate.py."""
    area, ar = (480 * 832 if res == 480 else 720 * 1280), img.height / img.width
    return round((area / ar) ** 0.5) // 16 * 16, round((area * ar) ** 0.5) // 16 * 16




def friendly_error(lines, code, log_name):
    errs = [l for l in lines if re.match(r"^[\w.]+(Error|Exception)\b", l)]
    last = errs[-1] if errs else ""
    if "OutOfMemory" in last or "out of memory" in last.lower():
        return msg("oom")
    if last:
        return last[:240]
    if code == 3:
        return msg("parent_gone")
    if code is not None and code % 2**32 in CRASH:
        return msg("crash", why=CRASH[code % 2**32])
    return msg("failed", code=code, log=log_name)


def public(j):
    return {k: j[k] for k in ("id", "status", "prompt", "res", "sec", "aspect", "steps", "seed", "progress",
                              "phase", "created", "started", "finished", "error", "video", "poster", "eta",
                              "width", "height")} | {"log": Path(j["out"]).with_suffix(".log").name}


def part_of(out):
    out = Path(out)
    return out.with_name(out.stem + ".part.mp4")   # generate.py writes here until the video is complete


# ---------- worker ----------
def track_speed(j, line, k):
    j["k"] = max(j.get("k") or 0, k)
    if m := re.search(r"([\d.]+)(s/it|it/s)\]", line):
        v = float(m[1])
        if v > 0:
            j["s_it"] = v if m[2] == "s/it" else 1 / v


def run_job(j):
    args = [sys.executable, "-u", str(ROOT / ("mock_generate.py" if MOCK else "generate.py")), j["image"], j["prompt"],
            "--res", str(j["res"]), "--sec", str(j["sec"]), "--steps", str(j["steps"]), "--out", j["out"]]
    if j["seed"] is not None:
        args += ["--seed", str(j["seed"])]
    if j.get("neg"):
        args += ["--neg", j["neg"]]
    for l in j["loras"]:
        args += ["--lora", str(LORAS / l["high"]), str(LORAS / l["low"]), str(l["w"])]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", WAN_PARENT_PID=str(os.getpid()))
    log_path = Path(j["out"]).with_suffix(".log")
    p = subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with lock:
        j["proc"] = p
        if j["status"] == "cancelled":  # cancelled right before the process started
            kill(p)
    n_seg, seg, buf = max(1, -(-j["sec"] // 5)), 0, b""
    with open(log_path, "wb") as lf:
        while True:
            ch = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(1)
            if not ch:
                break
            lf.write(ch)
            lf.flush()
            buf += ch
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            # tqdm rewrites its line with \r – read the unfinished line (e.g. "1/4 [40:16<…") right away, not with the next step
            if seg and (m := re.search(rb"(\d+)/(\d+) \[", buf)):
                k, n = int(m[1]), int(m[2])
                j["progress"] = max(j["progress"], 0.12 + 0.86 * (seg - 1 + 0.9 * k / n) / n_seg)
                track_speed(j, buf.decode("utf-8", "replace"), k)
            for raw in parts:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if "text encoder" in line:
                    j["phase"], j["progress"] = msg("ph_prompt"), 0.02
                elif "expert high" in line:
                    j["phase"], j["progress"] = msg("ph_model1"), 0.05
                elif "expert low" in line:
                    j["phase"], j["progress"] = msg("ph_model2"), 0.09
                elif m := re.search(r"segment (\d+)/(\d+):", line):
                    seg, n_seg = int(m[1]), int(m[2])
                    j["seg"], j["n_seg"], j["k"] = seg, n_seg, 0
                    j["phase"] = msg("ph_segment", seg=seg, n=n_seg) if n_seg > 1 else msg("ph_video")
                    j["progress"] = max(j["progress"], 0.12 + 0.86 * (seg - 1) / n_seg)
                elif seg and (m := re.search(r"(\d+)/(\d+) \[", line)):
                    k, n = int(m[1]), int(m[2])
                    j["progress"] = max(j["progress"], 0.12 + 0.86 * (seg - 1 + 0.9 * k / n) / n_seg)
                    track_speed(j, line, k)
                    if k == n:
                        j["phase"] = msg("ph_decode")
                elif "segment" in line and "done" in line and seg:
                    j["progress"] = max(j["progress"], 0.12 + 0.86 * seg / n_seg)
                elif line.startswith("[") and "DONE" in line:
                    j["progress"] = 1.0
                # Python errors (MIOpen messages are harmless)
                if "MIOpen" not in line and re.match(r"^[\w.]+(Error|Exception)\b", line):
                    j.setdefault("errlines", []).append(line)
    return p.wait()


def worker():
    while True:
        wake.wait()
        with lock:
            j = next((x for x in jobs if x["status"] == "queued"), None)
            if not j:
                wake.clear()
                continue
            j["status"], j["started"], j["phase"] = "running", time.time(), msg("ph_start")
        try:
            code = run_job(j)
        except Exception as e:  # noqa
            code, j["errlines"] = -1, [f"RuntimeError: {e!r}"]
        try:
            finish(j, code)
        except Exception as e:  # the queue must survive a failed cleanup
            j["status"], j["error"] = "error", msg("after_finish", err=repr(e)[:200])
        finally:
            j.pop("proc", None)
            j["finished"] = j["finished"] or time.time()


def kill(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        p.kill()


def rm(*paths):
    for f in paths:
        for _ in range(5):  # ffmpeg may hold the file for a moment
            try:
                Path(f).unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(1)


def finish(j, code):
        out, part = Path(j["out"]), part_of(j["out"])
        j["finished"] = time.time()
        if j["status"] == "cancelled":
            rm(out, part, out.with_suffix(".jpg"), out.with_suffix(".log"), j["image"])
            return
        ok = code == 0 and out.exists()
        if not ok:
            j["status"] = "error"
            j["error"] = friendly_error(j.get("errlines") or [], code, out.with_suffix(".log").name)
            if not out.exists() and part.exists() and part.stat().st_size > 0:   # keep at least the finished segments
                for _ in range(5):
                    try:
                        os.replace(part, out)
                        break
                    except PermissionError:
                        time.sleep(1)
            if not (out.exists() and out.stat().st_size > 0):   # nothing was produced – clean up (the log stays until dismissed)
                rm(out, part, out.with_suffix(".jpg"), j["image"])
                j["poster"] = None
                return
            j["video"] = f"/output/{out.name}"
        else:
            j["status"], j["progress"], j["video"] = "done", 1.0, f"/output/{out.name}"
        meta = {k: j[k] for k in ("prompt", "neg", "res", "sec", "aspect", "steps", "seed", "upload",
                                  "width", "height")}
        meta.update(loras=[f"{l['name']} ({l['w']:g})" for l in j["loras"]],
                    lora_ids=[{"id": l["id"], "w": l["w"]} for l in j["loras"]], finished=j["finished"])
        if ok:
            meta["took"] = round(j["finished"] - j["started"])
        else:
            meta.update(partial=True, error=j["error"])
        if j["seed"] is None:  # generate.py picked the seed – read it from the log
            m = re.search(r"seed (\d+)", out.with_suffix(".log").read_text("utf-8", "replace"))
            meta["seed"] = int(m[1]) if m else None
        out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if not (extra or {}).get("Cache-Control"):
            self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def file(self, path):
        if not path.is_file():
            return self.send(404, {"error": msg("not_found")})
        size = path.stat().st_size
        ctype = MIME.get(path.suffix.lower(), "application/octet-stream")
        # videos and posters never change (new = new name) -> cache; UI files always fresh
        cache = {"Cache-Control": "private, max-age=86400"} if path.suffix.lower() in (".mp4", ".jpg", ".png") else {}
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)$", rng.strip())) and (m[1] or m[2]):  # video seek
            a = int(m[1]) if m[1] else max(0, size - int(m[2]))
            b = min(int(m[2]) if m[1] and m[2] else size - 1, size - 1, a + 4 * 2**20 - 1)  # max 4 MB per request
            if a >= size or b < a:
                return self.send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
            with open(path, "rb") as f:
                f.seek(a)
                data = f.read(b - a + 1)
            return self.send(206, data, ctype, {"Content-Range": f"bytes {a}-{b}/{size}", "Accept-Ranges": "bytes", **cache})
        self.send(200, path.read_bytes(), ctype, {"Accept-Ranges": "bytes", **cache})

    def trusted(self):
        """Only our own UI: Host must be localhost:PORT, foreign Origins are rejected (protects against websites in a browser)."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        ok_hosts = (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
        return host in ok_hosts and (origin is None or origin in tuple("http://" + h for h in ok_hosts))

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.trusted():
            return self.send(403, {"error": msg("forbidden")})
        u = urlparse(self.path).path
        if u == "/":
            return self.file(WEB / "index.html")
        if u.startswith("/static/"):
            return self.safe(WEB, u[8:])
        if u.startswith("/output/"):
            return self.safe(OUT, u[8:])
        if u.startswith("/uploads/"):
            return self.safe(UPL, u[9:])
        if u == "/api/state":
            with lock:
                js = [public(j) for j in jobs if j["status"] in ("queued", "running")
                      or (j["status"] in ("error", "cancelled") and time.time() - (j["finished"] or 0) < 3600)]
                left = {j["id"]: time_left(j, 1.0) for j in jobs if j["status"] == "running"}
            vids = video_list()
            k = calib(vids)
            wait = 0
            for j in js:
                if j["status"] == "running":
                    j["left"] = left.get(j["id"])
                    wait += j["left"] or 0
                elif j["status"] == "queued":
                    j["eta"] = estimate(j["width"], j["height"], j["sec"], j["steps"], k)
                    j["wait"], wait = wait, wait + j["eta"]
            return self.send(200, {"app": "videogen-studio", "jobs": js, "videos": vids, "loras": lora_pairs(),
                                   "mock": MOCK, "model": {"load": LOAD_S, "a": MODEL_A, "b": MODEL_B,
                                                           "dec": MODEL_DEC, "seg": SEG_S, "k": k}})
        self.send(404, {"error": msg("not_found")})

    def safe(self, base, rel):
        p = (base / unquote(rel)).resolve()
        if base.resolve() not in p.parents:
            return self.send(403, {"error": msg("forbidden")})
        self.file(p)

    def do_POST(self):
        if not self.trusted() or not self.headers.get("Content-Type", "").startswith("application/json"):
            return self.send(403, {"error": msg("forbidden")})
        u = urlparse(self.path).path
        try:
            d = self.body()
            if not isinstance(d, dict):
                raise ValueError
        except Exception:
            return self.send(400, {"error": msg("bad_request")})
        if u == "/api/generate":
            return self.generate(d)
        if u == "/api/cancel":
            with lock:
                j = next((x for x in jobs if x["id"] == d.get("id")), None)
                if not j or j["status"] not in ("queued", "running"):
                    return self.send(404, {"error": msg("not_running")})
                was, j["status"], j["finished"] = j["status"], "cancelled", time.time()
                p = j.get("proc") if was == "running" else None
                if was == "queued":  # never started – clean up now
                    rm(Path(j["out"]).with_suffix(".jpg"), j["image"])
            if p:
                kill(p)  # outside the lock so /api/state does not block
            return self.send(200, {"ok": True})
        if u == "/api/dismiss":
            with lock:
                gone = [x for x in jobs if x["id"] == d.get("id") and x["status"] not in ("queued", "running")]
                jobs[:] = [x for x in jobs if x not in gone]
            for x in gone:
                if x["status"] == "error" and not x.get("video"):
                    rm(Path(x["out"]).with_suffix(".log"))
            return self.send(200, {"ok": True})
        if u == "/api/shutdown":   # closing the app when an earlier instance started the server
            with lock:
                procs = [x.get("proc") for x in jobs if x["status"] in ("queued", "running")]
                for x in jobs:
                    if x["status"] in ("queued", "running"):
                        x["status"] = "cancelled"
            for p in procs:
                if p:
                    kill(p)
            self.send(200, {"ok": True})
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return
        if u == "/api/delete":
            name = Path(str(d.get("name", ""))).name
            if not name.endswith(".mp4"):
                return self.send(400, {"error": msg("bad_file")})
            with lock:
                if any(Path(x["out"]).name == name and x["status"] in ("queued", "running") for x in jobs):
                    return self.send(409, {"error": msg("rendering")})
            meta = {}
            try:
                meta = json.loads((OUT / name).with_suffix(".json").read_text(encoding="utf-8"))
            except Exception:
                pass
            rm(*[(OUT / name).with_suffix(ext) for ext in (".mp4", ".json", ".jpg", ".log")],
               UPL / f"{Path(name).stem}_in.png")
            up = Path(str(meta.get("upload") or "")).name
            if up and not any(up in f.read_text(encoding="utf-8", errors="ignore") for f in OUT.glob("*.json")) \
                    and not any(x.get("upload") == up for x in jobs):
                rm(UPL / up)  # delete the original photo only if no other video uses it
            return self.send(200, {"ok": True})
        self.send(404, {"error": msg("not_found")})

    def generate(self, d):
        prompt = str(d.get("prompt", "")).strip()
        if not prompt:
            return self.send(400, {"error": msg("no_prompt")})
        try:
            res, sec, steps = int(d.get("res", 480)), int(d.get("sec", 5)), int(d.get("steps", 4))
            loras_in = [{"id": str(l["id"]), "w": min(2.0, max(0.0, float(l.get("w", 1.0))))}
                        for l in (d.get("loras") or [])]
        except (TypeError, ValueError, KeyError):
            return self.send(400, {"error": msg("bad_settings")})
        if res not in (480, 720) or sec not in (5, 10, 15) or not 1 <= steps <= 50:
            return self.send(400, {"error": msg("bad_settings")})
        aspect = d.get("aspect", "auto")
        if aspect != "auto" and aspect not in ASPECTS:
            return self.send(400, {"error": msg("bad_aspect")})
        # input image: a new upload (data URL) or an existing one (for "Again")
        if str(d.get("image") or "").startswith("data:image"):
            try:
                img = Image.open(io.BytesIO(base64.b64decode(d["image"].split(",", 1)[1])))
                img = ImageOps.exif_transpose(img).convert("RGB")
            except Exception:
                return self.send(400, {"error": msg("bad_image")})
            img.thumbnail((2560, 2560), Image.LANCZOS)   # phone photos can be 50 MP – pointless for 720p
            up = UPL / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
            img.save(up)
        elif d.get("upload"):
            up = UPL / Path(d["upload"]).name
            if not up.exists():
                return self.send(400, {"error": msg("image_gone")})
            img = Image.open(up).convert("RGB")
        else:
            return self.send(400, {"error": msg("no_image")})
        img = crop_aspect(img, aspect)
        seed = d.get("seed")
        seed = str(seed if seed is not None else "").strip()
        if seed and not (seed.isdigit() and int(seed) < 2**32):
            return self.send(400, {"error": msg("bad_seed")})
        seed = int(seed) if seed else None
        pairs = {p["id"]: p for p in lora_pairs()}
        missing = [l["id"] for l in loras_in if l["id"] not in pairs]
        if missing:
            return self.send(400, {"error": msg("lora_gone", name=missing[0])})
        loras = [dict(pairs[l["id"]], w=l["w"]) for l in loras_in]
        jid = uuid.uuid4().hex[:8]
        stem = f"wan_{time.strftime('%Y%m%d_%H%M%S')}_{jid}"
        src = UPL / f"{stem}_in.png"
        w, h = out_size(img, res)
        img.resize((w, h), Image.LANCZOS).save(src)   # already at output size (generate.py keeps it)
        thumb = img.copy()
        thumb.thumbnail((720, 720))
        thumb.save(OUT / f"{stem}.jpg", quality=88)
        j = {"id": jid, "status": "queued", "prompt": prompt, "neg": (d.get("neg") or "").strip() or None,
             "res": res, "sec": sec, "aspect": aspect, "steps": steps, "seed": seed, "loras": loras,
             "image": str(src), "upload": up.name, "out": str(OUT / f"{stem}.mp4"),
             "width": w, "height": h, "progress": 0.0, "phase": msg("ph_queued"), "created": time.time(), "started": None,
             "finished": None, "error": None, "video": None, "poster": f"/output/{stem}.jpg",
             "eta": estimate(w, h, sec, steps, calib(video_list()))}
        with lock:
            jobs.append(j)
        wake.set()
        self.send(200, public(j))


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    class Srv(ThreadingHTTPServer):
        allow_reuse_address = False   # on Windows SO_REUSEADDR would let two servers share a port
        daemon_threads = True

        def server_bind(self):
            import socket
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()
    try:
        srv = Srv(("127.0.0.1", PORT), H)
    except OSError as e:
        print(f"Port {PORT} is used by another program ({e}).", flush=True)
        sys.exit(98)
    print(f"Videogen Studio running at http://127.0.0.1:{PORT}  {'(MOCK – no GPU)' if MOCK else ''}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
