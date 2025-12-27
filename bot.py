#!/usr/bin/env python3
# bot.py — fixed 'never awaited' error

import os
import re
import time
import shutil
import zipfile
import subprocess
import asyncio
import threading
from urllib.parse import unquote, urlparse
from datetime import datetime

import requests
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

# ---------------- USER CONFIG ----------------
API_ID = 31800282
API_HASH = "f7e4ec66e5bf4e87630f0eb0ef620eda"
SESSION_NAME = "my_event_bot"

INPUT_CHANNEL_ID = -1002323337350 
OUTPUT_CHANNEL_ID = -1002004016572 

ROOT = os.path.expanduser("~/bot")
DOWNLOAD_DIR = os.path.join(ROOT, "downloads")
EXTRACT_DIR = os.path.join(ROOT, "extract")
THUMBNAIL_FILE = os.path.join(ROOT, "thumb.jpg")

MAX_UPLOAD_SIZE_GB = 2.0
MAX_DOWNLOAD_TIME = 2700 
ARIA2_RPC_URL = "http://127.0.0.1:6800/jsonrpc"

BRANDING = True
BRANDING_TEXT = "By A2Zmovies"
# ---------------------------------------------

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)
app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)

job_semaphore = asyncio.Semaphore(3)      # controls parallel jobs
upload_semaphore = asyncio.Semaphore(1) 
  # Telegram upload lock
USER_STATE = {}



LANG_MAP = {
    "tam": "Tamil", "tamil": "Tamil",
    "tel": "Telugu", "telugu": "Telugu",
    "hin": "Hindi", "hindi": "Hindi",
    "kan": "Kannada", "kannada": "Kannada",
    "mal": "Malayalam", "malayalam": "Malayalam",
    "eng": "English", "english": "English",
    "spa": "Spanish", "span": "Spanish", "spanish": "Spanish",
    "fra": "French", "fren": "French", "french": "French",
    "jpn": "Japanese", "jap": "Japanese", "japanese": "Japanese",
    "kor": "Korean", "korean": "Korean",
    "chi": "Chinese", "zh": "Chinese", "cn": "Chinese", "chinese": "Chinese",
    "ita": "Italian", "italian": "Italian",
    "ger": "German", "deu": "German", "german": "German",
    "per": "Persian", "farsi": "Persian", "persian": "Persian",
    "urd": "Urdu", "urdu": "Urdu",
    "por": "Portuguese", "pt": "Portuguese",
    "ara": "Arabic", "arabic": "Arabic",
    "tulu": "Tulu", "tlu": "Tulu"
}

TOKEN_BLACKLIST = [
    "www", "1tamilmv", "1tamil", "pink", "yts", "x264", "x265",
    "hdrip", "hq", "esub", "aac", "mp3", "mp4", "mkv",
    "webrip", "web", "web-dl", "webdl", "rip", "bluray",
    "brrip", "bdrip", "2160p", "1080p", "720p", "480p", "br", "utm",
    "moda", "moda.", "a2zmovies"
]
QUALITY_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("2160p", callback_data="q:2160p"),
        InlineKeyboardButton("1080p", callback_data="q:1080p")
    ],
    [
        InlineKeyboardButton("720p", callback_data="q:720p"),
        InlineKeyboardButton("480p", callback_data="q:480p")
    ],
    [
        InlineKeyboardButton("360p", callback_data="q:360p")
    ]
])


def token_looks_like_site(tok: str):
    if not tok: return True
    tl = tok.lower()
    if any(s in tl for s in TOKEN_BLACKLIST): return True
    if '.' in tok: return True
    if tok.isdigit(): return True
    if len(re.sub(r'[^a-zA-Z]','', tok)) == 0: return True
    return False

def lang_to_full(tok: str):
    if not tok: return None
    t = tok.strip()
    if token_looks_like_site(t):
        key_short = re.sub(r'[^a-z0-9]+', '', t.lower())
        if key_short in LANG_MAP: return LANG_MAP[key_short]
        return None
    key = re.sub(r'[^a-z0-9]+', '', t.lower())
    if key in LANG_MAP: return LANG_MAP[key]
    if re.match(r'^[A-Za-z]{3,10}$', t): return t.title()
    return None
