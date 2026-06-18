#!/usr/bin/env python3
"""
DICOM CT ビューアー（Web版）
ブラウザで動作するローカルWebアプリ

起動: python3 dicom_viewer_web.py
"""

import io
import json
import os
import subprocess
import sys
import threading
import webbrowser
from collections import defaultdict, OrderedDict
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

try:
    import pydicom
except ImportError:
    sys.exit("pydicom が必要です: pip3 install pydicom")

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow が必要です: pip3 install Pillow")

PORT = 8765

# ─────────────────────────────────────────────────────────────
# グローバルデータストア
# ─────────────────────────────────────────────────────────────

SERIES   = {}    # uid -> {"desc":str, "files":[path,...], "count":int}
FILE_META = {}   # path -> {uid, desc, instance, slice_loc, ...}

# 画像キャッシュ（HU配列、LRU 80枚まで）
_IMG_CACHE     = OrderedDict()
_IMG_CACHE_MAX = 80


def _hu_array(path):
    if path in _IMG_CACHE:
        _IMG_CACHE.move_to_end(path)
        return _IMG_CACHE[path]
    ds  = pydicom.dcmread(path)
    arr = ds.pixel_array.astype(np.float32)
    arr = arr * float(getattr(ds, 'RescaleSlope', 1.0)) \
             + float(getattr(ds, 'RescaleIntercept', 0.0))
    _IMG_CACHE[path] = arr
    if len(_IMG_CACHE) > _IMG_CACHE_MAX:
        _IMG_CACHE.popitem(last=False)
    return arr


def _apply_wl(arr, ww, wc):
    lo = wc - ww / 2.0
    hi = wc + ww / 2.0
    return ((np.clip(arr, lo, hi) - lo) / (hi - lo) * 255.0).astype(np.uint8)


# ─────────────────────────────────────────────────────────────
# フォルダスキャン
# ─────────────────────────────────────────────────────────────

# DICOMでないことが確実な拡張子（スキャンをスキップ）
_SKIP_EXT = frozenset({
    '.exe', '.dll', '.bat', '.cmd', '.msi', '.sys', '.com',
    '.app', '.dmg', '.pkg', '.mpkg', '.dylib',
    '.pdf', '.txt', '.rtf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.html', '.htm', '.xml', '.css', '.js', '.json',
    '.ico', '.bmp', '.jpg', '.jpeg', '.png', '.gif', '.svg',
    '.ini', '.inf', '.cfg', '.log', '.nfo', '.lnk', '.url',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.cab',
    '.db', '.sqlite', '.mdb', '.accdb',
    '.mp4', '.avi', '.mov', '.wmv', '.mpg', '.mpeg',
    '.mp3', '.wav', '.aac',
    '.ttf', '.otf', '.woff', '.woff2',
    '.py', '.java', '.class', '.jar', '.sh',
})

# スキップするフォルダ名（ビューワーソフト・説明書など）
_SKIP_DIRS = frozenset({
    'autorun', 'viewer', 'software', '__macosx', '.ds_store', 'dicomdir',
    'windows', 'win', 'win32', 'win64', 'mac', 'linux', 'unix',
    'program', 'programs', 'install', 'installer', 'setup',
    'readme', 'manual', 'manuals', 'docs', 'document', 'documents', 'help',
    'license', 'licences', 'licenses',
})


def _likely_dicom(path):
    """拡張子とDICOMマジックバイトで高速判定"""
    ext = os.path.splitext(path)[1].lower()
    if ext in _SKIP_EXT:
        return False
    try:
        with open(path, 'rb') as f:
            f.seek(128)
            if f.read(4) == b'DICM':
                return True
        # preambleなし旧形式DICOMは拡張子なし・.dcm・.ima に限定して試す
        if ext in ('', '.dcm', '.ima', '.dicom'):
            return True
        return False
    except Exception:
        return False


def scan_folder(folder):
    global SERIES, FILE_META
    SERIES    = {}
    FILE_META = {}
    _IMG_CACHE.clear()

    series_dict = defaultdict(list)

    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs
                   if d.lower() not in _SKIP_DIRS and not d.startswith('.')]
        for fn in files:
            if fn.startswith('.'):
                continue
            path = os.path.join(root, fn)
            if not _likely_dicom(path):
                continue
            try:
                ds  = pydicom.dcmread(path, stop_before_pixels=True)
                uid = str(ds.get('SeriesInstanceUID', ''))
                if not uid:
                    continue
                meta = {
                    'uid':          uid,
                    'desc':         str(ds.get('SeriesDescription', '')),
                    'instance':     int(ds.get('InstanceNumber', 0)),
                    'slice_loc':    float(ds.get('SliceLocation', 0)),
                    'patient_name': str(ds.get('PatientName', '')),
                    'study_date':   str(ds.get('StudyDate', '')),
                    'modality':     str(ds.get('Modality', '')),
                    'ww':           int(ds.get('WindowWidth', 400)),
                    'wc':           int(ds.get('WindowCenter', 40)),
                }
                FILE_META[path] = meta
                series_dict[uid].append(
                    (meta['slice_loc'], meta['instance'], path))
            except Exception:
                pass

    for uid, items in series_dict.items():
        items.sort(key=lambda x: (x[0], x[1]))
        paths = [p for _, _, p in items]
        desc  = FILE_META[paths[0]]['desc'] if paths else ''
        SERIES[uid] = {'desc': desc, 'files': paths, 'count': len(paths)}

    result = [{'uid': uid, 'desc': v['desc'], 'count': v['count']}
              for uid, v in SERIES.items()]
    result.sort(key=lambda x: x['desc'])
    return result


