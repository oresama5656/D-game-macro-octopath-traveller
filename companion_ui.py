"""Compact, parchment-and-brass desktop interface for the existing macro engine."""
import time
import tkinter as tk
from tkinter import ttk, messagebox
from win32_io import KEYS
from vision import SCENES

BG = "#181e1a"
CARD = "#252b25"
INK = "#eee5cf"
MUTED = "#aaa99b"
GOLD = "#c8b27d"
LINE = "#565440"

FIELDS = [
    ("left", "左へ移動", "left", "key"), ("right", "右へ移動", "right", "key"),
    ("dash", "ダッシュ（noneで無効）", "lshift", "key"),
    ("confirm", "決定", "enter", "key"), ("boost", "ブースト", "o", "key"),
    ("duration", "実行時間の上限 / 秒", "600", "number"),
    ("battle", "1戦の上限 / 秒", "180", "number"),
    ("stride", "往復の片道 / 秒", "0.8", "number"),
    ("confirm_interval", "決定入力の間隔 / 秒", "0.15", "number"),
    ("threshold", "画像判定の許容差", "12", "number"),
    ("heal_percent", "回復を始めるHP / %", "60", ["50", "60", "70", "80", "90"]),
    ("heal_members", "編成人数", "4", ["1", "2", "3", "4"]),
    ("menu", "メニューを開くキー", "i", "key"),
    ("cancel", "戻るキー", "backspace", "key"),
]