def strip_links_and_usernames(text: str) -> str:
    if not text:
        return text

    # Remove URLs (http, https, www)
    text = re.sub(r'https?://\S+', '', text, flags=re.I)
    text = re.sub(r'www\.\S+', '', text, flags=re.I)

    # Remove Telegram usernames (@username)
    text = re.sub(r'@\w+', '', text)

    # Clean extra spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text

def safe_filename(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]+', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 240:
        base, ext = os.path.splitext(name)
        name = base[:220] + ext
    return name

def strip_site_prefix(name: str) -> str:
    if not name: return name
    s = name.strip()
    s = re.sub(r'^(www[._-][^\s]+|[^\s]+\.(com|net|in|xyz|pink|site|tv|cc|me|org|pw|online))[ _-]+', '', s, flags=re.I)
    s = re.sub(r'^[\-_ ]+', '', s)
    return s

def guess_filename_from_url(url: str, default_ext=".mkv") -> str:
    try:
        parsed = urlparse(url)
        last = os.path.basename(parsed.path) or parsed.query or ""
        last = unquote(last.split('?')[0])
        if last and not re.search(r'\.(mkv|mp4|zip|rar|7z|tar|gz)$', last, flags=re.I):
            last = last + default_ext
        return last or ("file" + default_ext)
    except:
        return "file" + default_ext

def looks_like_hash_filename(name: str) -> bool:
    if not name: return False
    base = os.path.splitext(os.path.basename(name))[0]
    base = re.sub(r'\.\d+$', '', base)
    if re.fullmatch(r'[0-9a-fA-F]{20,}', base): return True
    if len(base) >= 24 and len(re.sub(r'[aeiouAEIOU]', '', base)) / max(1, len(base)) > 0.8: return True
    return False

SERIES_REGEXES = [
    re.compile(r'\bS\s*0?(\d{1,3})\s*[\-._ ]?\s*E(?:P|pisode|p)?\s*0?(\d{1,3})\b', re.I),
    re.compile(r'\bS0?(\d{1,3})\s*[xX]\s*0?(\d{1,3})\b', re.I),
    re.compile(r'\b0?(\d{1,3})\s*[xX]\s*0?(\d{1,3})\b', re.I),
    re.compile(r'\bS0?(\d{1,3})EP0?(\d{1,3})\b', re.I),
    re.compile(r'\bS0?(\d{1,3})E0?(\d{1,3})\b', re.I)
]

def detect_series_token_from_text(text: str):
    if not text: return None
    for rx in SERIES_REGEXES:
        m = rx.search(text)
        if m:
            try:
                s = int(m.group(1)); e = int(m.group(2))
                return (s, e, f"S{int(s):02d} E{int(e):02d}")
            except: pass
    return None

def natural_episode_sort_key(path):
    s = detect_series_token_from_text(os.path.basename(path))
    if s:
        season, ep, _ = s
        return (season, ep, os.path.basename(path))
    nums = re.findall(r'(\d+)', os.path.basename(path))
    if nums: return (0, int(nums[0]), os.path.basename(path))
    return (0, 0, os.path.basename(path))