# ─────────────────────────────────────────────────────────────
# 画像レンダリング
# ─────────────────────────────────────────────────────────────

def render_png_bytes(uid, index, ww, wc):
    path = SERIES[uid]['files'][index]
    arr  = _hu_array(path)
    img  = Image.fromarray(_apply_wl(arr, ww, wc), mode='L')
    buf  = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def render_export_bytes(pinned_list, ww, wc):
    """4枚合成画像を生成して PNG bytes を返す"""
    PS  = 600
    GAP = 6
    W   = PS * 2 + GAP * 3
    H   = PS * 2 + GAP * 3 + 34

    comp = Image.new('RGB', (W, H), (14, 14, 14))
    draw = ImageDraw.Draw(comp)
    patient_info = ''

    for i, item in enumerate(pinned_list):
        row, col = divmod(i, 2)
        x = GAP + col * (PS + GAP)
        y = GAP + row * (PS + GAP)
        draw.rectangle([x - 1, y - 1, x + PS, y + PS], outline=(50, 50, 50))

        if not item:
            draw.text((x + PS // 2, y + PS // 2),
                      f"パネル {i+1}\n（空）",
                      fill=(50, 50, 50), anchor='mm')
            continue

        uid   = item.get('uid')
        index = item.get('index', 0)
        if uid not in SERIES or index >= len(SERIES[uid]['files']):
            continue

        path = SERIES[uid]['files'][index]
        try:
            arr = _hu_array(path)
            pil = Image.fromarray(_apply_wl(arr, ww, wc), mode='L').convert('RGB')

            iw, ih = pil.size
            ratio  = min(PS / iw, PS / ih)
            nw, nh = max(1, int(iw * ratio)), max(1, int(ih * ratio))
            pil    = pil.resize((nw, nh), Image.LANCZOS)

            comp.paste(pil, (x + (PS - nw) // 2, y + (PS - nh) // 2))

            meta  = FILE_META.get(path, {})
            loc   = f"  {float(meta.get('slice_loc', 0)):.1f}mm"
            desc  = SERIES[uid]['desc']
            draw.text((x + 4, y + 4),
                      f"{desc}\nNo.{index+1}/{SERIES[uid]['count']}{loc}",
                      fill=(255, 255, 0))

            if not patient_info and meta.get('patient_name'):
                date = meta.get('study_date', '')
                if len(date) == 8:
                    date = f"{date[:4]}/{date[4:6]}/{date[6:]}"
                patient_info = f"患者: {meta['patient_name']}  撮影日: {date}"
        except Exception as e:
            draw.text((x + PS // 2, y + PS // 2),
                      f"エラー\n{e}", fill=(255, 60, 60), anchor='mm')

    iy = H - 30
    draw.rectangle([0, iy, W, H], fill=(25, 25, 25))
    draw.text((GAP, iy + 6),
              f"{patient_info}   W:{ww}  C:{wc}   【電子カルテ貼り付け用】",
              fill=(160, 160, 160))

    buf = io.BytesIO()
    comp.save(buf, format='PNG', dpi=(150, 150))
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# macOS ネイティブフォルダ選択
# ─────────────────────────────────────────────────────────────

def pick_folder_macos():
    """osascript でネイティブフォルダ選択ダイアログを表示"""
    try:
        r = subprocess.run(
            ['osascript', '-e', 'POSIX path of (choose folder)'],
            capture_output=True, text=True, timeout=60
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# HTTP ハンドラー
# ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, *_):
        pass  # アクセスログ抑制

    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)

        def q(k, default=None):
            v = qs.get(k, [default])
            return v[0] if v else default

        p = parsed.path

        if p == '/':
            html = VIEWER_HTML.encode('utf-8')
            self._send(200, 'text/html; charset=utf-8', html)

        elif p == '/api/pick-folder':
            folder = pick_folder_macos()
            if folder:
                self._send_json({'folder': folder})
            else:
                self._send_json({'folder': None, 'error': 'キャンセルされました'})

        elif p == '/api/image':
            uid   = q('uid')
            index = int(q('index', '0'))
            ww    = int(q('ww', '400'))
            wc    = int(q('wc', '40'))
            if not uid or uid not in SERIES or index >= len(SERIES[uid]['files']):
                self._send(404, 'text/plain', b'Not found')
                return
            try:
                data = render_png_bytes(uid, index, ww, wc)
                self._send(200, 'image/png', data,
                           extra=[('Cache-Control', 'no-cache')])
            except Exception as e:
                self._send(500, 'text/plain', str(e).encode())

        elif p == '/api/series':
            result = [{'uid': uid, 'desc': v['desc'], 'count': v['count']}
                      for uid, v in SERIES.items()]
            result.sort(key=lambda x: x['desc'])
            self._send_json(result)

        elif p == '/api/metadata':
            uid   = q('uid')
            index = int(q('index', '0'))
            if not uid or uid not in SERIES or index >= len(SERIES[uid]['files']):
                self._send(404, 'text/plain', b'Not found')
                return
            path = SERIES[uid]['files'][index]
            meta = dict(FILE_META.get(path, {}))
            meta['desc'] = SERIES[uid]['desc']
            self._send_json(meta)

        elif p == '/api/export':
            ww           = int(q('ww', '400'))
            wc           = int(q('wc', '40'))
            pinned_json  = q('pinned', '[]')
            pinned_list  = json.loads(pinned_json)
            try:
                data = render_export_bytes(pinned_list, ww, wc)
                self._send(200, 'image/png', data,
                           extra=[('Content-Disposition',
                                   'attachment; filename="CT比較4枚.png"')])
            except Exception as e:
                self._send(500, 'text/plain', str(e).encode())

        else:
            self._send(404, 'text/plain', b'Not found')

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/scan':
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            try:
                data   = json.loads(body)
                folder = data.get('folder', '')
                if not os.path.isdir(folder):
                    self._send(400, 'text/plain', b'Invalid folder')
                    return
                result = scan_folder(folder)
                self._send_json(result)
            except Exception as e:
                self._send(500, 'text/plain', str(e).encode())
        else:
            self._send(404, 'text/plain', b'Not found')

    def _send(self, code, ctype, data, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(data))
        if extra:
            for k, v in extra:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self._send(200, 'application/json', data)


# ─────────────────────────────────────────────────────────────
# HTML / CSS / JavaScript（埋め込み）
# ─────────────────────────────────────────────────────────────

VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>DICOM CT ビューアー</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;
  background:#0d0d0d;color:#ddd;height:100vh;
  display:flex;flex-direction:column;overflow:hidden;
  user-select:none;
}

/* ── ツールバー ── */
#toolbar{
  background:#191919;border-bottom:1px solid #2f2f2f;
  padding:5px 10px;display:flex;align-items:center;
  gap:5px;flex-shrink:0;flex-wrap:wrap;
}
#toolbar label{color:#999;font-size:11px;margin-right:1px}
input[type=number]{
  background:#252525;border:1px solid #3a3a3a;color:#fff;
  padding:3px 5px;border-radius:4px;width:66px;font-size:12px;
}
.btn{
  background:#2e2e2e;color:#ccc;border:1px solid #484848;
  border-radius:5px;padding:3px 9px;font-size:11px;cursor:pointer;
}
.btn:hover{background:#3a3a3a}
.btn.primary{background:#0a84ff;border-color:#0a84ff;color:#fff}
.btn.primary:hover{background:#2a94ff}
.sep{width:1px;background:#3a3a3a;height:22px;margin:0 4px}

/* ── レイアウト ── */
#main{display:flex;flex:1;overflow:hidden}

/* ── サイドバー ── */
#sidebar{
  width:210px;background:#141414;
  border-right:1px solid #2a2a2a;
  display:flex;flex-direction:column;flex-shrink:0;
}
#sidebar h3{
  padding:8px 12px;font-size:11px;color:#777;
  text-transform:uppercase;letter-spacing:.5px;
  border-bottom:1px solid #222;
}
#open-btn{
  margin:8px;padding:8px 6px;background:#0a84ff;color:#fff;
  border:none;border-radius:6px;cursor:pointer;font-size:13px;
}
#open-btn:hover{background:#2a94ff}
#series-list{flex:1;overflow-y:auto;padding:3px 0}
.si{
  padding:7px 12px;cursor:pointer;font-size:11px;
  border-left:3px solid transparent;line-height:1.5;
}
.si:hover{background:#1e1e1e}
.si.active{background:#162030;border-left-color:#0a84ff;color:#fff}
.si .cnt{color:#555;font-size:10px}
#load-info{padding:6px 12px;font-size:10px;color:#555;border-top:1px solid #222}

/* ── コンテンツ ── */
#content{flex:1;display:flex;flex-direction:column;overflow:hidden}

/* ── タブ ── */
#tabs{display:flex;background:#161616;border-bottom:1px solid #2a2a2a}
.tab{padding:7px 18px;cursor:pointer;font-size:12px;color:#777;
     border-bottom:2px solid transparent}
.tab.active{color:#0a84ff;border-bottom-color:#0a84ff}
.tc{display:none;flex:1;flex-direction:column;overflow:hidden}
.tc.active{display:flex}

/* ── シングルビュー ── */
#viewer-area{
  flex:1;position:relative;overflow:hidden;
  background:#000;cursor:crosshair;
}
#viewer-canvas{
  display:block;position:absolute;
  top:0;left:0;width:100%;height:100%;
}
#overlay{
  position:absolute;top:0;left:0;right:0;bottom:0;
  pointer-events:none;
}
.ov{
  position:absolute;color:#ff0;font-size:10px;
  line-height:1.6;text-shadow:1px 1px 2px #000;
  font-family:monospace;white-space:pre;
}
.tl{top:7px;left:7px}
.tr{top:7px;right:7px;text-align:right}
.bl{bottom:7px;left:7px}
.br{bottom:7px;right:7px;text-align:right}

#controls-bar{
  background:#141414;padding:5px 10px;
  display:flex;align-items:center;gap:8px;
  border-top:1px solid #222;flex-shrink:0;
}
#slice-info{font-size:11px;color:#777;min-width:90px}
#slice-slider{flex:1;accent-color:#0a84ff;cursor:pointer}
#pin-bar{
  background:#111;padding:5px 10px;
  display:flex;align-items:center;gap:5px;
  border-top:1px solid #1e1e1e;flex-shrink:0;
}
#pin-bar>span{font-size:11px;color:#555;margin-right:3px}

/* ── 4パネル ── */
#quad-grid{
  display:grid;grid-template-columns:1fr 1fr;
  grid-template-rows:1fr 1fr;gap:2px;
  background:#2a2a2a;flex:1;overflow:hidden;
}
.panel{background:#000;display:flex;flex-direction:column;overflow:hidden}
.ph{
  background:#1c1c1c;padding:3px 7px;font-size:10px;
  color:#777;display:flex;align-items:center;
  justify-content:space-between;flex-shrink:0;
}
.ph.hi{color:#ddd}
.cb{background:none;border:none;color:#555;cursor:pointer;font-size:13px;padding:0 3px}
.cb:hover{color:#f44}
.pw{flex:1;position:relative;overflow:hidden}
.pw img{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain}
.placeholder{
  position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);
  text-align:center;color:#2e2e2e;font-size:12px;line-height:2;
}
.pov{
  position:absolute;top:3px;left:3px;
  color:#ff0;font-size:9px;line-height:1.5;
  text-shadow:1px 1px 2px #000;pointer-events:none;
  font-family:monospace;white-space:pre;
}
#export-bar{
  background:#141414;padding:8px 14px;
  display:flex;align-items:center;gap:12px;
  border-top:1px solid #2a2a2a;flex-shrink:0;
}
#export-bar small{color:#555;font-size:10px}

/* ── ステータス ── */
#statusbar{
  background:#161616;border-top:1px solid #2a2a2a;
  padding:3px 10px;font-size:10px;color:#555;
  display:flex;justify-content:space-between;flex-shrink:0;
}

/* ── ローディング ── */
#loading{
  display:none;position:fixed;inset:0;
  background:rgba(0,0,0,.75);z-index:200;
  align-items:center;justify-content:center;flex-direction:column;gap:12px;
}
#loading.show{display:flex}
.spin{
  width:36px;height:36px;border:4px solid #333;
  border-top-color:#0a84ff;border-radius:50%;
  animation:rot .7s linear infinite;
}
@keyframes rot{to{transform:rotate(360deg)}}
#loading p{color:#aaa;font-size:13px}

::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:#111}
::-webkit-scrollbar-thumb{background:#3a3a3a;border-radius:3px}
</style>
</head>
<body>

<div id="loading"><div class="spin"></div><p id="load-msg">読み込み中...</p></div>

<!-- ツールバー -->
<div id="toolbar">
  <label>W:</label><input type="number" id="ww" value="400" min="1" max="10000">
  <label>&nbsp;C:</label><input type="number" id="wc" value="40" min="-10000" max="10000">
  <div class="sep"></div>
  <span style="font-size:10px;color:#666">プリセット:</span>
  <button class="btn" onclick="preset(400,40)">軟部組織</button>
  <button class="btn" onclick="preset(1500,300)">骨</button>
  <button class="btn" onclick="preset(1500,-600)">肺</button>
  <button class="btn" onclick="preset(80,40)">脳</button>
  <button class="btn" onclick="preset(350,40)">腹部</button>
  <div class="sep"></div>
  <span style="font-size:10px;color:#666">ズーム:</span>
  <button class="btn" onclick="dz(-0.2)">－</button>
  <span id="zd" style="font-size:11px;min-width:38px;text-align:center">100%</span>
  <button class="btn" onclick="dz(0.2)">＋</button>
  <button class="btn" onclick="resetView()">リセット</button>
  <div class="sep"></div>
  <button class="btn" onclick="showShortcuts()" style="font-size:10px">操作ガイド ？</button>
</div>

<!-- メイン -->
<div id="main">

  <!-- サイドバー -->
  <div id="sidebar">
    <h3>シリーズ一覧</h3>
    <button id="open-btn" onclick="openFolder()">📁 フォルダ / CD を開く</button>
    <div id="series-list">
      <div style="padding:14px 12px;color:#444;font-size:11px;line-height:2">
        「フォルダ / CD を開く」ボタンを押してDICOMデータのフォルダを選択してください
      </div>
    </div>
    <div id="load-info"></div>
  </div>

  <!-- コンテンツ -->
  <div id="content">
    <div id="tabs">
      <div class="tab active" onclick="switchTab('single')">シングルビュー</div>
      <div class="tab" onclick="switchTab('quad')">4枚比較・エクスポート</div>
    </div>

    <!-- シングルビュー -->
    <div id="tc-single" class="tc active">
      <div id="viewer-area" onmousedown="startDrag(event)"
           onmousemove="onMove(event)" oncontextmenu="return false">
        <canvas id="viewer-canvas"></canvas>
        <div id="overlay">
          <div class="ov tl" id="ov-tl"></div>
          <div class="ov tr" id="ov-tr"></div>
          <div class="ov bl" id="ov-bl"></div>
          <div class="ov br" id="ov-br"></div>
        </div>
      </div>
      <div id="controls-bar">
        <span id="slice-info">スライス: — / —</span>
        <input type="range" id="slice-slider" min="0" max="1" value="0"
               oninput="onSlider(+this.value)">
      </div>
      <div id="pin-bar">
        <button id="pin-btn" class="btn primary" onclick="pinNext()">📌 この画像を記録（0 / 4）</button>
        <button class="btn" onclick="clearAllPins()" style="margin-left:4px">クリア</button>
        <span style="margin-left:10px;font-size:10px;color:#555">
          見たいスライスで「記録」を押してください。4枚になったら自動でまとめ画像を作成します。
        </span>
      </div>
    </div>

    <!-- 4枚比較 -->
    <div id="tc-quad" class="tc">
      <div id="quad-grid">
        <!-- パネル 0〜3 は JS で生成 -->
      </div>
      <div id="export-bar">
        <button class="btn primary" onclick="doExport()"
                style="padding:7px 16px;font-size:12px">
          📷 4枚を1枚の画像にまとめてダウンロード（電子カルテ用）
        </button>
        <small>パネルをダブルクリック → シングルビューで拡大表示</small>
      </div>
    </div>
  </div>
</div>

<div id="statusbar">
  <span id="status">フォルダまたは CD を開いてください</span>
  <span><span id="hu">HU: —</span>&nbsp;&nbsp;<span id="xy"></span></span>
</div>

<script>
// ══════════════════════════════════════════════
// 状態
// ══════════════════════════════════════════════
let series=[],curUID=null,curIdx=0,curCount=0;
let zoom=1,panX=0,panY=0;
let pinned=[null,null,null,null];
let _lastImg=null,_dx=0,_dy=0,_sw=0,_sh=0;
let dragging=false,dragBtn=0,dsx=0,dsy=0,dpx=0,dpy=0,dww=400,dwc=40;

// ══════════════════════════════════════════════
// パネル生成
// ══════════════════════════════════════════════
(function buildPanels(){
  const g=document.getElementById('quad-grid');
  g.innerHTML='';
  for(let i=0;i<4;i++){
    g.innerHTML+=`
    <div class="panel">
      <div class="ph" id="ph${i}">
        <span id="ph-label${i}">パネル ${i+1}（空）</span>
        <button class="cb" onclick="clearPanel(${i})">×</button>
      </div>
      <div class="pw" id="pw${i}" ondblclick="focusPanel(${i})">
        <div class="placeholder" id="pp${i}">パネル ${i+1}<br>
          <small style="color:#2a2a2a">シングルビューで「記録」を押して追加</small>
        </div>
      </div>
    </div>`;
  }
})();

// ══════════════════════════════════════════════
// フォルダを開く
// ══════════════════════════════════════════════
async function openFolder(){
  showLoad('フォルダを選択してください...');
  try{
    // macOS ネイティブダイアログ
    const r=await fetch('/api/pick-folder');
    const d=await r.json();
    if(!d.folder){ hideLoad(); return; }
    await scanFolder(d.folder);
  }catch(e){
    // フォールバック: 手動入力
    hideLoad();
    const folder=prompt('DICOMフォルダのパスを入力してください\n例: /Volumes/CDROM  または  /Users/yourname/CT_Data');
    if(folder) await scanFolder(folder);
  }
}

async function scanFolder(folder){
  showLoad('DICOMファイルをスキャン中...');
  try{
    const r=await fetch('/api/scan',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({folder})
    });
    series=await r.json();
    renderSidebar();
    status(`${series.length} シリーズを読み込みました`);
    if(series.length>0) selectSeries(series[0].uid);
  }catch(e){
    status('エラー: '+e.message);
  }finally{
    hideLoad();
  }
}

// ══════════════════════════════════════════════
// サイドバー
// ══════════════════════════════════════════════
function renderSidebar(){
  const el=document.getElementById('series-list');
  if(!series.length){
    el.innerHTML='<div style="padding:12px;color:#444;font-size:11px">DICOMファイルが見つかりません</div>';
    return;
  }
  el.innerHTML=series.map(s=>`
    <div class="si${s.uid===curUID?' active':''}" onclick="selectSeries('${s.uid}')" data-uid="${s.uid}">
      <div>${s.desc||'（名称なし）'}</div>
      <div class="cnt">${s.count} 枚</div>
    </div>`).join('');
  const total=series.reduce((a,s)=>a+s.count,0);
  document.getElementById('load-info').textContent=
    `${series.length} シリーズ  /  計 ${total} 枚`;
}

// ══════════════════════════════════════════════
// シリーズ選択
// ══════════════════════════════════════════════
function selectSeries(uid){
  curUID=uid; curIdx=0;
  _pc.clear();
  const s=series.find(x=>x.uid===uid);
  if(!s)return;
  curCount=s.count;
  document.querySelectorAll('.si').forEach(el=>{
    el.classList.toggle('active',el.dataset.uid===uid);
  });
  const sl=document.getElementById('slice-slider');
  sl.max=curCount-1; sl.value=0;
  zoom=1;panX=0;panY=0;
  loadImg();
}

// ══════════════════════════════════════════════
// 画像描画（白フラッシュ防止 + プリフェッチ）
// ══════════════════════════════════════════════
const _pc=new Map();
let _reqId=0;

async function loadImg(){
  if(!curUID)return;
  const myId=++_reqId;
  const ww=+document.getElementById('ww').value;
  const wc=+document.getElementById('wc').value;

  // キャッシュチェック → なければフェッチ（キャンバスはまだ触らない）
  const cKey=`${curUID}:${curIdx}:${ww}:${wc}`;
  let img=_pc.get(cKey);
  if(!img||!img.complete||!img.naturalWidth){
    img=new Image();
    try{
      await new Promise((ok,ng)=>{
        img.onload=ok; img.onerror=ng;
        img.src=`/api/image?uid=${encodeURIComponent(curUID)}&index=${curIdx}&ww=${ww}&wc=${wc}`;
      });
    }catch{ return; }
    _pc.set(cKey,img);
    if(_pc.size>12) _pc.delete(_pc.keys().next().value);
  }
  if(myId!==_reqId)return;

  // 画像取得後にキャンバスを更新（白フラッシュ防止）
  const canvas=document.getElementById('viewer-canvas');
  const area=document.getElementById('viewer-area');
  const aw=area.clientWidth, ah=area.clientHeight;
  if(canvas.width!==aw) canvas.width=aw;
  if(canvas.height!==ah) canvas.height=ah;
  const ctx=canvas.getContext('2d');

  const sw=img.naturalWidth*zoom, sh=img.naturalHeight*zoom;
  const dx=aw/2-sw/2+panX, dy=ah/2-sh/2+panY;
  ctx.clearRect(0,0,aw,ah);
  ctx.drawImage(img,dx,dy,sw,sh);
  _lastImg=img; _dx=dx; _dy=dy; _sw=sw; _sh=sh;

  document.getElementById('slice-info').textContent=`スライス: ${curIdx+1} / ${curCount}`;
  document.getElementById('zd').textContent=Math.round(zoom*100)+'%';

  loadOverlay(ww,wc);

  // 前後スライスをプリフェッチ（次の切り替えを速く）
  _prefetch(curIdx-1,ww,wc);
  _prefetch(curIdx+1,ww,wc);
}

function _prefetch(idx,ww,wc){
  if(!curUID||idx<0||idx>=curCount)return;
  const k=`${curUID}:${idx}:${ww}:${wc}`;
  if(_pc.has(k))return;
  const i=new Image();
  i.src=`/api/image?uid=${encodeURIComponent(curUID)}&index=${idx}&ww=${ww}&wc=${wc}`;
  _pc.set(k,i);
  if(_pc.size>12)_pc.delete(_pc.keys().next().value);
}

function loadOverlay(ww,wc){
  fetch(`/api/metadata?uid=${encodeURIComponent(curUID)}&index=${curIdx}`)
    .then(r=>r.json()).then(m=>{
      let date=m.study_date||'';
      if(date.length===8) date=`${date.slice(0,4)}/${date.slice(4,6)}/${date.slice(6)}`;
      const loc=m.slice_loc!=null?`位置: ${(+m.slice_loc).toFixed(1)} mm`:'';
      document.getElementById('ov-tl').textContent=`${m.patient_name||''}\n${date}`;
      document.getElementById('ov-tr').textContent=`W:${ww}  C:${wc}`;
      document.getElementById('ov-bl').textContent=`No.${curIdx+1}  ${loc}`;
      document.getElementById('ov-br').textContent=m.desc||'';
    }).catch(()=>{});
}

// ══════════════════════════════════════════════
// スクロール
// ══════════════════════════════════════════════
function scroll(d){
  curIdx=Math.max(0,Math.min(curIdx+d,curCount-1));
  document.getElementById('slice-slider').value=curIdx;
  loadImg();
}
function onSlider(v){if(v!==curIdx){curIdx=v;loadImg();}}

document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT')return;
  ({
    ArrowUp:()=>scroll(-1),ArrowLeft:()=>scroll(-1),
    ArrowDown:()=>scroll(1),ArrowRight:()=>scroll(1),
    PageUp:()=>scroll(-10),PageDown:()=>scroll(10),
    Home:()=>{curIdx=0;document.getElementById('slice-slider').value=0;loadImg();},
    End:()=>{curIdx=curCount-1;document.getElementById('slice-slider').value=curIdx;loadImg();},
  })[e.key]?.();
  if(['+','='].includes(e.key)) dz(0.2);
  if(e.key==='-') dz(-0.2);
  if(e.key==='0') resetView();
});

