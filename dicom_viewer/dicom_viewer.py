#!/usr/bin/env python3
"""
DICOM CT ビューアー
医師向け DICOM CT 画像表示アプリケーション

使い方:
  python3 dicom_viewer.py

必要ライブラリ:
  pip3 install pydicom Pillow numpy
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
import threading

import numpy as np

try:
    import pydicom
    from pydicom.errors import InvalidDicomError
except ImportError:
    print("pydicom が見つかりません。次のコマンドでインストールしてください:")
    print("  pip3 install pydicom")
    sys.exit(1)

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
except ImportError:
    print("Pillow が見つかりません。次のコマンドでインストールしてください:")
    print("  pip3 install Pillow")
    sys.exit(1)


# ─────────────────────────────────────────
# データクラス
# ─────────────────────────────────────────

class DicomFile:
    """単一DICOMファイルのラッパー（メタデータ先読み）"""

    def __init__(self, path):
        self.path = path
        self.valid = False
        self._dataset = None
        self._pixel_array = None

        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
            self.instance_number = int(ds.get('InstanceNumber', 0))
            self.slice_location  = float(ds.get('SliceLocation',
                                                 self.instance_number))
            self.series_uid      = str(ds.get('SeriesInstanceUID', ''))
            self.series_desc     = str(ds.get('SeriesDescription', ''))
            self.patient_name    = str(ds.get('PatientName', ''))
            self.study_date      = str(ds.get('StudyDate', ''))
            self.modality        = str(ds.get('Modality', ''))
            self.valid = bool(self.series_uid)
        except Exception:
            pass

    def dataset(self):
        if self._dataset is None:
            self._dataset = pydicom.dcmread(self.path)
        return self._dataset

    def pixel_array_hu(self):
        """ピクセル配列をHounsfield Unit（HU）に変換して返す"""
        if self._pixel_array is not None:
            return self._pixel_array
        ds = self.dataset()
        arr = ds.pixel_array.astype(np.float32)
        slope     = float(getattr(ds, 'RescaleSlope',     1.0))
        intercept = float(getattr(ds, 'RescaleIntercept', 0.0))
        self._pixel_array = arr * slope + intercept
        return self._pixel_array


class DicomSeries:
    """同一SeriesInstanceUIDのファイル群"""

    def __init__(self, uid, desc, files):
        self.uid   = uid
        self.desc  = desc or f"シリーズ {uid[:8]}"
        self.files = sorted(files,
                            key=lambda f: (f.slice_location, f.instance_number))
        self.count = len(self.files)

    def display_name(self):
        return f"{self.desc}  ({self.count}枚)"


# ─────────────────────────────────────────
# メインアプリ
# ─────────────────────────────────────────

class DicomViewer(tk.Tk):

    # CT ウィンドウプリセット
    PRESETS = [
        ("軟部組織",  400,   40),
        ("骨窓",     1500,  300),
        ("肺窓",     1500, -600),
        ("脳窓",      80,   40),
        ("腹部",      350,   40),
        ("縦隔",      400,   40),
    ]

    def __init__(self):
        super().__init__()
        self.title("DICOM CT ビューアー")
        self.configure(bg='#111111')

        # ── 状態変数 ──────────────────────────
        self.series_list     = []
        self.current_series  = None
        self.current_index   = 0

        self.pinned          = [None] * 4   # (DicomSeries, index) or None
        self._quad_photos    = [None] * 4   # PhotoImage 参照保持

        self.zoom_factor     = 1.0
        self.pan_x           = 0
        self.pan_y           = 0
        self._drag_start     = None
        self._pan_start      = (0, 0)

        self.ww = tk.IntVar(value=400)
        self.wc = tk.IntVar(value=40)
        self._wl_drag_start  = None
        self._wl_start_ww    = 400
        self._wl_start_wc    = 40

        self._main_photo     = None   # PhotoImage 参照保持（GC防止）
        self._loading        = False

        # ── UI 構築 ─────────────────────────
        self._build_menu()
        self._build_ui()
        self._bind_events()

        # 最大化
        try:
            self.state('zoomed')
        except Exception:
            self.geometry("1400x900")

    # ═══════════════════════════════════════
    # メニュー
    # ═══════════════════════════════════════

    def _build_menu(self):
        mb = tk.Menu(self)

        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="フォルダ / CD を開く (⌘O)",
                       command=self.open_folder)
        fm.add_separator()
        fm.add_command(label="終了", command=self.quit)
        mb.add_cascade(label="ファイル", menu=fm)

        vm = tk.Menu(mb, tearoff=0)
        vm.add_command(label="表示リセット (0)",      command=self.reset_view)
        vm.add_command(label="W/L リセット",          command=self._reset_wl)
        mb.add_cascade(label="表示", menu=vm)

        pm = tk.Menu(mb, tearoff=0)
        for name, ww, wc in self.PRESETS:
            pm.add_command(label=f"{name}  (W:{ww} C:{wc})",
                           command=lambda w=ww, c=wc: self._apply_preset(w, c))
        mb.add_cascade(label="CTプリセット", menu=pm)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="キーボードショートカット",
                       command=self._show_shortcuts)
        mb.add_cascade(label="ヘルプ", menu=hm)

        self.config(menu=mb)

    # ═══════════════════════════════════════
    # UI 構築
    # ═══════════════════════════════════════

    def _build_ui(self):
        main = tk.Frame(self, bg='#111111')
        main.pack(fill=tk.BOTH, expand=True)

        self._build_sidebar(main)

        right = tk.Frame(main, bg='#111111')
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_toolbar(right)
        self._build_notebook(right)
        self._build_statusbar()

    # ─── サイドバー（シリーズ一覧）─────────────────

    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg='#1e1e1e', width=230)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        sb.pack_propagate(False)

        tk.Label(sb, text="シリーズ一覧",
                 bg='#1e1e1e', fg='#cccccc',
                 font=('Helvetica', 11, 'bold'), pady=8).pack(fill=tk.X)

        tk.Button(sb, text="📁  フォルダ / CD を開く",
                  command=self.open_folder,
                  bg='#0a84ff', fg='white',
                  font=('Helvetica', 10),
                  relief=tk.FLAT, cursor='hand2', pady=7
                  ).pack(fill=tk.X, padx=8, pady=(0, 8))

        lf = tk.Frame(sb, bg='#1e1e1e')
        lf.pack(fill=tk.BOTH, expand=True, padx=4)

        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL)
        self.series_lb = tk.Listbox(
            lf,
            yscrollcommand=vsb.set,
            bg='#111111', fg='#dddddd',
            selectbackground='#0a84ff', selectforeground='white',
            font=('Helvetica', 9),
            relief=tk.FLAT, borderwidth=0,
            activestyle='none'
        )
        vsb.config(command=self.series_lb.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.series_lb.pack(fill=tk.BOTH, expand=True)
        self.series_lb.bind('<<ListboxSelect>>', self._on_series_select)

        self.series_info = tk.Label(sb, text="",
                                    bg='#1e1e1e', fg='#888888',
                                    font=('Helvetica', 8), wraplength=210,
                                    justify='left')
        self.series_info.pack(padx=8, pady=4, anchor='w')

    # ─── ツールバー ──────────────────────────────

    def _build_toolbar(self, parent):
        tb = tk.Frame(parent, bg='#2a2a2a', height=44)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)

        def lbl(text):
            return tk.Label(tb, text=text, bg='#2a2a2a', fg='#cccccc',
                            font=('Helvetica', 10))

        def spin(var, lo, hi, w=5):
            s = tk.Spinbox(tb, from_=lo, to=hi, textvariable=var,
                           width=w, bg='#3a3a3a', fg='white',
                           buttonbackground='#3a3a3a', insertbackground='white',
                           command=self.update_display)
            s.bind('<Return>', lambda _: self.update_display())
            return s

        lbl("W:").pack(side=tk.LEFT, padx=(10, 2))
        spin(self.ww, 1, 10000).pack(side=tk.LEFT)
        lbl("  C:").pack(side=tk.LEFT, padx=(6, 2))
        spin(self.wc, -10000, 10000, w=6).pack(side=tk.LEFT)

        # プリセットボタン
        tk.Frame(tb, bg='#444444', width=1).pack(side=tk.LEFT, fill=tk.Y,
                                                  padx=8, pady=6)
        for name, ww, wc in self.PRESETS:
            tk.Button(tb, text=name,
                      command=lambda w=ww, c=wc: self._apply_preset(w, c),
                      bg='#3a3a3a', fg='white',
                      font=('Helvetica', 9), relief=tk.FLAT,
                      cursor='hand2', padx=6, pady=3
                      ).pack(side=tk.LEFT, padx=2, pady=8)

        # ズーム
        tk.Frame(tb, bg='#444444', width=1).pack(side=tk.LEFT, fill=tk.Y,
                                                  padx=8, pady=6)
        lbl("ズーム:").pack(side=tk.LEFT, padx=(4, 4))

        tk.Button(tb, text="－", command=self.zoom_out,
                  bg='#3a3a3a', fg='white', font=('Helvetica', 13, 'bold'),
                  relief=tk.FLAT, cursor='hand2', width=2
                  ).pack(side=tk.LEFT, pady=8)

        self.zoom_lbl = tk.Label(tb, text="100%",
                                  bg='#2a2a2a', fg='#cccccc',
                                  font=('Helvetica', 10), width=5)
        self.zoom_lbl.pack(side=tk.LEFT)

        tk.Button(tb, text="＋", command=self.zoom_in,
                  bg='#3a3a3a', fg='white', font=('Helvetica', 13, 'bold'),
                  relief=tk.FLAT, cursor='hand2', width=2
                  ).pack(side=tk.LEFT, pady=8)

        tk.Button(tb, text="リセット", command=self.reset_view,
                  bg='#3a3a3a', fg='white', font=('Helvetica', 9),
                  relief=tk.FLAT, cursor='hand2', padx=6, pady=3
                  ).pack(side=tk.LEFT, padx=6, pady=8)

    # ─── タブ（シングル / 4パネル）──────────────────

    def _build_notebook(self, parent):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('DV.TNotebook',
                        background='#111111', borderwidth=0)
        style.configure('DV.TNotebook.Tab',
                        background='#2a2a2a', foreground='#cccccc',
                        padding=[14, 6], font=('Helvetica', 10))
        style.map('DV.TNotebook.Tab',
                  background=[('selected', '#0a84ff')],
                  foreground=[('selected', 'white')])

        self.nb = ttk.Notebook(parent, style='DV.TNotebook')
        self.nb.pack(fill=tk.BOTH, expand=True)

        self._build_single_tab()
        self._build_quad_tab()

    def _build_single_tab(self):
        frame = tk.Frame(self.nb, bg='#111111')
        self.nb.add(frame, text="  シングルビュー  ")

        # メインキャンバス
        self.canvas = tk.Canvas(frame, bg='#000000',
                                cursor='crosshair', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # スライダーバー
        sf = tk.Frame(frame, bg='#1a1a1a')
        sf.pack(fill=tk.X, padx=8, pady=4)

        self.slice_lbl = tk.Label(sf, text="スライス: - / -",
                                   bg='#1a1a1a', fg='#888888',
                                   font=('Helvetica', 9), width=14)
        self.slice_lbl.pack(side=tk.LEFT)

        self.slider = ttk.Scale(sf, from_=0, to=1,
                                orient=tk.HORIZONTAL,
                                command=self._on_slider)
        self.slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        # 比較パネルに追加ボタン
        pf = tk.Frame(frame, bg='#1a1a1a')
        pf.pack(fill=tk.X, padx=8, pady=(0, 6))

        tk.Label(pf, text="比較パネルに追加:",
                 bg='#1a1a1a', fg='#cccccc',
                 font=('Helvetica', 10)).pack(side=tk.LEFT, padx=(0, 8))

        self.pin_btns = []
        for i in range(4):
            b = tk.Button(pf, text=f"パネル {i+1}",
                          command=lambda idx=i: self.pin_to_panel(idx),
                          bg='#3a3a3a', fg='white',
                          font=('Helvetica', 9), relief=tk.FLAT,
                          cursor='hand2', padx=10, pady=4)
            b.pack(side=tk.LEFT, padx=3)
            self.pin_btns.append(b)

        tk.Label(pf, text="（比較したいスライスを最大4枚選択して電子カルテ用にエクスポート）",
                 bg='#1a1a1a', fg='#666666',
                 font=('Helvetica', 8)).pack(side=tk.LEFT, padx=12)

    def _build_quad_tab(self):
        frame = tk.Frame(self.nb, bg='#111111')
        self.nb.add(frame, text="  4枚比較・エクスポート  ")

        frame.rowconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(2, weight=0)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self.quad_canvases = []
        self.quad_title_labels = []

        for i in range(4):
            row, col = divmod(i, 2)
            pf = tk.Frame(frame, bg='#1e1e1e',
                          highlightthickness=1,
                          highlightbackground='#333333')
            pf.grid(row=row, column=col, padx=2, pady=2, sticky='nsew')

            # タイトルバー
            tf = tk.Frame(pf, bg='#2a2a2a', height=26)
            tf.pack(fill=tk.X)
            tf.pack_propagate(False)

            tl = tk.Label(tf, text=f"パネル {i+1}  （空）",
                          bg='#2a2a2a', fg='#888888',
                          font=('Helvetica', 9), anchor='w')
            tl.pack(side=tk.LEFT, padx=8, fill=tk.Y)
            self.quad_title_labels.append(tl)

            tk.Button(tf, text="クリア",
                      command=lambda idx=i: self.clear_panel(idx),
                      bg='#2a2a2a', fg='#888888',
                      font=('Helvetica', 8), relief=tk.FLAT,
                      cursor='hand2', padx=4
                      ).pack(side=tk.RIGHT, padx=4)

            cv = tk.Canvas(pf, bg='#000000', highlightthickness=0)
            cv.pack(fill=tk.BOTH, expand=True)
            cv.bind('<Double-Button-1>',
                    lambda e, idx=i: self._focus_panel(idx))
            cv.bind('<Configure>',
                    lambda e, idx=i: self._redraw_quad_panel(idx))
            self.quad_canvases.append(cv)

        # エクスポートバー
        ef = tk.Frame(frame, bg='#1a1a1a')
        ef.grid(row=2, column=0, columnspan=2, sticky='ew', pady=4)

        tk.Button(ef,
                  text="📷  選択した4枚を1枚の画像にしてエクスポート（電子カルテ保存用）",
                  command=self.export_quad,
                  bg='#0a84ff', fg='white',
                  font=('Helvetica', 11, 'bold'),
                  relief=tk.FLAT, cursor='hand2', pady=8
                  ).pack(side=tk.LEFT, padx=16, pady=4)

        tk.Label(ef,
                 text="ダブルクリック → そのパネルをシングルビューで拡大表示",
                 bg='#1a1a1a', fg='#666666',
                 font=('Helvetica', 9)).pack(side=tk.LEFT, padx=8)

    # ─── ステータスバー ─────────────────────────

    def _build_statusbar(self):
        sf = tk.Frame(self, bg='#2a2a2a', height=22)
        sf.pack(fill=tk.X, side=tk.BOTTOM)
        sf.pack_propagate(False)

        self.status_var = tk.StringVar(value="フォルダまたはCDを開いてください")
        tk.Label(sf, textvariable=self.status_var,
                 bg='#2a2a2a', fg='#aaaaaa',
                 font=('Helvetica', 9), anchor='w'
                 ).pack(side=tk.LEFT, padx=8, fill=tk.Y)

        self.pos_lbl = tk.Label(sf, text="",
                                bg='#2a2a2a', fg='#aaaaaa',
                                font=('Helvetica', 9))
        self.pos_lbl.pack(side=tk.RIGHT, padx=8)

        self.hu_lbl = tk.Label(sf, text="HU: —",
                               bg='#2a2a2a', fg='#aaaaaa',
                               font=('Helvetica', 9))
        self.hu_lbl.pack(side=tk.RIGHT, padx=16)

    # ═══════════════════════════════════════
    # イベントバインド
    # ═══════════════════════════════════════

    def _bind_events(self):
        # キーボードナビゲーション
        for key in ('<Up>', '<Left>'):
            self.bind(key, lambda e: self.scroll_image(-1))
        for key in ('<Down>', '<Right>'):
            self.bind(key, lambda e: self.scroll_image(1))
        self.bind('<Prior>',    lambda e: self.scroll_image(-10))   # Page Up
        self.bind('<Next>',     lambda e: self.scroll_image(10))    # Page Down
        self.bind('<Home>',     lambda e: self._jump_to(0))
        self.bind('<End>',      lambda e: self._jump_to(-1))
        self.bind('<plus>',     lambda e: self.zoom_in())
        self.bind('<equal>',    lambda e: self.zoom_in())
        self.bind('<minus>',    lambda e: self.zoom_out())
        self.bind('<Key-0>',    lambda e: self.reset_view())
        self.bind('<Command-o>', lambda e: self.open_folder())

        # マウスホイール（スクロール）
        self.canvas.bind('<MouseWheel>', self._on_wheel)
        self.canvas.bind('<Button-4>',   lambda e: self.scroll_image(-1))
        self.canvas.bind('<Button-5>',   lambda e: self.scroll_image(1))

        # Ctrl+ホイール → ズーム
        self.canvas.bind('<Control-MouseWheel>', self._on_ctrl_wheel)

        # 左ドラッグ → パン
        self.canvas.bind('<ButtonPress-1>',  self._start_pan)
        self.canvas.bind('<B1-Motion>',      self._do_pan)

        # 右ドラッグ → W/L 調整
        self.canvas.bind('<ButtonPress-2>',  self._start_wl)
        self.canvas.bind('<B2-Motion>',      self._do_wl)
        self.canvas.bind('<ButtonPress-3>',  self._start_wl)
        self.canvas.bind('<B3-Motion>',      self._do_wl)

        # マウス移動 → HU 表示
        self.canvas.bind('<Motion>', self._on_mouse_move)

        # キャンバスリサイズ
        self.canvas.bind('<Configure>', lambda e: self.update_display())

    # ═══════════════════════════════════════
    # フォルダ読み込み
    # ═══════════════════════════════════════

    def open_folder(self):
        folder = filedialog.askdirectory(title="DICOMフォルダ（またはCDドライブ）を選択")
        if not folder:
            return
        if self._loading:
            return

        self._loading = True
        self.series_lb.delete(0, tk.END)
        self.series_lb.insert(0, "読み込み中...")
        self.status_var.set("DICOMファイルをスキャン中...")

        t = threading.Thread(target=self._load_folder, args=(folder,), daemon=True)
        t.start()

    def _load_folder(self, folder):
        series_dict = defaultdict(list)
        total = 0

        skip_dirs = {'autorun', 'viewer', 'software', 'dicomdir', '.ds_store',
                     '__macosx'}

        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs
                       if d.lower() not in skip_dirs and not d.startswith('.')]

            for fn in files:
                if fn.startswith('.'):
                    continue
                path = os.path.join(root, fn)
                df = DicomFile(path)
                if df.valid:
                    series_dict[df.series_uid].append(df)
                    total += 1
                    if total % 100 == 0:
                        self.after(0, lambda n=total:
                                   self.status_var.set(
                                       f"スキャン中... {n} ファイル検出"))

        series_list = []
        for uid, files in series_dict.items():
            desc = files[0].series_desc if files else ''
            series_list.append(DicomSeries(uid, desc, files))

        series_list.sort(key=lambda s: s.desc)
        self.after(0, lambda: self._on_load_done(series_list, total))

    def _on_load_done(self, series_list, total):
        self._loading = False
        self.series_list = series_list
        self.series_lb.delete(0, tk.END)

        if not series_list:
            self.series_lb.insert(0, "DICOMファイルが見つかりません")
            self.status_var.set("DICOMファイルが見つかりませんでした")
            self.series_info.config(text="")
            return

        for s in series_list:
            self.series_lb.insert(tk.END, s.display_name())

        self.series_info.config(
            text=f"{len(series_list)} シリーズ  /  合計 {total} ファイル")
        self.status_var.set(
            f"{len(series_list)} シリーズを読み込みました（計 {total} 枚）")

        # 最初のシリーズを自動選択
        self.series_lb.selection_set(0)
        self.load_series(series_list[0])

    # ═══════════════════════════════════════
    # シリーズ表示
    # ═══════════════════════════════════════

    def _on_series_select(self, event):
        sel = self.series_lb.curselection()
        if sel and self.series_list:
            idx = sel[0]
            if idx < len(self.series_list):
                self.load_series(self.series_list[idx])

    def load_series(self, series):
        self.current_series = series
        self.current_index  = 0
        self.zoom_factor    = 1.0
        self.pan_x = self.pan_y = 0

        if series.count > 1:
            self.slider.configure(to=series.count - 1)
        self.slider.set(0)

        self.status_var.set(
            f"シリーズ: {series.desc}  （{series.count} 枚）")
        self.update_display()

    # ═══════════════════════════════════════
    # 画像レンダリング
    # ═══════════════════════════════════════

    def _apply_windowing(self, arr, ww, wc):
        lo = wc - ww / 2
        hi = wc + ww / 2
        img = np.clip(arr, lo, hi)
        img = ((img - lo) / (hi - lo) * 255.0).astype(np.uint8)
        return img

    def _render_pil(self, df, target_w, target_h, zoom=None):
        """DICOMファイルをPIL Imageとしてレンダリング"""
        arr = df.pixel_array_hu()
        img_arr = self._apply_windowing(arr, self.ww.get(), self.wc.get())
        pil = Image.fromarray(img_arr, mode='L')

        if zoom is not None:
            iw, ih = pil.size
            new_w = max(1, int(iw * zoom))
            new_h = max(1, int(ih * zoom))
            pil = pil.resize((new_w, new_h), Image.LANCZOS)
        else:
            # アスペクト比を維持してフィット
            iw, ih = pil.size
            ratio = min(target_w / iw, target_h / ih)
            new_w = max(1, int(iw * ratio))
            new_h = max(1, int(ih * ratio))
            pil = pil.resize((new_w, new_h), Image.LANCZOS)

        return pil

    def update_display(self, *_):
        """シングルビューの描画"""
        if self.current_series is None:
            return
        if self.current_index >= self.current_series.count:
            return

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            return

        df = self.current_series.files[self.current_index]

        try:
            pil = self._render_pil(df, cw, ch, zoom=self.zoom_factor)
        except Exception as e:
            self.status_var.set(f"画像エラー: {e}")
            return

        photo = ImageTk.PhotoImage(pil)
        self._main_photo = photo   # 参照保持

        self.canvas.delete('all')

        iw, ih = pil.size
        cx = cw // 2 + self.pan_x
        cy = ch // 2 + self.pan_y
        self.canvas.create_image(cx, cy, anchor='center', image=photo)

        self._draw_overlay(df, cw, ch)

        # スライス情報
        total = self.current_series.count
        self.slice_lbl.config(
            text=f"スライス: {self.current_index + 1} / {total}")
        self.zoom_lbl.config(text=f"{int(self.zoom_factor * 100)}%")

    def _draw_overlay(self, df, cw, ch):
        """情報オーバーレイ描画"""
        try:
            ds = df.dataset()
            pname = str(ds.get('PatientName', ''))
            date  = str(ds.get('StudyDate', ''))
            if len(date) == 8:
                date = f"{date[:4]}/{date[4:6]}/{date[6:]}"
            ww = self.ww.get()
            wc = self.wc.get()
            sloc = ds.get('SliceLocation', '')
            inst = ds.get('InstanceNumber', '')
            sdesc = str(ds.get('SeriesDescription', ''))

            yellow = '#ffff00'
            fnt    = ('Helvetica', 9)

            # 左上
            self.canvas.create_text(8, 8, anchor='nw',
                text=f"{pname}\n{date}", fill=yellow, font=fnt)
            # 右上
            self.canvas.create_text(cw - 8, 8, anchor='ne',
                text=f"W:{ww}  C:{wc}", fill=yellow, font=fnt)
            # 左下
            loc_str = f"{float(sloc):.1f} mm" if sloc != '' else ''
            self.canvas.create_text(8, ch - 8, anchor='sw',
                text=f"No.{inst}  {loc_str}", fill=yellow, font=fnt)
            # 右下
            self.canvas.create_text(cw - 8, ch - 8, anchor='se',
                text=sdesc, fill=yellow, font=fnt)
        except Exception:
            pass

    # ═══════════════════════════════════════
    # ナビゲーション
    # ═══════════════════════════════════════

    def scroll_image(self, delta):
        if self.current_series is None:
            return
        self._jump_to(self.current_index + delta)

    def _jump_to(self, idx):
        if self.current_series is None:
            return
        n = self.current_series.count
        if idx < 0:
            idx = n + idx
        self.current_index = max(0, min(idx, n - 1))
        self.slider.set(self.current_index)
        self.update_display()

    def _on_slider(self, val):
        if self.current_series is None:
            return
        idx = int(float(val))
        if idx != self.current_index:
            self.current_index = idx
            self.update_display()

    # ═══════════════════════════════════════
    # マウス操作
    # ═══════════════════════════════════════

    def _on_wheel(self, event):
        self.scroll_image(-1 if event.delta > 0 else 1)

    def _on_ctrl_wheel(self, event):
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def _start_pan(self, event):
        self._drag_start = (event.x, event.y)
        self._pan_start  = (self.pan_x, self.pan_y)

    def _do_pan(self, event):
        if self._drag_start:
            self.pan_x = self._pan_start[0] + (event.x - self._drag_start[0])
            self.pan_y = self._pan_start[1] + (event.y - self._drag_start[1])
            self.update_display()

    def _start_wl(self, event):
        self._wl_drag_start = (event.x, event.y)
        self._wl_start_ww   = self.ww.get()
        self._wl_start_wc   = self.wc.get()

    def _do_wl(self, event):
        if self._wl_drag_start:
            dx = event.x - self._wl_drag_start[0]
            dy = event.y - self._wl_drag_start[1]
            self.ww.set(max(1, int(self._wl_start_ww + dx * 5)))
            self.wc.set(int(self._wl_start_wc - dy * 5))
            self.update_display()

    def _on_mouse_move(self, event):
        if self.current_series is None:
            return
        try:
            df  = self.current_series.files[self.current_index]
            arr = df.pixel_array_hu()
            ih, iw = arr.shape
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()

            disp_w = int(iw * self.zoom_factor)
            disp_h = int(ih * self.zoom_factor)
            cx = cw // 2 + self.pan_x
            cy = ch // 2 + self.pan_y

            img_x = int((event.x - cx + disp_w / 2) / self.zoom_factor)
            img_y = int((event.y - cy + disp_h / 2) / self.zoom_factor)

            if 0 <= img_x < iw and 0 <= img_y < ih:
                hu = arr[img_y, img_x]
                self.hu_lbl.config(text=f"HU: {hu:.0f}")
                self.pos_lbl.config(text=f"座標: ({img_x}, {img_y})")
        except Exception:
            pass

    # ═══════════════════════════════════════
    # ズーム
    # ═══════════════════════════════════════

    def zoom_in(self, event=None):
        self.zoom_factor = min(self.zoom_factor * 1.25, 16.0)
        self.update_display()

    def zoom_out(self, event=None):
        self.zoom_factor = max(self.zoom_factor / 1.25, 0.05)
        self.update_display()

    def reset_view(self):
        self.zoom_factor = 1.0
        self.pan_x = self.pan_y = 0
        self.update_display()

    def _reset_wl(self):
        self.ww.set(400)
        self.wc.set(40)
        self.update_display()

    def _apply_preset(self, ww, wc):
        self.ww.set(ww)
        self.wc.set(wc)
        self.update_display()

    # ═══════════════════════════════════════
    # 4パネル比較
    # ═══════════════════════════════════════

    def pin_to_panel(self, panel_idx):
        if self.current_series is None:
            messagebox.showwarning("警告", "シリーズが選択されていません")
            return
        self.pinned[panel_idx] = (self.current_series, self.current_index)
        self._refresh_quad()
        # 4枚比較タブに切り替え
        self.nb.select(1)
        self.status_var.set(
            f"パネル {panel_idx+1} に "
            f"{self.current_series.desc} [{self.current_index+1}枚目] を追加しました")

    def clear_panel(self, panel_idx):
        self.pinned[panel_idx] = None
        self._quad_photos[panel_idx] = None
        self._redraw_quad_panel(panel_idx)
        self.quad_title_labels[panel_idx].config(
            text=f"パネル {panel_idx+1}  （空）", fg='#888888')

    def _focus_panel(self, panel_idx):
        """ダブルクリック → シングルビューで拡大表示"""
        if self.pinned[panel_idx] is None:
            return
        series, idx = self.pinned[panel_idx]
        self.current_series = series
        self.current_index  = idx
        self.nb.select(0)
        self.update_display()

    def _refresh_quad(self):
        for i in range(4):
            self._redraw_quad_panel(i)

    def _redraw_quad_panel(self, idx, event=None):
        cv = self.quad_canvases[idx]
        cv.delete('all')

        cw = cv.winfo_width()
        ch = cv.winfo_height()
        if cw <= 1:
            cw = 400
        if ch <= 1:
            ch = 300

        pinned = self.pinned[idx]

        if pinned is None:
            cv.create_text(cw // 2, ch // 2,
                           text=f"パネル {idx+1}\n\nシングルビューで「パネル {idx+1}」\nボタンを押して追加",
                           fill='#444444', font=('Helvetica', 10),
                           justify='center')
            self.quad_title_labels[idx].config(
                text=f"パネル {idx+1}  （空）", fg='#888888')
            return

        series, img_idx = pinned
        df = series.files[img_idx]

        try:
            pil = self._render_pil(df, cw, ch)
            photo = ImageTk.PhotoImage(pil)
            self._quad_photos[idx] = photo

            iw, ih = pil.size
            cv.create_image(cw // 2, ch // 2, anchor='center', image=photo)

            # オーバーレイ
            ds = df.dataset()
            sloc = ds.get('SliceLocation', '')
            loc_str = f"  {float(sloc):.1f}mm" if sloc != '' else ''
            cv.create_text(4, 4, anchor='nw',
                           text=f"{series.desc}\nNo.{img_idx+1}/{series.count}{loc_str}",
                           fill='#ffff00', font=('Helvetica', 8))

            self.quad_title_labels[idx].config(
                text=f"パネル {idx+1}:  {series.desc}  [{img_idx+1}/{series.count}]",
                fg='white')

        except Exception as e:
            cv.create_text(cw // 2, ch // 2,
                           text=f"エラー\n{e}", fill='#ff4444',
                           font=('Helvetica', 9), justify='center')

    # ═══════════════════════════════════════
    # エクスポート
    # ═══════════════════════════════════════

    def export_quad(self):
        filled = [(i, p) for i, p in enumerate(self.pinned) if p is not None]
        if not filled:
            messagebox.showwarning(
                "警告",
                "比較パネルに画像がありません。\n"
                "シングルビューで画像を選んで「パネル N」ボタンを押してください。")
            return

        path = filedialog.asksaveasfilename(
            title="4枚比較画像を保存（電子カルテ用）",
            defaultextension=".png",
            filetypes=[("PNG 画像", "*.png"), ("JPEG 画像", "*.jpg")],
            initialfile="CT比較4枚.png"
        )
        if not path:
            return

        # 高解像度合成（各パネル 600×600）
        PS  = 600
        GAP = 6
        W   = PS * 2 + GAP * 3
        H   = PS * 2 + GAP * 3 + 28   # 下部に情報バー

        composite = Image.new('RGB', (W, H), (15, 15, 15))
        draw = ImageDraw.Draw(composite)

        for i in range(4):
            row, col = divmod(i, 2)
            x = GAP + col * (PS + GAP)
            y = GAP + row * (PS + GAP)

            # 枠
            draw.rectangle([x - 1, y - 1, x + PS, y + PS],
                           outline=(60, 60, 60))

            if self.pinned[i] is None:
                draw.text((x + PS // 2, y + PS // 2),
                          f"パネル {i+1}\n（空）",
                          fill=(60, 60, 60), anchor='mm')
                continue

            series, idx = self.pinned[i]
            df = series.files[idx]

            try:
                arr     = df.pixel_array_hu()
                img_arr = self._apply_windowing(arr, self.ww.get(), self.wc.get())
                pil     = Image.fromarray(img_arr, mode='L').convert('RGB')

                iw, ih = pil.size
                ratio   = min(PS / iw, PS / ih)
                new_w   = max(1, int(iw * ratio))
                new_h   = max(1, int(ih * ratio))
                pil     = pil.resize((new_w, new_h), Image.LANCZOS)

                px = x + (PS - new_w) // 2
                py = y + (PS - new_h) // 2
                composite.paste(pil, (px, py))

                # オーバーレイ
                ds   = df.dataset()
                sloc = ds.get('SliceLocation', '')
                loc  = f"  {float(sloc):.1f}mm" if sloc != '' else ''
                draw.text((x + 4, y + 4),
                          f"{series.desc}\nNo.{idx+1}/{series.count}{loc}",
                          fill=(255, 255, 0))
                draw.text((x + PS - 4, y + 4),
                          f"[{i+1}]",
                          fill=(255, 255, 255), anchor='ra')

            except Exception as e:
                draw.text((x + PS // 2, y + PS // 2),
                          f"エラー\n{e}",
                          fill=(255, 60, 60), anchor='mm')

        # 情報バー
        info_y = H - 24
        draw.rectangle([0, info_y - 2, W, H], fill=(30, 30, 30))
        try:
            first_valid = next(p for p in self.pinned if p is not None)
            ds     = first_valid[0].files[0].dataset()
            pname  = str(ds.get('PatientName', ''))
            date   = str(ds.get('StudyDate', ''))
            if len(date) == 8:
                date = f"{date[:4]}/{date[4:6]}/{date[6:]}"
        except Exception:
            pname = ''
            date  = ''

        draw.text((GAP, info_y),
                  f"患者: {pname}  撮影日: {date}  "
                  f"W:{self.ww.get()} C:{self.wc.get()}",
                  fill=(180, 180, 180))

        # 保存
        if path.lower().endswith('.jpg') or path.lower().endswith('.jpeg'):
            composite.save(path, quality=95, dpi=(150, 150))
        else:
            composite.save(path, dpi=(150, 150))

        messagebox.showinfo("保存完了",
                            f"画像を保存しました:\n{path}\n\n"
                            f"解像度: {W} × {H} px  (電子カルテに貼り付け可能)")
        self.status_var.set(f"エクスポート完了: {path}")

    # ═══════════════════════════════════════
    # ショートカットヘルプ
    # ═══════════════════════════════════════

    def _show_shortcuts(self):
        win = tk.Toplevel(self)
        win.title("キーボードショートカット")
        win.configure(bg='#1e1e1e')
        win.geometry("420x360")
        win.resizable(False, False)

        shortcuts = [
            ("↑ / ←",         "前のスライス"),
            ("↓ / →",         "次のスライス"),
            ("Page Up",        "10枚前にジャンプ"),
            ("Page Down",      "10枚後にジャンプ"),
            ("Home",           "最初のスライス"),
            ("End",            "最後のスライス"),
            ("+ / =",          "ズームイン"),
            ("−",              "ズームアウト"),
            ("0",              "表示リセット"),
            ("⌘O",            "フォルダを開く"),
            ("左ドラッグ",     "パン（移動）"),
            ("右ドラッグ",     "W/L（ウィンドウ幅・レベル）調整\n  左右: Window Width\n  上下: Window Center"),
            ("マウスホイール", "スライス切り替え"),
        ]

        tk.Label(win, text="キーボードショートカット一覧",
                 bg='#1e1e1e', fg='white',
                 font=('Helvetica', 12, 'bold'), pady=12
                 ).pack()

        for key, desc in shortcuts:
            row = tk.Frame(win, bg='#1e1e1e')
            row.pack(fill=tk.X, padx=16, pady=2)
            tk.Label(row, text=key,
                     bg='#1e1e1e', fg='#0a84ff',
                     font=('Courier', 10), width=16, anchor='w'
                     ).pack(side=tk.LEFT)
            tk.Label(row, text=desc,
                     bg='#1e1e1e', fg='#cccccc',
                     font=('Helvetica', 10), anchor='w', justify='left'
                     ).pack(side=tk.LEFT)


# ─────────────────────────────────────────
# エントリーポイント
# ─────────────────────────────────────────

def main():
    app = DicomViewer()
    app.mainloop()


if __name__ == '__main__':
    main()