def run_cmd(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return p.stdout + "\n" + p.stderr
    except Exception: return ""

def detect_audio_languages_ffprobe(path):
    if not os.path.exists(path): return []
    out = run_cmd(["ffprobe","-v","error","-select_streams","a","-show_entries","stream_tags=language,title","-of","json", path], timeout=20)
    langs = []
    for m in re.finditer(r'"language"\s*:\s*"([^"]+)"', out, flags=re.I):
        candidate = m.group(1).strip()
        full = lang_to_full(candidate)
        if full and full not in langs: langs.append(full)
    for m in re.finditer(r'"title"\s*:\s*"([^"]+)"', out, flags=re.I):
        t = m.group(1)
        for token in re.split(r'[\s\[\]\(\)\-\+_,/\.]+', t):
            if not token: continue
            if token_looks_like_site(token): continue
            maybe = lang_to_full(token)
            if maybe and maybe not in langs: langs.append(maybe)
    if not langs:
        base = os.path.basename(path)
        for token in re.split(r'[\s\[\]\(\)\-\+_,/\.]+', base):
            if not token: continue
            if token_looks_like_site(token): continue
            maybe = lang_to_full(token)
            if maybe and maybe not in langs: langs.append(maybe)
    return langs

def detect_audio_stream_count_and_langs(path):
    out = run_cmd(["ffprobe","-v","error","-select_streams","a","-show_entries","stream=index:stream_tags=language,title","-of","json", path], timeout=20)
    blocks = re.split(r'\{\s*"index"\s*:', out)
    langs = []
    for b in blocks[1:]:
        lang = None
        m = re.search(r'"language"\s*:\s*"([^"]+)"', b, flags=re.I)
        if m: lang = lang_to_full(m.group(1))
        else:
            m2 = re.search(r'"title"\s*:\s*"([^"]+)"', b, flags=re.I)
            if m2:
                for token in re.split(r'[\s\[\]\(\)\-\+_,/\.]+', m2.group(1)):
                    if token_looks_like_site(token): continue
                    maybe = lang_to_full(token)
                    if maybe:
                        lang = maybe
                        break
        langs.append(lang if lang else None)
    return langs

def detect_subtitle_streams(path):
    out = run_cmd(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream=index:stream_tags=language,title", "-of", "json", path], timeout=20)
    blocks = re.split(r'\{\s*"index"\s*:', out)
    subs = []
    for b in blocks[1:]:
        lang = None
        m = re.search(r'"language"\s*:\s*"([^"]+)"', b, flags=re.I)
        if m: lang = lang_to_full(m.group(1))
        else:
            m2 = re.search(r'"title"\s*:\s*"([^"]+)"', b, flags=re.I)
            if m2:
                for token in re.split(r'[\s\[\]\(\)\-\+_,/\.]+', m2.group(1)):
                    if token_looks_like_site(token): continue
                    maybe = lang_to_full(token)
                    if maybe:
                        lang = maybe
                        break
        subs.append(lang if lang else None)
    return subs

def detect_langs_from_name(name):
    if not name: return []
    langs = []
    for token in re.split(r'[\s\[\]\(\)\-\+_,/\.]+', os.path.basename(name)):
        if not token or token_looks_like_site(token): continue
        maybe = lang_to_full(token)
        if maybe and maybe not in langs: langs.append(maybe)
    return langs

def extract_all_mkvs_from_zip(zip_path):
    out = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            for info in z.infolist():
                if info.filename.lower().endswith('.mkv'):
                    target = os.path.join(EXTRACT_DIR, os.path.basename(info.filename))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with z.open(info) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    out.append(os.path.abspath(target))
    except: return []
    return out

def extract_all_with_7z(path):
    try:
        shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
        os.makedirs(EXTRACT_DIR, exist_ok=True)
        subprocess.run(["7z", "x", "-y", "-o" + EXTRACT_DIR, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        found = []
        for root, _, files in os.walk(EXTRACT_DIR):
            for f in files:
                if f.lower().endswith('.mkv'):
                    found.append(os.path.abspath(os.path.join(root, f)))
        return found
    except: return []

def extract_if_archive(path):
    path = os.path.abspath(path)
    shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    try:
        if zipfile.is_zipfile(path) or path.lower().endswith('.zip'):
            return extract_all_mkvs_from_zip(path)
    except: pass
    return extract_all_with_7z(path)

def build_caption_from_filename(filename: str, detected_langs=None, is_series=False, series_token=None, quality_suffix=""):
    name = (filename or "").strip().strip('"').strip("'")
    name = strip_site_prefix(name)
    base, ext = os.path.splitext(name)
    ext = ext or ".mkv"
    langs = []
    bracket = re.search(r'\[([^\]]+)\]', base)
    if bracket:
        raw = bracket.group(1)
        parts = re.split(r'[\+\,/]', raw)
        for p in parts:
            cand = p.strip()
            if not cand or token_looks_like_site(cand): continue
            full = lang_to_full(cand)
            if full and full not in langs: langs.append(full)
    if not langs and detected_langs:
        for l in detected_langs:
            if l and l not in langs: langs.append(l)
    base_tokens = [t for t in re.split(r'[\s\[\]\(\)\-\+_,/\.]+', base) if t]
    deduped_langs = []
    for L in langs:
        if not L: continue
        L_low = L.lower()
        if any(bt.lower() == L_low for bt in base_tokens): continue
        if L not in deduped_langs: deduped_langs.append(L)
    langs = deduped_langs
    langs_part = " ".join(langs) if langs else ""
    m = re.search(r'^(.*?)\s*(\(?((?:19|20)\d{2})\)?)', base)
    if m:
        title = m.group(1).strip()
        year = m.group(3)
    else:
        parts2 = re.split(r'\b(HQ|HDRip|WEB|WEB[- ]DL|x264|x265|720p|1080p)\b', base, flags=re.IGNORECASE)
        title = parts2[0].strip()
        ym = re.search(r'\b(19|20)\d{2}\b', base)
        year = ym.group(0) if ym else ""
    rest = base
    if title: rest = re.sub(re.escape(title), '', rest, count=1, flags=re.IGNORECASE).strip()
    if year: rest = re.sub(r'\(?'+re.escape(year)+r'\)?', '', rest, count=1).strip()
    rest = re.sub(r'^[\s\-\:\|]+', '', rest).strip()
    title_part = (title + (" " + year if year else "")).strip()
    if langs_part:
        if not any(tok.lower() == lp.lower() for tok in re.split(r'[\s\[\]\(\)\-\+_,/\.]+', title_part) for lp in langs):
            title_part = (title_part + " " + langs_part).strip()
        langs_part = ""
    quality_part = quality_suffix or ""
    if is_series and series_token: parts = [p for p in [title_part, series_token, langs_part, quality_part, rest] if p]
    else: parts = [p for p in [title_part, langs_part, quality_part, rest] if p]
    caption_body = " ".join(parts).strip()
    if not caption_body.lower().endswith(ext.lower()):
        if rest: caption = (caption_body + ext).strip()
        else: caption = (caption_body + " " + os.path.basename(base) + ext).strip()
    else: caption = caption_body
    return re.sub(r'\s+', ' ', caption).strip()

def rpc_call(method, params=None, timeout=6):
    payload = {"jsonrpc": "2.0", "id": "bot", "method": method}
    if params is not None: payload["params"] = params
    try:
        r = requests.post(ARIA2_RPC_URL, json=payload, timeout=timeout)
        return r.json()
    except: return None

def ensure_aria2_rpc_running():
    try:
        r = rpc_call("aria2.getVersion")
        if isinstance(r, dict) and r.get("result"): return True
    except: pass
    try:
        cmd = ["aria2c", "--enable-rpc", "--rpc-listen-all=false", "--rpc-allow-origin-all", "--rpc-listen-port=6800", "--dir", DOWNLOAD_DIR]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(12):
            time.sleep(0.5)
            r = rpc_call("aria2.getVersion")
            if isinstance(r, dict) and r.get("result"): return True
    except: pass
    return False

def human_bytes(n):
    n = float(n or 0)
    if n < 1024**3: return f"{n/1024/1024:.2f} MB"
    return f"{n/1024/1024/1024:.2f} GB"

# --- FIXED: Added missing awaits ---
async def aria2_download_rpc(url: str, out_name: str, status_message, task_dir):
    out_name = safe_filename(out_name)

    # Ensure aria2 RPC is running
    ok = await asyncio.get_event_loop().run_in_executor(
        None, ensure_aria2_rpc_running
    )
    if not ok:
        await safe_edit(status_message, "⚠️ aria2 RPC not available.")
        return None

    # Add download
    add_resp = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: rpc_call(
            "aria2.addUri",
            [[url], {"out": out_name, "dir": task_dir}]
        )
    )

    if not add_resp or "result" not in add_resp:
        await safe_edit(status_message, "⚠️ aria2 addUri failed.")
        return None

    gid = add_resp["result"]

    last_text = None
    last_progress_time = time.time()
    last_done = 0

    STALL_LIMIT = 120          # seconds without progress → cancel
    timeout_deadline = time.time() + MAX_DOWNLOAD_TIME

    while True:
        await asyncio.sleep(0.8)

        st = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: rpc_call(
                "aria2.tellStatus",
                [gid, ["status", "totalLength", "completedLength",
                       "downloadSpeed", "files", "errorMessage"]]
            )
        )

        if not st or "result" not in st:
            continue

        result = st["result"]
        status = result.get("status")

        total = int(result.get("totalLength") or 0)
        done = int(result.get("completedLength") or 0)
        speed = int(result.get("downloadSpeed") or 0)

        now = time.time()

        # ================= PROGRESS =================
        if status in ("active", "waiting"):

            # progress detection
            if done > last_done:
                last_done = done
                last_progress_time = now

            # 🔴 HARD STALL DETECTION
            if now - last_progress_time > STALL_LIMIT:
                await safe_edit(
                    status_message,
                    "❌ Download stalled (aria2 not progressing). Cancelling…"
                )
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: rpc_call("aria2.remove", [gid])
                )
                return None

            # progress text
            sp_s = (
                f"{speed/1024/1024:.2f} MB/s"
                if speed < 1024**3
                else f"{speed/1024/1024/1024:.2f} GB/s"
            )

            if total > 0:
                pct = done * 100 / total
                text = (
                    f"⬇️ Downloading: {pct:.1f}% — "
                    f"{human_bytes(done)}/{human_bytes(total)} — {sp_s}"
                )
            else:
                text = f"⬇️ Downloading: {human_bytes(done)} — {sp_s}"

            if text != last_text:
                last_text = text
                await safe_edit(status_message, text)

        # ================= COMPLETE =================
        elif status == "complete":
            await safe_edit(
                status_message,
                "⬇️ Download complete. Finalizing file..."
            )

            files = result.get("files", [])
            if files and files[0].get("path"):
                path = files[0]["path"]
            else:
                path = os.path.join(task_dir, out_name)

            # 🔴 Wait for file to stop growing
            last_size = -1
            for _ in range(20):
                if not os.path.exists(path):
                    await asyncio.sleep(1)
                    continue

                size = os.path.getsize(path)
                if size == last_size and size > 0:
                    break

                last_size = size
                await asyncio.sleep(1)

            await asyncio.sleep(2)  # extra safety
            return path

        # ================= ERROR =================
        elif status == "error":
            await safe_edit(
                status_message,
                f"❌ aria2 error: {result.get('errorMessage')}"
            )
            return None

        # ================= TIMEOUT =================
        if time.time() > timeout_deadline:
            await safe_edit(status_message, "⚠️ Download timed out.")
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: rpc_call("aria2.remove", [gid])
            )
            return None