document.getElementById('viewer-area').addEventListener('wheel',e=>{
  e.preventDefault();
  if(e.ctrlKey||e.metaKey) dz(e.deltaY<0?0.15:-0.15);
  else scroll(e.deltaY>0?1:-1);
},{passive:false});

// ══════════════════════════════════════════════
// パン & W/L ドラッグ
// ══════════════════════════════════════════════
function startDrag(e){
  dragging=true;dragBtn=e.button;
  dsx=e.clientX;dsy=e.clientY;
  dpx=panX;dpy=panY;
  dww=+document.getElementById('ww').value;
  dwc=+document.getElementById('wc').value;
  function mv(ev){
    if(!dragging)return;
    const dx=ev.clientX-dsx,dy=ev.clientY-dsy;
    if(dragBtn===0){panX=dpx+dx;panY=dpy+dy;loadImg();}
    else{
      document.getElementById('ww').value=Math.max(1,Math.round(dww+dx*5));
      document.getElementById('wc').value=Math.round(dwc-dy*5);
      loadImg();
    }
  }
  function up(){dragging=false;window.removeEventListener('mousemove',mv);window.removeEventListener('mouseup',up);}
  window.addEventListener('mousemove',mv);
  window.addEventListener('mouseup',up);
}

function onMove(e){
  if(!_lastImg||!curUID)return;
  const rect=document.getElementById('viewer-area').getBoundingClientRect();
  const mx=e.clientX-rect.left,my=e.clientY-rect.top;
  // HU: 元画像座標へ変換
  const ix=Math.round((mx-_dx)*_lastImg.naturalWidth/_sw);
  const iy=Math.round((my-_dy)*_lastImg.naturalHeight/_sh);
  document.getElementById('xy').textContent=`(${ix}, ${iy})`;
}

