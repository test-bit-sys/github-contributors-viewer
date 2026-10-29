#!/usr/bin/env python3
"""
GitHub Contributors Viewer
==========================
A small desktop app (Tkinter) that fetches every contributor of any GitHub
repository, organizes them in a sortable table and lets you search instantly.

Requirements:
    pip install requests
    (Tkinter ships with Python on Windows/macOS; on Linux: sudo apt install python3-tk)

Run:
    python github.py

Tip: a GitHub token (optional) raises the API limit from 60 to 5000 requests/hour.
"""
import csv
import json
import queue
import re
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import requests

DEFAULT_REPO = "https://github.com/storytold/photocraft"
APP_DIR = Path.home() / ".contributors_viewer"
CONFIG_FILE = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "cache"
API = "https://api.github.com"

# (column id, heading, width, anchor, numeric)
COLUMNS = [
    ("rank", "#", 50, "center", True),
    ("login", "Username", 190, "w", False),
    ("name", "Name", 200, "w", False),
    ("contributions", "Contributions", 110, "center", True),
    ("company", "Company", 160, "w", False),
    ("location", "Location", 160, "w", False),
]


# --------------------------------------------------------------------------- #
# GitHub helpers
# --------------------------------------------------------------------------- #
def parse_repo(text: str) -> str:
    """Accepts a full GitHub URL or 'owner/name' and returns 'owner/name'."""
    text = text.strip()
    m = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+)", text)
    if m:
        owner, name = m.group(1), m.group(2)
    else:
        m = re.fullmatch(r"([\w.-]+)/([\w.-]+)", text)
        if not m:
            raise ValueError("Enter a GitHub URL or 'owner/repo'.")
        owner, name = m.group(1), m.group(2)
    if name.endswith(".git"):
        name = name[:-4]
    return f"{owner}/{name}"


def make_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers["Accept"] = "application/vnd.github+json"
    s.headers["User-Agent"] = "contributors-viewer"
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def check_response(r: requests.Response) -> None:
    if r.status_code == 404:
        raise RuntimeError("Repository not found (or it is private).")
    if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
        reset = r.headers.get("X-RateLimit-Reset")
        when = ""
        if reset:
            when = " Resets at " + datetime.fromtimestamp(int(reset)).strftime("%H:%M:%S") + "."
        raise RuntimeError("GitHub API rate limit reached. Add a token to raise it." + when)
    if r.status_code == 401:
        raise RuntimeError("Invalid GitHub token.")
    r.raise_for_status()


def fetch_contributors(session, repo, include_anon, cancel, on_status):
    url = f"{API}/repos/{repo}/contributors"
    params = {"per_page": 100, "anon": "true" if include_anon else "false"}
    people, page = [], 0
    while url:
        if cancel.is_set():
            raise InterruptedError
        r = session.get(url, params=params, timeout=30)
        check_response(r)
        page += 1
        for c in r.json():
            people.append({
                "login": c.get("login") or c.get("name") or c.get("email") or "unknown",
                "name": "",
                "contributions": c.get("contributions", 0),
                "profile": c.get("html_url", ""),
                "type": c.get("type", ""),
                "company": "",
                "location": "",
            })
        on_status(f"Fetched page {page} ({len(people)} contributors)...")
        url = r.links.get("next", {}).get("url")
        params = None  # the "next" link already carries the query string
    return people


def fetch_details(session, people, cancel, on_progress):
    users = [p for p in people if p["type"] == "User"]
    done = {"n": 0}
    lock = threading.Lock()

    def work(p):
        if cancel.is_set():
            return
        r = session.get(f"{API}/users/{p['login']}", timeout=30)
        if r.ok:
            d = r.json()
            p["name"] = d.get("name") or ""
            p["company"] = d.get("company") or ""
            p["location"] = d.get("location") or ""
        elif r.status_code in (403, 429):
            check_response(r)
        with lock:
            done["n"] += 1
            on_progress(done["n"], len(users))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, users))
    if cancel.is_set():
        raise InterruptedError