def make_telegram_download_progress_editor(status_message):
    last = {
        "time": time.time(),
        "bytes": 0,
        "text": None,
        "stuck_since": time.time(),
        "stalled": False
    }

    STUCK_LIMIT = 90  # seconds

    def progress(current, total):
        try:
            now = time.time()

            if current > last["bytes"]:
                last["bytes"] = current
                last["stuck_since"] = now

            # Mark stalled but DO NOT raise
            if now - last["stuck_since"] > STUCK_LIMIT:
                if not last["stalled"]:
                    last["stalled"] = True
                    app.loop.create_task(
                        safe_edit(status_message, "⚠️ Download stalled — continuing…")
                    )
                return

            if now - last["time"] < 1.5:
                return

            last["time"] = now

            human_cur = human_bytes(current)
            if total and total > 0:
                human_tot = human_bytes(total)
                pct = (current * 100.0 / total)
                text = f"⬇️ Downloading: {pct:.1f}% — {human_cur}/{human_tot}"
            else:
                text = f"⬇️ Downloading: {human_cur}"

            if text != last["text"]:
                last["text"] = text
                app.loop.create_task(safe_edit(status_message, text))

        except:
            pass

    progress._state = last   # attach state to function
    return progress


def make_upload_progress_editor(message):
    """
    SAFE upload progress handler:
    - Stops updates before 100%
    - Prevents semaphore lock
    - Prevents Telegram upload freeze
    """

    state = {
        "last_time": 0,
        "finished": False
    }

    def progress(current, total):
        # If already finalized, do nothing
        if state["finished"]:
            return

        try:
            if not total or total <= 0:
                return

            pct = (current * 100) / total
            now = time.time()

            # 🔴 VERY IMPORTANT: stop updating after ~99%
            if pct >= 99.5:
                state["finished"] = True
                app.loop.create_task(
                    safe_edit(message, "⬆️ Uploading: Finalizing…")
                )
                return

            # Throttle updates
            if now - state["last_time"] < 1.5:
                return

            state["last_time"] = now

            text = (
                f"⬆️ Uploading: {pct:.1f}% — "
                f"{human_bytes(current)}/{human_bytes(total)}"
            )

            app.loop.create_task(safe_edit(message, text))

        except:
            pass

    return progress