// ══════════════════════════════════════════════
// ズーム
// ══════════════════════════════════════════════
function dz(d){zoom=Math.max(0.05,Math.min(zoom+d,12));document.getElementById('zd').textContent=Math.round(zoom*100)+'%';loadImg();}
function resetView(){zoom=1;panX=0;panY=0;document.getElementById('zd').textContent='100%';loadImg();}

// ══════════════════════════════════════════════
// プリセット
// ══════════════════════════════════════════════
function preset(ww,wc){_pc.clear();document.getElementById('ww').value=ww;document.getElementById('wc').value=wc;loadImg();}
document.getElementById('ww').addEventListener('change',()=>{_pc.clear();loadImg();});
document.getElementById('wc').addEventListener('change',()=>{_pc.clear();loadImg();});

// ══════════════════════════════════════════════
// タブ
// ══════════════════════════════════════════════
function switchTab(t){
  document.querySelectorAll('.tab').forEach((el,i)=>el.classList.toggle('active',(i===0)===(t==='single')));
  document.getElementById('tc-single').classList.toggle('active',t==='single');
  document.getElementById('tc-quad').classList.toggle('active',t==='quad');
  if(t==='quad') refreshAllPanels();
}

// ══════════════════════════════════════════════
// 4パネル（1ボタン操作）
// ══════════════════════════════════════════════
function pinNext(){
  if(!curUID){alert('シリーズが選択されていません');return;}
  const filled=pinned.filter(p=>p).length;
  if(filled>=4){
    if(confirm('4枚すでに記録されています。\nリセットして最初からやり直しますか？')){
      clearAllPins();
    }
    return;
  }
  const slot=pinned.findIndex(p=>!p);
  pinned[slot]={uid:curUID,index:curIdx};
  updatePinBtn();
  const newFilled=pinned.filter(p=>p).length;
  status(`${newFilled} / 4 枚を記録しました`);
  if(newFilled===4){
    refreshAllPanels();
    switchTab('quad');
    setTimeout(()=>doExport(),500);
  }
}