class CompanionUI:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.dialog = None
        self.tabs = {}
        self.last_wins = 0
        self.last_elapsed = 0
        self.state = tk.StringVar(value="待機中")
        self.detail = tk.StringVar(value="フィールドでF8を押すと、旅が始まります。")
        self.wins = tk.StringVar(value="0")
        self.elapsed = tk.StringVar(value="00:00")
        self.scene = tk.StringVar(value="—")
        self.output = tk.StringVar()
        self.health = tk.StringVar()
        for key, _, default, _ in FIELDS:
            app.values[key] = tk.StringVar(value=default)
        self.theme()
        self.build()
        self.refresh()

    def theme(self):
        root = self.root
        root.configure(background=BG)
        root.option_add("*Font", ("Yu Gothic UI", 10))
        root.option_add("*TCombobox*Listbox.background", CARD)
        root.option_add("*TCombobox*Listbox.foreground", INK)
        root.option_add("*TCombobox*Listbox.selectBackground", LINE)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Yu Gothic UI", 10))
        style.configure("Muted.TLabel", foreground=MUTED, font=("Yu Gothic UI", 9))
        style.configure("Gold.TLabel", foreground=GOLD)
        style.configure("TCheckbutton", background=BG, foreground=INK, font=("Yu Gothic UI", 10), padding=(0, 4))
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", GOLD)],
                  indicatorbackground=[("selected", GOLD), ("!selected", CARD)])
        style.configure("TRadiobutton", background=BG, foreground=INK, padding=5)
        style.map("TRadiobutton", background=[("active", BG)], foreground=[("active", GOLD)])
        style.configure("TButton", background=CARD, foreground=INK, bordercolor=LINE, lightcolor=CARD,
                        darkcolor=CARD, padding=(12, 7), font=("Yu Gothic UI", 10))
        style.map("TButton", background=[("active", "#383e31"), ("pressed", LINE)], foreground=[("active", GOLD)])
        style.configure("TEntry", fieldbackground=CARD, foreground=INK, insertcolor=INK, bordercolor=LINE, padding=5)
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=INK,
                        arrowcolor=GOLD, bordercolor=LINE, padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", INK)],
                  selectbackground=[("readonly", CARD)], selectforeground=[("readonly", INK)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(20, 9))
        style.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", GOLD)])
        style.configure("TLabelframe", background=BG, bordercolor=LINE)
        style.configure("TLabelframe.Label", background=BG, foreground=GOLD)

    def button(self, parent, text, command, primary=False, **kwargs):
        return tk.Button(parent, text=text, command=command, relief="flat", bd=0,
                         background=GOLD if primary else CARD,
                         foreground=BG if primary else INK,
                         activebackground="#e0c997" if primary else "#383e31",
                         activeforeground=BG if primary else GOLD,
                         font=("Yu Gothic UI", 10, "bold" if primary else "normal"),
                         cursor="hand2", padx=12, pady=8, takefocus=True, **kwargs)

    def build(self):
        root, app = self.root, self.app
        root.title("Octopath Companion")
        width, height = 408, 520
        x = max(0, root.winfo_screenwidth()-width-24)
        y = min(56, max(0, root.winfo_screenheight()-height-50))
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.resizable(False, False)
        panel = tk.Frame(root, bg=BG, padx=18, pady=14)
        panel.pack(fill="both", expand=True)
        header = tk.Frame(panel, bg=BG)
        header.pack(fill="x")
        tk.Label(header, text="OCTOPATH", bg=BG, fg=INK, font=("Georgia", 19)).pack(side="left")
        self.pin_button = tk.Button(header, text="◆ 固定", command=self.toggle_pin, bg=BG, fg=GOLD,
                                    activebackground=BG, activeforeground=INK, bd=0,
                                    font=("Yu Gothic UI", 9), cursor="hand2")
        self.pin_button.pack(side="right")
        tk.Label(panel, text="COMPANION   /   育成の手引き", bg=BG, fg=MUTED,
                 font=("Yu Gothic UI", 9)).pack(anchor="w", pady=(1, 6))
        rule = tk.Canvas(panel, height=12, bg=BG, highlightthickness=0)
        rule.pack(fill="x", pady=(0, 7))
        rule.create_line(0, 6, 172, 6, fill=LINE)
        rule.create_polygon(179, 2, 183, 6, 179, 10, 175, 6, fill=GOLD, outline="")
        rule.create_line(187, 6, 372, 6, fill=LINE)

        card = tk.Frame(panel, bg=CARD, highlightbackground=LINE, highlightthickness=1, padx=14, pady=10)
        card.pack(fill="x")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="◆  旅の状況", bg=CARD, fg=GOLD, font=("Yu Gothic UI", 9)).pack(side="left")
        tk.Label(row, textvariable=self.output, bg=CARD, fg=MUTED, font=("Yu Gothic UI", 9)).pack(side="right")
        self.state_label = tk.Label(card, textvariable=self.state, bg=CARD, fg=INK, font=("Yu Mincho", 20, "bold"))
        self.state_label.pack(anchor="w", pady=(5, 3))
        tk.Label(card, textvariable=self.detail, bg=CARD, fg=MUTED, wraplength=334,
                 justify="left", anchor="nw", height=2, font=("Yu Gothic UI", 9)).pack(fill="x")
        stats = tk.Frame(card, bg=CARD)
        stats.pack(fill="x", pady=(8, 0))
        for col, (title, variable) in enumerate((("勝利", self.wins), ("経過時間", self.elapsed), ("現在地", self.scene))):
            cell = tk.Frame(stats, bg=CARD)
            cell.grid(row=0, column=col, sticky="nsew")
            stats.columnconfigure(col, weight=1, uniform="stat")
            tk.Label(cell, text=title, bg=CARD, fg=MUTED, font=("Yu Gothic UI", 8)).pack(anchor="w")
            tk.Label(cell, textvariable=variable, bg=CARD, fg=INK, font=("Yu Gothic UI", 13)).pack(anchor="w", pady=(2, 0))

        modes = ttk.Frame(panel)
        modes.pack(fill="x", pady=(8, 2))
        for i, (text, variable) in enumerate((("BP全投入", app.bp_mode), ("戦闘後の回復", app.heal_mode),
                                            ("背景で動作", app.background), ("判定のみ", app.dry))):
            ttk.Checkbutton(modes, text=text, variable=variable, command=app.change_mode).grid(row=i//2, column=i%2, sticky="w")
        modes.columnconfigure(0, weight=1)
        modes.columnconfigure(1, weight=1)
        tk.Label(panel, textvariable=self.health, bg=BG, fg=MUTED, anchor="w", wraplength=370,
                 font=("Yu Gothic UI", 9), height=2, justify="left").pack(fill="x", pady=(2, 6))

        actions = tk.Frame(panel, bg=BG)
        actions.pack(fill="x")
        self.start_button = self.button(actions, "周回を開始   F8", self.toggle_run, primary=True)
        self.start_button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.button(actions, "停止  F9", lambda: app.stop("手動停止"), width=8).pack(side="right")
        utilities = tk.Frame(panel, bg=BG)
        utilities.pack(fill="x", pady=(8, 0))
        for label, tab in (("操作設定", "control"), ("画像登録", "markers"), ("回復設定", "healing")):
            self.button(utilities, label, lambda t=tab: self.open_settings(t)).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Label(panel, text="F8 開始／停止   ·   F9 緊急停止", bg=BG, fg=MUTED,
                 font=("Yu Gothic UI", 8)).pack(pady=(5, 0))

    def toggle_run(self):
        if self.app.loop or self.app.armed:
            self.app.stop("手動停止")
        else:
            self.app.start()

    def apply_pin(self):
        self.root.attributes("-topmost", self.app.topmost.get())
        self.pin_button.configure(text="◆ 固定" if self.app.topmost.get() else "◇ 固定", fg=GOLD if self.app.topmost.get() else MUTED)

    def toggle_pin(self):
        if self.app.loop and not self.app.run_background:
            self.app.stop("最前面の設定を変更しました。F8で再開してください")
        self.app.topmost.set(not self.app.topmost.get())
        self.apply_pin()
        try:
            self.app.save()
        except OSError as error:
            self.app.status.set(f"表示設定を保存できません：{error}")

    def fields(self, parent, keys):
        for row, (key, title, _, kind) in enumerate(field for field in FIELDS if field[0] in keys):
            ttk.Label(parent, text=title).grid(row=row, column=0, sticky="w", pady=2)
            if kind == "number":
                widget = ttk.Entry(parent, textvariable=self.app.values[key], width=17)
            else:
                choices = (["none", *KEYS] if key == "dash" else list(KEYS)) if kind == "key" else kind
                widget = ttk.Combobox(parent, textvariable=self.app.values[key], values=choices, state="readonly", width=15)
            widget.grid(row=row, column=1, sticky="e", pady=2, padx=(20, 0))
        parent.columnconfigure(0, weight=1)

    def open_settings(self, tab="control"):
        app = self.app
        if self.dialog and self.dialog.winfo_exists():
            self.notebook.select(self.tabs[tab])
            self.dialog.lift()
            return
        if app.loop or app.armed:
            app.stop("設定を開くため停止")
        dialog = self.dialog = tk.Toplevel(self.root)
        dialog.title("Companion — 設定")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.attributes("-topmost", app.topmost.get())
        w, h = 620, 580
        x = max(0, min(self.root.winfo_x()-w-12, self.root.winfo_screenwidth()-w))
        y = max(20, min(self.root.winfo_y(), self.root.winfo_screenheight()-h-60))
        dialog.geometry(f"{w}x{h}+{x}+{y}")
        dialog.minsize(w, h)
        dialog.grab_set()
        outer = ttk.Frame(dialog, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="旅の設定", font=("Yu Mincho", 17, "bold"), style="Gold.TLabel").pack(anchor="w", pady=(0, 10))
        notebook = self.notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self.tabs = {name: ttk.Frame(notebook, padding=16) for name in ("control", "markers", "healing", "status")}
        for name, title in (("control", "操作"), ("markers", "画像登録"), ("healing", "回復"), ("status", "状態")):
            notebook.add(self.tabs[name], text=title)
        self.fields(self.tabs["control"], {field[0] for field in FIELDS[:10]})
        ttk.Checkbutton(self.tabs["control"], text="簡易判定：フィールド以外は決定入力", variable=app.simple).grid(row=10, columnspan=2, sticky="w", pady=(12, 0))

        markers = self.tabs["markers"]
        ttk.Label(markers, text="画面に固有の目印を登録します。", style="Gold.TLabel").pack(anchor="w")
        ttk.Label(markers, text="フィールドはミニマップ中央の丸印。\n戦闘・勝利結果は固定の文字や枠を選びます。\n撮影は5秒後です。", style="Muted.TLabel").pack(anchor="w", pady=10)
        for key, title in SCENES.items():
            ttk.Radiobutton(markers, text=title, variable=app.scene, value=key).pack(anchor="w")
        row = ttk.Frame(markers)
        row.pack(fill="x", pady=16)
        ttk.Button(row, text="見本を追加", command=lambda: self.capture_action(app.register)).pack(side="left")
        ttk.Button(row, text="選択した種類を解除", command=app.clear_marker).pack(side="left", padx=8)
        ttk.Button(row, text="判定テスト", command=lambda: self.capture_action(app.test)).pack(side="left")
        ttk.Label(markers, textvariable=app.marker_status, wraplength=520, style="Muted.TLabel").pack(anchor="w")

        healing = self.tabs["healing"]
        ttk.Label(healing, text="オフィーリアの「回復魔法」で全体回復。", style="Gold.TLabel").pack(anchor="w")
        ttk.Label(healing, text="戦闘後に全員のHPを確認します。\n編成人数を変えたときは、ここも合わせてください。", style="Muted.TLabel").pack(anchor="w", pady=10)
        form = ttk.Frame(healing)
        form.pack(fill="x", pady=8)
        self.fields(form, {"heal_percent", "heal_members", "menu", "cancel"})
        ttk.Button(healing, text="HP確認・回復を1回テスト", command=self.healing_test).pack(anchor="w", pady=14)
        ttk.Label(healing, textvariable=app.heal_status, wraplength=510, style="Muted.TLabel").pack(anchor="w")

        status = self.tabs["status"]
        for title, variable in (("現在の状態", app.status), ("キー入力", app.mode_status), ("BP", app.bp_status), ("回復", app.heal_status)):
            ttk.Label(status, text=title, style="Gold.TLabel").pack(anchor="w", pady=(8, 2))
            ttk.Label(status, textvariable=variable, wraplength=515).pack(anchor="w")
        ttk.Label(status, text="詳細ログ：profiles/runtime.log\nゲームを最小化すると停止します。", style="Muted.TLabel").pack(anchor="w", pady=20)
        notebook.select(self.tabs[tab])
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Label(buttons, text="設定を開くと周回は停止します。", style="Muted.TLabel").pack(side="left")
        ttk.Button(buttons, text="保存して閉じる", command=self.close_settings).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", self.close_settings)

    def close_settings(self):
        try:
            self.app.settings()
            self.app.save()
            self.app.refresh_mode()
        except (ValueError, OSError) as error:
            messagebox.showerror("設定を確認してください", str(error), parent=self.dialog)
            return False
        self.dialog.destroy()
        self.dialog = None
        return True

    def healing_test(self):
        if self.close_settings():
            self.app.test_healing()

    def capture_action(self, callback):
        if self.close_settings():
            callback()

    def refresh(self):
        app = self.app
        if app.loop:
            self.last_wins = app.loop.wins
            self.last_elapsed = max(0, int(time.monotonic()-app.loop.started))
            healing = app.heal_policy.active
            self.state.set("回復中" if healing else "周回中")
            self.state_label.configure(fg="#b7c99f" if not healing else "#b0c8c8")
            scene = app.last_runtime_scene or app.loop.phase
            self.scene.set("回復" if healing else SCENES.get(scene, "確認中"))
            self.detail.set(app.heal_policy.note if healing else {
                "field": "フィールドを往復して、次の遭遇を待っています。",
                "battle": "ブーストと通常攻撃で戦闘を進めています。" if app.run_bp else "通常攻撃で戦闘を進めています。",
                "victory": "戦利品を確認して、次の旅へ。",
                "levelup": "成長を確認して、次の旅へ。",
            }.get(scene, "画面の切り替わりを確認しています。"))
        elif app.armed:
            self.state.set("開始待機")
            self.state_label.configure(fg=GOLD)
            self.detail.set("5秒以内にゲームを前面に。背景動作ONなら、そのままで大丈夫です。")
        else:
            raw = app.status.get()
            self.state.set("停止中" if raw.startswith(("停止", "撮影できません")) else "待機中")
            self.state_label.configure(fg=INK)
            self.detail.set(raw if raw.startswith(("停止", "判定", "撮影できません")) else "フィールドでF8を押すと、周回を開始します。")
            self.scene.set("—")
        self.output.set("判定のみ · 送信OFF" if app.dry.get() else "キー送信 ON")
        self.health.set(app.heal_status.get() if app.heal_mode.get() else "回復はOFFです。HPを確認してから周回してください。")
        self.wins.set(str(self.last_wins))
        self.elapsed.set(f"{self.last_elapsed//60:02d}:{self.last_elapsed%60:02d}")
        self.start_button.configure(text="一時停止   F8" if app.loop or app.armed else "周回を開始   F8")
        self.root.after(200, self.refresh)