async def safe_edit(msg, text):
    try: await msg.edit_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await msg.edit_text(text)
    except: pass

async def safe_reply(message, text):
    try: return await message.reply_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await message.reply_text(text)

def ensure_mkv_copy(src_path):
    base, ext = os.path.splitext(src_path)
    if ext.lower() == ".mkv": return src_path
    out = base + ".mkv"
    try:
        subprocess.run(["ffmpeg","-y","-i",src_path,"-map","0","-c","copy", out + ".tmp"], check=True, timeout=600)
        os.replace(out + ".tmp", out)
        return out
    except: return src_path

def tag_audio_tracks_with_branding(src_mkv, branding_text=BRANDING_TEXT):
    """
    FORCE overwrite audio & subtitle track titles and metadata.
    """
    if not BRANDING or not os.path.exists(src_mkv):
        return src_mkv

    try:
        # Get stream counts
        audio_langs = detect_audio_stream_count_and_langs(src_mkv)
        sub_langs = detect_subtitle_streams(src_mkv)

        meta_args = [
            "-metadata", f"title={branding_text}", # Global title
            "-metadata", "comment=Processed by A2Zmovies"
        ]

        # AUDIO tracks — Apply branding to EACH stream
        for i, lang in enumerate(audio_langs):
            full_title = f"{branding_text} - {lang}" if lang else branding_text
            meta_args += [
                f"-metadata:s:a:{i}", f"title={full_title}",
                f"-metadata:s:a:{i}", f"handler_name={branding_text}",
                f"-disposition:a:{i}", "default" if i == 0 else "0" 
            ]

        # SUBTITLE tracks
        for i, lang in enumerate(sub_langs):
            full_title = f"{branding_text} - {lang}" if lang else branding_text
            meta_args += [
                f"-metadata:s:s:{i}", f"title={full_title}",
                f"-metadata:s:s:{i}", f"handler_name={branding_text}"
            ]

        tmp_out = src_mkv + ".branded.mkv"
        
        # We use -map_metadata -1 to clear old junk, then apply ours
        cmd = [
            "ffmpeg", "-y", "-i", src_mkv,
            "-map", "0", "-c", "copy",
            "-map_metadata", "0", # Keep global metadata but override streams
            *meta_args,
            tmp_out
        ]

        process = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)

        if process.returncode == 0 and os.path.exists(tmp_out):
            # Verify the file size is sane before replacing
            if os.path.getsize(tmp_out) > 1000:
                os.replace(tmp_out, src_mkv)
                return src_mkv
        
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
            
        return src_mkv

    except Exception as e:
        print(f"Branding Error: {e}")
        return src_mkv