function clearAllPins(){
  pinned=[null,null,null,null];
  for(let i=0;i<4;i++)clearPanel(i);
  updatePinBtn();
  status('比較記録をリセットしました');
}

function updatePinBtn(){
  const btn=document.getElementById('pin-btn');
  if(!btn)return;
  const n=pinned.filter(p=>p).length;
  btn.textContent=n<4?`📌 この画像を記録（${n} / 4）`:`✅ 4枚記録済み`;
}

function clearPanel(i){
  pinned[i]=null;
  document.getElementById(`ph${i}`).classList.remove('hi');
  document.getElementById(`ph-label${i}`).textContent=`パネル ${i+1}（空）`;
  document.getElementById(`pw${i}`).innerHTML=
    `<div class="placeholder" id="pp${i}">パネル ${i+1}<br>
      <small style="color:#2a2a2a">シングルビューで「記録」を押して追加</small></div>`;
  updatePinBtn();
}

function focusPanel(i){
  if(!pinned[i])return;
  curUID=pinned[i].uid;curIdx=pinned[i].index;
  const s=series.find(x=>x.uid===curUID);
  if(s)curCount=s.count;
  document.getElementById('slice-slider').max=curCount-1;
  document.getElementById('slice-slider').value=curIdx;
  document.querySelectorAll('.si').forEach(el=>el.classList.toggle('active',el.dataset.uid===curUID));
  zoom=1;panX=0;panY=0;
  switchTab('single');loadImg();
}