def organize(people):
    people.sort(key=lambda p: (-p["contributions"], p["login"].lower()))
    for i, p in enumerate(people, 1):
        p["rank"] = i
    return people


# --------------------------------------------------------------------------- #
# Config / cache
# --------------------------------------------------------------------------- #
def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text("utf-8"))
    except Exception:
        return {"repos": [DEFAULT_REPO], "token": "", "details": False, "anon": True}


def save_config(cfg):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), "utf-8")


def cache_path(repo):
    return CACHE_DIR / (repo.replace("/", "__") + ".json")


def load_cache(repo):
    try:
        return json.loads(cache_path(repo).read_text("utf-8"))
    except Exception:
        return None


def save_cache(repo, people):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(repo).write_text(json.dumps(people, ensure_ascii=False, indent=2), "utf-8")


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GitHub Contributors Viewer")
        self.geometry("980x640")
        self.minsize(820, 520)

        self.cfg = load_config()
        self.people = []          # full data set
        self.repo = ""            # current "owner/name"
        self.sort_col, self.sort_rev = "rank", False
        self.msgs = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None

        self._build_ui()
        self._bind_keys()
        self.after(100, self._poll)

        # Load the cached copy of the last repo, if any.
        self._load_from_cache(parse_repo_safe(self.repo_var.get()))

    # ---- UI construction -------------------------------------------------- #
    def _build_ui(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=26)
        style.configure("Big.TEntry", padding=4)

        # Row 1: repository + token
        top = ttk.LabelFrame(self, text="Project", padding=8)
        top.pack(fill="x", padx=10, pady=(10, 4))
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Repository URL:").grid(row=0, column=0, sticky="w")
        self.repo_var = tk.StringVar(value=(self.cfg.get("repos") or [DEFAULT_REPO])[0])
        self.repo_box = ttk.Combobox(top, textvariable=self.repo_var,
                                     values=self.cfg.get("repos", []))
        self.repo_box.grid(row=0, column=1, sticky="ew", padx=6)
        self.fetch_btn = ttk.Button(top, text="Fetch contributors", command=self.start_fetch)
        self.fetch_btn.grid(row=0, column=2, padx=(0, 4))
        self.cancel_btn = ttk.Button(top, text="Cancel", command=self.cancel.set, state="disabled")
        self.cancel_btn.grid(row=0, column=3)

        ttk.Label(top, text="GitHub token (optional):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.token_var = tk.StringVar(value=self.cfg.get("token", ""))
        ttk.Entry(top, textvariable=self.token_var, show="*").grid(
            row=1, column=1, sticky="ew", padx=6, pady=(6, 0))

        opts = ttk.Frame(top)
        opts.grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))
        self.details_var = tk.BooleanVar(value=self.cfg.get("details", False))
        self.anon_var = tk.BooleanVar(value=self.cfg.get("anon", True))
        ttk.Checkbutton(opts, text="Fetch real names / company / location (slower)",
                        variable=self.details_var).pack(anchor="w")
        ttk.Checkbutton(opts, text="Include anonymous contributors",
                        variable=self.anon_var).pack(anchor="w")

        # Row 2: search + filters
        bar = ttk.Frame(self, padding=(10, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        self.search_entry = ttk.Entry(bar, textvariable=self.search_var, width=36, style="Big.TEntry")
        self.search_entry.pack(side="left", padx=6)
        ttk.Button(bar, text="Clear", command=lambda: self.search_var.set("")).pack(side="left")

        ttk.Label(bar, text="Min contributions:").pack(side="left", padx=(18, 4))
        self.min_var = tk.IntVar(value=0)
        spin = ttk.Spinbox(bar, from_=0, to=100000, width=7, textvariable=self.min_var,
                           command=self.refresh_table)
        spin.pack(side="left")
        spin.bind("<KeyRelease>", lambda e: self.refresh_table())

        self.count_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.count_var).pack(side="right")

        # Table
        frame = ttk.Frame(self, padding=(10, 0))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS],
                                 show="headings", selectmode="browse")
        for cid, head, width, anchor, _ in COLUMNS:
            self.tree.heading(cid, text=head, command=lambda c=cid: self.sort_by(c))
            self.tree.column(cid, width=width, anchor=anchor, stretch=(cid != "rank"))
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#f4f6f8")

        self.tree.bind("<Double-1>", lambda e: self.open_profile())
        self.tree.bind("<Return>", lambda e: self.open_profile())
        self.tree.bind("<Button-3>", self._popup)
        self.tree.bind("<Button-2>", self._popup)  # macOS

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Open profile in browser", command=self.open_profile)
        self.menu.add_command(label="Copy username", command=lambda: self.copy_field("login"))
        self.menu.add_command(label="Copy profile link", command=lambda: self.copy_field("profile"))

        # Bottom: export + status
        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Export CSV", command=lambda: self.export("csv")).pack(side="left")
        ttk.Button(bottom, text="Export JSON", command=lambda: self.export("json")).pack(side="left", padx=4)
        ttk.Button(bottom, text="Export Markdown", command=lambda: self.export("md")).pack(side="left")
        ttk.Label(bottom, text="(exports the rows currently shown)",
                  foreground="#666").pack(side="left", padx=8)

        self.progress = ttk.Progressbar(bottom, length=180, mode="determinate")
        self.progress.pack(side="right")
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="right", padx=10)

    def _bind_keys(self):
        self.bind("<Control-f>", lambda e: (self.search_entry.focus_set(),
                                            self.search_entry.select_range(0, "end")))
        self.search_entry.bind("<Escape>", lambda e: self.search_var.set(""))
        self.repo_box.bind("<Return>", lambda e: self.start_fetch())
        self.repo_box.bind("<<ComboboxSelected>>",
                           lambda e: self._load_from_cache(parse_repo_safe(self.repo_var.get())))

    # ---- Table ------------------------------------------------------------ #
    def refresh_table(self):
        query = self.search_var.get().strip().lower()
        terms = query.split()
        try:
            min_c = int(self.min_var.get())
        except (tk.TclError, ValueError):
            min_c = 0

        rows = []
        for p in self.people:
            if p["contributions"] < min_c:
                continue
            haystack = " ".join(str(p.get(k, "")) for k in
                                ("login", "name", "company", "location")).lower()
            if all(t in haystack for t in terms):
                rows.append(p)

        numeric = {c[0] for c in COLUMNS if c[4]}
        key = self.sort_col
        rows.sort(key=lambda p: p[key] if key in numeric else str(p.get(key, "")).lower(),
                  reverse=self.sort_rev)

        self.tree.delete(*self.tree.get_children())
        for i, p in enumerate(rows):
            self.tree.insert("", "end", iid=str(p["rank"]),
                             values=[p.get(c[0], "") for c in COLUMNS],
                             tags=("odd",) if i % 2 else ())
        self._shown = rows
        total = sum(p["contributions"] for p in self.people)
        anon = sum(1 for p in self.people if p["type"] == "Anonymous")
        self.count_var.set(f"Showing {len(rows)} of {len(self.people)} contributors"
                           f" ({anon} anonymous)  |  {total} total contributions")
        self._update_headings()

    def sort_by(self, col):
        if self.sort_col == col:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_col = col
            self.sort_rev = col == "contributions"
        self.refresh_table()

    def _update_headings(self):
        for cid, head, *_ in COLUMNS:
            arrow = ""
            if cid == self.sort_col:
                arrow = "  ▼" if self.sort_rev else "  ▲"
            self.tree.heading(cid, text=head + arrow)

    # ---- Actions ---------------------------------------------------------- #
    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        rank = int(sel[0])
        return next((p for p in self.people if p["rank"] == rank), None)

    def _popup(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def open_profile(self):
        p = self._selected()
        if p and p["profile"]:
            webbrowser.open(p["profile"])

    def copy_field(self, field):
        p = self._selected()
        if p:
            self.clipboard_clear()
            self.clipboard_append(p.get(field, ""))
            self.status_var.set(f"Copied: {p.get(field, '')}")

    def export(self, fmt):
        rows = getattr(self, "_shown", [])
        if not rows:
            messagebox.showinfo("Export", "Nothing to export.")
            return
        base = (self.repo or "contributors").replace("/", "_")
        ext = {"csv": ".csv", "json": ".json", "md": ".md"}[fmt]
        path = filedialog.asksaveasfilename(defaultextension=ext, initialfile=base + ext)
        if not path:
            return
        fields = ["rank", "login", "name", "contributions", "company", "location", "profile"]
        if fmt == "csv":
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
        elif fmt == "json":
            Path(path).write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
        else:
            lines = [f"# Contributors of {self.repo}", "",
                     "| # | Username | Name | Contributions | Company | Location |",
                     "|---|----------|------|---------------|---------|----------|"]
            for p in rows:
                user = f"[{p['login']}]({p['profile']})" if p["profile"] else p["login"]
                lines.append(f"| {p['rank']} | {user} | {p['name']} | {p['contributions']} "
                             f"| {p['company']} | {p['location']} |")
            Path(path).write_text("\n".join(lines), "utf-8")
        self.status_var.set(f"Exported {len(rows)} rows to {path}")

    # ---- Fetching (background thread) ------------------------------------- #
    def start_fetch(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            repo = parse_repo(self.repo_var.get())
        except ValueError as e:
            messagebox.showerror("Invalid repository", str(e))
            return

        self.cancel.clear()
        self.fetch_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.status_var.set(f"Fetching {repo}...")

        token = self.token_var.get().strip()
        details, anon = self.details_var.get(), self.anon_var.get()

        def run():
            try:
                s = make_session(token)
                people = fetch_contributors(
                    s, repo, anon, self.cancel,
                    lambda t: self.msgs.put(("status", t)))
                if details:
                    self.msgs.put(("mode", "determinate"))
                    fetch_details(s, people, self.cancel,
                                  lambda n, t: self.msgs.put(("progress", n, t)))
                self.msgs.put(("done", repo, organize(people)))
            except InterruptedError:
                self.msgs.put(("error", "Cancelled."))
            except requests.RequestException as e:
                self.msgs.put(("error", f"Network error: {e}"))
            except Exception as e:  # noqa: BLE001
                self.msgs.put(("error", str(e)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _poll(self):
        try:
            while True:
                msg = self.msgs.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "mode":
                    self.progress.stop()
                    self.progress.config(mode="determinate", value=0, maximum=100)
                elif kind == "progress":
                    n, total = msg[1], msg[2]
                    self.progress.config(value=100 * n / max(total, 1))
                    self.status_var.set(f"Fetching details {n}/{total}...")
                elif kind == "done":
                    self._finish()
                    self.repo, self.people = msg[1], msg[2]
                    save_cache(self.repo, self.people)
                    self._remember_repo(self.repo)
                    self.refresh_table()
                    self.status_var.set(f"Done: {len(self.people)} contributors.")
                    self.search_entry.focus_set()
                elif kind == "error":
                    self._finish()
                    self.status_var.set(msg[1])
                    if msg[1] != "Cancelled.":
                        messagebox.showerror("Error", msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self):
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self.fetch_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")

    # ---- Cache / config --------------------------------------------------- #
    def _load_from_cache(self, repo):
        if not repo:
            return
        data = load_cache(repo)
        if data:
            self.repo, self.people = repo, data
            self.refresh_table()
            self.status_var.set(f"Loaded {len(data)} contributors from cache. "
                                f"Press Fetch to refresh.")

    def _remember_repo(self, repo):
        url = f"https://github.com/{repo}"
        repos = [url] + [r for r in self.cfg.get("repos", []) if r != url]
        self.cfg.update(repos=repos[:15], token=self.token_var.get().strip(),
                        details=self.details_var.get(), anon=self.anon_var.get())
        save_config(self.cfg)
        self.repo_box.config(values=self.cfg["repos"])
        self.repo_var.set(url)


def parse_repo_safe(text):
    try:
        return parse_repo(text)
    except ValueError:
        return ""


if __name__ == "__main__":
    App().mainloop()