def format_series_caption(filename: str, detected_langs, quality_override=None):
    base, ext = os.path.splitext(filename)

    # Replace separators with space
    clean = re.sub(r'[._\-]+', ' ', base)

    # Detect series token
    series = detect_series_token_from_text(clean)
    series_token = series[2] if series else ""

    # Detect quality
    quality = quality_override
    if not quality:
        q = re.search(r'\b(2160p|1080p|720p|480p|360p)\b', clean, re.I)
        quality = q.group(1) if q else ""

    # Detect source like WEB-DL, HDRip, BluRay
    src = ""
    m = re.search(r'\b(WEB\s*DL|WEB\s*RIP|HDRip|BluRay|BRRip)\b', clean, re.I)
    if m:
        src = m.group(1).replace(" ", "-").upper()

    # Remove junk words
    clean = re.sub(
        r'\b(S\d+E\d+|2160p|1080p|720p|480p|360p|WEB\s*DL|WEB\s*RIP|HDRip|BluRay|BRRip)\b',
        '',
        clean,
        flags=re.I
    )

    clean = re.sub(r'\s+', ' ', clean).strip()

    langs = " ".join(detected_langs)

    parts = [
        clean,
        series_token,
        langs,
        quality,
        src
    ]

    return " ".join(p for p in parts if p).strip() + ext