function refreshPanel(i){
  if(!pinned[i])return;
  const {uid,index}=pinned[i];
  const ww=+document.getElementById('ww').value;
  const wc=+document.getElementById('wc').value;
  const s=series.find(x=>x.uid===uid);
  const pw=document.getElementById(`pw${i}`);
  pw.innerHTML='';
  const img=document.createElement('img');
  img.src=`/api/image?uid=${encodeURIComponent(uid)}&index=${index}&ww=${ww}&wc=${wc}`;
  const ov=document.createElement('div'); ov.className='pov';
  fetch(`/api/metadata?uid=${encodeURIComponent(uid)}&index=${index}`)
    .then(r=>r.json()).then(m=>{
      const loc=m.slice_loc!=null?` ${(+m.slice_loc).toFixed(1)}mm`:'';
      ov.textContent=`${m.desc||s?.desc||''}\nNo.${index+1}/${s?.count||'?'}${loc}`;
      document.getElementById(`ph-label${i}`).textContent=
        `パネル ${i+1}: ${s?.desc||''}  [${index+1}/${s?.count||'?'}]`;
      document.getElementById(`ph${i}`).classList.add('hi');
    });
  pw.appendChild(img);pw.appendChild(ov);
}

function refreshAllPanels(){for(let i=0;i<4;i++)refreshPanel(i);}

// ══════════════════════════════════════════════
// エクスポート（ダウンロード + クリップボードコピー）
// ══════════════════════════════════════════════
async function doExport(){
  if(!pinned.some(p=>p)){
    alert('比較パネルに画像がありません。\nシングルビューで「この画像を記録」ボタンを押してください。');
    return;
  }
  const ww=+document.getElementById('ww').value;
  const wc=+document.getElementById('wc').value;
  showLoad('4枚まとめ画像を生成中...');
  try{
    const params=new URLSearchParams({ww,wc,pinned:JSON.stringify(pinned)});
    const r=await fetch('/api/export?'+params);
    if(!r.ok)throw new Error(await r.text());
    const blob=await r.blob();

    // クリップボードへのコピーを試みる（電子カルテへの貼り付け用）
    let copied=false;
    try{
      await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);
      copied=true;
    }catch(_){}

    // ファイルダウンロードも実行
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download='CT比較4枚.png';
    a.click();

    const msg=copied
      ?'✅ クリップボードにコピー済み＋ファイルをダウンロードしました — 電子カルテに貼り付けできます'
      :'📥 画像をダウンロードしました（CT比較4枚.png）';
    status(msg);
    _toast(msg);
  }catch(e){alert('エラー: '+e.message);}
  finally{hideLoad();}
}