def normalize_filename_spaces(name: str) -> str:
    """
    Convert separators like ., _, -, +, [] {} () into spaces
    and collapse multiple spaces into one.
    """
    if not name:
        return name

    # Remove extension first
    base, ext = os.path.splitext(name)

    # Replace all non-alphanumeric characters with space
    base = re.sub(r'[^A-Za-z0-9]+', ' ', base)

    # Collapse multiple spaces
    base = re.sub(r'\s+', ' ', base).strip()

    return base + ext

async def process_job(client, message):
    # This ensures only 3 jobs run at a time
    async with job_semaphore:
        status = await safe_reply(message, "⏳ Slot acquired — Processing started...")

        try:
            # 1. Detect filename logic
            original_name = None
            if message.document: 
                original_name = message.document.file_name
            elif message.video: 
                original_name = message.video.file_name
            elif message.audio: 
                original_name = message.audio.file_name

            seedr_m = re.search(r'(https?://(?:www\.)?seedr\.cc/download/\S+)', (message.caption or "") + " " + (message.text or ""))
            seedr_link = seedr_m.group(1) if seedr_m else None

            if not original_name and seedr_link: 
                original_name = guess_filename_from_url(seedr_link)
            
            original_name = safe_filename(original_name or "file.mkv")
            
            # Create unique task folder to prevent parallel tasks from overwriting each other
            task_id = f"task_{message.id}"
            TASK_DIR = os.path.join(DOWNLOAD_DIR, task_id)
            os.makedirs(TASK_DIR, exist_ok=True)

            # 2. DOWNLOAD
            final_path = None
            if seedr_link:
                final_path = await aria2_download_rpc(seedr_link, original_name, status, TASK_DIR)
            else:
                # 🔄 ALWAYS refresh message to avoid FILE_REFERENCE_EXPIRED
                fresh_msg = await client.get_messages(
                    chat_id=message.chat.id,
                    message_ids=message.id
                )

                media = fresh_msg.document or fresh_msg.video or fresh_msg.audio

                if not media:
                    await safe_edit(status, "❌ Media expired or unavailable.")
                    return

                final_path = await client.download_media(
                    media,
                    file_name=os.path.join(TASK_DIR, original_name),
                    progress=make_telegram_download_progress_editor(status)
                )

            if not final_path or not os.path.exists(final_path):
                await safe_edit(status, "❌ Download failed.")
                return
            
            # 3. EXTRACT / PROCESS
            extracted = extract_if_archive(final_path)
            files_to_upload = extracted if extracted else [final_path]

            # 4. UPLOAD (Using upload_semaphore to prevent flooding Telegram)
            uid = message.from_user.id
            for path in sorted(files_to_upload, key=natural_episode_sort_key):
                mkv = ensure_mkv_copy(path)
                mkv = tag_audio_tracks_with_branding(mkv)
                clean_name = normalize_filename_spaces(strip_links_and_usernames(os.path.basename(mkv)))
                
                state = USER_STATE.get(uid, {})
                detected_langs = detect_langs_from_name(clean_name)

                # CAPTION LOGIC
                if state.get("mode") == "custom" and state.get("custom_caption"):
                    cap = state["custom_caption"]

                elif state.get("mode") == "series" or detect_series_token_from_text(clean_name):
                    cap = format_series_caption(
                        clean_name,
                        detected_langs,
                        quality_override=state.get("quality")
                    )

                else:
                    cap = build_caption_from_filename(
                        clean_name,
                        detected_langs=detected_langs
                    )

                async with upload_semaphore:
                    try:
                        await client.send_document(
                            OUTPUT_CHANNEL_ID,
                            mkv,
                            caption=cap,
                            thumb=THUMBNAIL_FILE if os.path.exists(THUMBNAIL_FILE) else None,
                            progress=make_upload_progress_editor(status)
                        )
                    except FloodWait as e:
                        wait = int(e.value) + 5
                        print(f"FloodWait: sleeping {wait} seconds")
                        await safe_edit(status, f"⏳ Telegram rate limit — waiting {wait//60} min…")
                        await asyncio.sleep(wait)

                        # retry ONCE after wait
                        await client.send_document(
                            OUTPUT_CHANNEL_ID,
                            mkv,
                            caption=cap,
                            thumb=THUMBNAIL_FILE if os.path.exists(THUMBNAIL_FILE) else None,
                            progress=make_upload_progress_editor(status)
                        )

            await status.delete()
            # Cleanup task folder
            uid=message.from_user.id
            USER_STATE.pop(uid, None)
            shutil.rmtree(TASK_DIR, ignore_errors=True)

        except Exception as e:
            print(f"Job Error: {e}")
            await safe_edit(status, f"❌ Error: {str(e)}")
            # Cleanup state on error if needed
            uid = message.from_user.id
            USER_STATE.pop(uid, None)

@app.on_message(filters.chat(INPUT_CHANNEL_ID) & (filters.document | filters.video | filters.audio | filters.regex(r'(https?://(?:www\.)?seedr\.cc/download/\S+)')))
async def handle_message(client, message):
    # This allows the bot to receive new messages while others are processing
    asyncio.create_task(process_job(client, message))

@app.on_message(filters.command("series"))
async def series_command(client, message):
    uid = message.from_user.id

    USER_STATE[uid] = {
        "mode": "series",
        "quality": None,
        "custom_caption": None
    }

    await message.reply_text(
    "🎬 Series mode enabled.\n\n"
    "1️⃣ Upload the episode file or Seedr link\n"
    "2️⃣ Choose quality below ⬇️",
    reply_markup=QUALITY_KEYBOARD
    )


@app.on_message(filters.command("custom"))
async def custom_command(client, message):
    uid = message.from_user.id

    USER_STATE[uid] = {
        "mode": "custom",
        "quality": None,
        "custom_caption": None
    }

    await message.reply_text(
        "✏️ Custom caption mode enabled.\n\n"
        "Send the caption text first."
    )


@app.on_message(filters.text & ~filters.command(["series", "custom"]))
async def capture_custom_caption(client, message):
    uid = message.from_user.id

    if uid not in USER_STATE:
        return

    state = USER_STATE[uid]

    if state["mode"] == "custom" and not state["custom_caption"]:
        state["custom_caption"] = message.text.strip()

        await message.reply_text(
            "✅ Caption saved.\n\nNow upload the file or Seedr link."
        )

@app.on_callback_query(filters.regex(r"^q:"))
async def quality_selected(client, callback):
    uid = callback.from_user.id

    if uid not in USER_STATE:
        await callback.answer("Session expired", show_alert=True)
        return

    quality = callback.data.split(":")[1]
    USER_STATE[uid]["quality"] = quality

    await callback.message.edit_text(
        f"✅ Quality selected: {quality}\n\nNow uploading…"
    )
    await callback.answer()

from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_health_server():
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()


if __name__ == "__main__":
    print("Starting bot...")
    app.run()
    