function _toast(msg){
  const d=document.createElement('div');
  d.style.cssText='position:fixed;bottom:40px;left:50%;transform:translateX(-50%);'
    +'background:#1c1c1c;border:1px solid #0a84ff;color:#fff;'
    +'padding:12px 28px;border-radius:8px;font-size:13px;z-index:500;'
    +'box-shadow:0 4px 20px rgba(0,0,0,.7);white-space:nowrap;transition:opacity .5s';
  d.textContent=msg;
  document.body.appendChild(d);
  setTimeout(()=>d.style.opacity='0',3500);
  setTimeout(()=>d.remove(),4100);
}

// ══════════════════════════════════════════════
// 操作ガイド
// ══════════════════════════════════════════════
function showShortcuts(){
  const h=`<div style="position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:300;display:flex;align-items:center;justify-content:center" onclick="this.remove()">
  <div style="background:#1e1e1e;border:1px solid #3a3a3a;border-radius:10px;padding:24px;min-width:380px;max-width:480px" onclick="event.stopPropagation()">
    <h3 style="color:#fff;margin-bottom:16px;font-size:14px">操作ガイド</h3>
    <table style="font-size:12px;line-height:2;width:100%;border-collapse:collapse">
      <tr><td style="color:#0a84ff;font-family:monospace;width:160px">↑↓ / ←→</td><td style="color:#ccc">スライスを1枚前/後</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">Page Up / Page Down</td><td style="color:#ccc">10枚前/後にジャンプ</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">Home / End</td><td style="color:#ccc">最初/最後のスライス</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">マウスホイール</td><td style="color:#ccc">スライス切り替え</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">Ctrl + ホイール</td><td style="color:#ccc">ズーム</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">＋ / −</td><td style="color:#ccc">ズームイン/アウト</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">0</td><td style="color:#ccc">表示リセット</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">左ドラッグ</td><td style="color:#ccc">パン（画像移動）</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">右ドラッグ 左右</td><td style="color:#ccc">Window Width（コントラスト）調整</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">右ドラッグ 上下</td><td style="color:#ccc">Window Center（輝度）調整</td></tr>
      <tr><td style="color:#0a84ff;font-family:monospace">📌 記録ボタン</td><td style="color:#ccc">現在の画像を比較に記録（4枚で自動エクスポート）</td></tr>
    </table>
    <p style="color:#555;font-size:11px;margin-top:16px">クリックで閉じる</p>
  </div></div>`;
  document.body.insertAdjacentHTML('beforeend',h);
}

// ══════════════════════════════════════════════
// ユーティリティ
// ══════════════════════════════════════════════
function status(m){document.getElementById('status').textContent=m;}
function showLoad(m){document.getElementById('load-msg').textContent=m;document.getElementById('loading').classList.add('show');}
function hideLoad(){document.getElementById('loading').classList.remove('show');}
window.addEventListener('resize',()=>{if(curUID)loadImg();});
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────
# 起動
# ─────────────────────────────────────────────────────────────

def main():
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    url    = f'http://127.0.0.1:{PORT}'
    print(f"DICOM CT ビューアー起動: {url}")
    print("ブラウザが自動的に開きます。  終了: Ctrl + C")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n終了しました。')


if __name__ == '__main__':
    main()
