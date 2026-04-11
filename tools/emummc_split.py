#!/usr/bin/env python3
"""
emummc_split.py - hekate NAND Split/Join Tool

Handles two formats:
  Backup  : rawnand.bin.00, rawnand.bin.01, ... (1 GB or 2 GB chunks)
  emuMMC  : eMMC/00, 01, ... + BOOT0/BOOT1 + file_based marker + emummc.ini

Requires: ttkbootstrap  (pip install ttkbootstrap)
"""

import os
import sys
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
except ImportError:
    print("Missing dependency: pip install ttkbootstrap")
    sys.exit(1)

# ── Constants (matches hekate source) ────────────────────────────────────────
EMUMMC_SPLIT = 0xFE000000          # fe_emummc_tools.c - emuMMC file-based part size
BOOT_SIZE    = 0x2000 * 512        # 4 MiB  (0x2000 sectors * 512)
SIZE_2GB     = 0x80000000          # fe_emmc_tools.c - backup split (large SD)
SIZE_1GB     = 0x40000000          # fe_emmc_tools.c - backup split (small SD <=8GB)
VERSION      = "1.0.0"


# ── Core: Backup ─────────────────────────────────────────────────────────────

def backup_split(rawnand, out_dir, chunk_size, progress_cb, log_cb):
    total = os.path.getsize(rawnand)
    log_cb(f"Input   : {rawnand}")
    log_cb(f"Size    : {total:,} bytes  ({total / (1024**3):.2f} GB)")
    log_cb(f"Chunk   : {chunk_size // (1024**3)} GB  ({chunk_size:#010x})")
    log_cb("")

    os.makedirs(out_dir, exist_ok=True)
    written = 0
    with open(rawnand, "rb") as f:
        part = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            name = f"rawnand.bin.{part:02d}"
            with open(os.path.join(out_dir, name), "wb") as o:
                o.write(chunk)
            written += len(chunk)
            progress_cb(written / total * 100)
            log_cb(f"  {name}  ({len(chunk):,} bytes)")
            part += 1

    log_cb(f"\nDone. {part} file(s) written to: {out_dir}")


def backup_join(in_dir, out_file, progress_cb, log_cb):
    parts = []
    i = 0
    while os.path.exists(os.path.join(in_dir, f"rawnand.bin.{i:02d}")):
        parts.append(os.path.join(in_dir, f"rawnand.bin.{i:02d}"))
        i += 1

    if not parts:
        raise FileNotFoundError("No parts found — expected rawnand.bin.00, rawnand.bin.01, ...")

    total = sum(os.path.getsize(p) for p in parts)
    log_cb(f"Parts   : {len(parts)}")
    log_cb(f"Total   : {total:,} bytes  ({total / (1024**3):.2f} GB)")
    log_cb(f"Output  : {out_file}")
    log_cb("")

    written = 0
    with open(out_file, "wb") as out:
        for p in parts:
            sz = os.path.getsize(p)
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out)
            written += sz
            progress_cb(written / total * 100)
            log_cb(f"  {os.path.basename(p)}  ({sz:,} bytes)")

    log_cb(f"\nDone. RAWNAND saved to: {out_file}")


# ── Core: emuMMC ──────────────────────────────────────────────────────────────

def emummc_split(rawnand, boot0, boot1, out_dir, slot, progress_cb, log_cb):
    emmc_dir = os.path.join(out_dir, slot, "eMMC")
    os.makedirs(emmc_dir, exist_ok=True)

    total = os.path.getsize(rawnand)
    log_cb(f"Input   : {rawnand}")
    log_cb(f"Size    : {total:,} bytes  ({total / (1024**3):.2f} GB)")
    log_cb(f"Slot    : {slot}")
    log_cb(f"Output  : {emmc_dir}")
    log_cb("")

    written = 0
    with open(rawnand, "rb") as f:
        part = 0
        while True:
            chunk = f.read(EMUMMC_SPLIT)
            if not chunk:
                break
            fname = f"{part:02d}"
            with open(os.path.join(emmc_dir, fname), "wb") as o:
                o.write(chunk)
            written += len(chunk)
            progress_cb(written / total * 85)
            log_cb(f"  {fname}  ({len(chunk):,} bytes)")
            part += 1

    for bname, bsrc in [("BOOT0", boot0), ("BOOT1", boot1)]:
        bsz = os.path.getsize(bsrc)
        if bsz != BOOT_SIZE:
            log_cb(f"  WARNING: {bname} size {bsz} != expected {BOOT_SIZE} (4 MiB)")
        shutil.copy2(bsrc, os.path.join(emmc_dir, bname))
        log_cb(f"  Copied {bname}  ({bsz:,} bytes)")

    open(os.path.join(out_dir, slot, "file_based"), "wb").close()
    log_cb("  Created file_based marker")

    slot_id = "".join(c for c in slot if c.isdigit()) or "0"
    ini = (
        f"[emummc]\nenabled=1\nsector=0x0\n"
        f"path=emuMMC/{slot}\nid=0x{int(slot_id):04x}\n"
        f"nintendo_path=emuMMC/{slot}/Nintendo\n"
    )
    with open(os.path.join(out_dir, "emummc.ini"), "w") as f:
        f.write(ini)
    log_cb("  Created emummc.ini")

    progress_cb(100)
    log_cb(f"\nDone. Copy emuMMC/ to the root of your SD card.")


def emummc_join(emmc_dir, out_rawnand, out_boot0, out_boot1, progress_cb, log_cb):
    parts = []
    i = 0
    while os.path.exists(os.path.join(emmc_dir, f"{i:02d}")):
        parts.append(os.path.join(emmc_dir, f"{i:02d}"))
        i += 1

    if not parts:
        raise FileNotFoundError("No parts found — expected 00, 01, 02, ...")

    total = sum(os.path.getsize(p) for p in parts)
    log_cb(f"Parts   : {len(parts)}")
    log_cb(f"Total   : {total:,} bytes  ({total / (1024**3):.2f} GB)")
    log_cb(f"Output  : {out_rawnand}")
    log_cb("")

    written = 0
    with open(out_rawnand, "wb") as out:
        for p in parts:
            sz = os.path.getsize(p)
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out)
            written += sz
            progress_cb(written / total * 100)
            log_cb(f"  {os.path.basename(p)}  ({sz:,} bytes)")

    for bname, bpath in [("BOOT0", out_boot0), ("BOOT1", out_boot1)]:
        if bpath:
            src = os.path.join(emmc_dir, bname)
            if os.path.exists(src):
                shutil.copy2(src, bpath)
                log_cb(f"  Extracted {bname} → {bpath}")
            else:
                log_cb(f"  WARNING: {bname} not found in source, skipping")

    progress_cb(100)
    log_cb(f"\nDone. RAWNAND saved to: {out_rawnand}")


# ── GUI ───────────────────────────────────────────────────────────────────────

class App(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title(f"hekate NAND Tool v{VERSION}")
        self.geometry("740x860")
        self.resizable(False, False)
        self._build_ui()
        self._center()

    def _center(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 740) // 2
        y = (self.winfo_screenheight() - 860) // 2
        self.geometry(f"740x860+{x}+{y}")

    def _build_ui(self):
        # Header
        hdr = ttk.Frame(self, padding="20 15 20 10")
        hdr.pack(fill=X)
        ttk.Label(hdr, text="hekate NAND Tool",
                  font=("Segoe UI", 18, "bold")).pack(anchor=W)
        ttk.Label(hdr, text="Split and join NAND backups and emuMMC SD files",
                  font=("Segoe UI", 10), bootstyle="secondary").pack(anchor=W)

        ttk.Separator(self, orient=HORIZONTAL).pack(fill=X, padx=20)

        # Notebook — 4 tabs
        nb = ttk.Notebook(self, bootstyle="primary", padding="20 10 20 0")
        nb.pack(fill=BOTH, padx=20, pady=10)

        self._tab_backup_split(nb)
        self._tab_backup_join(nb)
        self._tab_emummc_split(nb)
        self._tab_emummc_join(nb)

        # Log
        lf = ttk.LabelFrame(self, text="Log", padding="10", bootstyle="secondary")
        lf.pack(fill=BOTH, expand=True, padx=20, pady=(0, 10))

        self.log_box = tk.Text(lf, height=10, state=DISABLED,
                               font=("Consolas", 8),
                               bg="#1e1e2e", fg="#cdd6f4",
                               relief=FLAT, bd=0, wrap=WORD)
        sb = ttk.Scrollbar(lf, orient=VERTICAL,
                           command=self.log_box.yview, bootstyle="primary-round")
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        self.log_box.pack(fill=BOTH, expand=True)

        # Progress
        pf = ttk.Frame(self, padding="20 0 20 15")
        pf.pack(fill=X)
        self.progress = ttk.Progressbar(pf, maximum=100, bootstyle="success-striped")
        self.progress.pack(fill=X)
        self.status_lbl = ttk.Label(pf, text="Ready.",
                                    font=("Segoe UI", 8), bootstyle="secondary")
        self.status_lbl.pack(anchor=W, pady=(4, 0))

    # ── Tab: Backup Split ─────────────────────────────────────────────────────

    def _tab_backup_split(self, nb):
        tab = ttk.Frame(nb, padding="10")
        nb.add(tab, text="  Backup Split  ")

        self.bs_rawnand  = tk.StringVar()
        self.bs_out_dir  = tk.StringVar()
        self.bs_chunkvar = tk.StringVar(value="2GB")

        self._file_row(tab, "RAWNAND dump", self.bs_rawnand,
                       self._pick_file(self.bs_rawnand, "Select RAWNAND dump",
                                       [("BIN files", "*.bin"), ("All", "*.*")]))
        self._file_row(tab, "Output folder", self.bs_out_dir,
                       self._pick_dir(self.bs_out_dir, "Select output folder"))

        # Chunk size selector
        cr = ttk.Frame(tab)
        cr.pack(fill=X, pady=(0, 8))
        ttk.Label(cr, text="Chunk size", font=("Segoe UI", 9, "bold"),
                  width=14).pack(side=LEFT)
        for label in ("2GB", "1GB"):
            ttk.Radiobutton(cr, text=label, variable=self.bs_chunkvar,
                            value=label, bootstyle="primary").pack(side=LEFT, padx=(0, 15))
        ttk.Label(cr, text="2 GB for large SD cards, 1 GB for ≤8 GB",
                  font=("Segoe UI", 8), bootstyle="secondary").pack(side=LEFT)

        ttk.Separator(tab, orient=HORIZONTAL).pack(fill=X, pady=10)
        ttk.Button(tab, text="Start Split", bootstyle="success", width=18,
                   command=self._run_backup_split).pack(anchor=E)

    # ── Tab: Backup Join ──────────────────────────────────────────────────────

    def _tab_backup_join(self, nb):
        tab = ttk.Frame(nb, padding="10")
        nb.add(tab, text="  Backup Join  ")

        self.bj_in_dir   = tk.StringVar()
        self.bj_out_file = tk.StringVar()

        self._file_row(tab, "Parts folder", self.bj_in_dir,
                       self._pick_dir(self.bj_in_dir,
                                      "Select folder containing rawnand.bin.00, .01 ..."))
        self._file_row(tab, "Output RAWNAND", self.bj_out_file,
                       self._pick_save(self.bj_out_file, "Save RAWNAND as",
                                       [("BIN files", "*.bin"), ("All", "*.*")]))

        ttk.Label(tab,
                  text="Joins rawnand.bin.00, rawnand.bin.01, ... into a single file.",
                  font=("Segoe UI", 8), bootstyle="secondary").pack(anchor=W, pady=(0, 8))

        ttk.Separator(tab, orient=HORIZONTAL).pack(fill=X, pady=10)
        ttk.Button(tab, text="Start Join", bootstyle="success", width=18,
                   command=self._run_backup_join).pack(anchor=E)

    # ── Tab: emuMMC Split ─────────────────────────────────────────────────────

    def _tab_emummc_split(self, nb):
        tab = ttk.Frame(nb, padding="10")
        nb.add(tab, text="  emuMMC Split  ")

        self.es_rawnand = tk.StringVar()
        self.es_boot0   = tk.StringVar()
        self.es_boot1   = tk.StringVar()
        self.es_out_dir = tk.StringVar()
        self.es_slot    = tk.StringVar(value="SD00")

        self._file_row(tab, "RAWNAND dump", self.es_rawnand,
                       self._pick_file(self.es_rawnand, "Select RAWNAND dump",
                                       [("BIN files", "*.bin"), ("All", "*.*")]))
        self._file_row(tab, "BOOT0 dump", self.es_boot0,
                       self._pick_file(self.es_boot0, "Select BOOT0 dump",
                                       [("BIN files", "*.bin"), ("All", "*.*")]))
        self._file_row(tab, "BOOT1 dump", self.es_boot1,
                       self._pick_file(self.es_boot1, "Select BOOT1 dump",
                                       [("BIN files", "*.bin"), ("All", "*.*")]))
        self._file_row(tab, "Output folder", self.es_out_dir,
                       self._pick_dir(self.es_out_dir,
                                      "Select output folder (emuMMC/ will be created here)"))

        # Slot name
        sr = ttk.Frame(tab)
        sr.pack(fill=X, pady=(0, 8))
        ttk.Label(sr, text="Slot name", font=("Segoe UI", 9, "bold"),
                  width=14).pack(side=LEFT)
        ttk.Entry(sr, textvariable=self.es_slot,
                  width=8, font=("Segoe UI", 9)).pack(side=LEFT, padx=(0, 8))
        ttk.Label(sr, text="e.g. SD00, SD01, RAW0 ...",
                  font=("Segoe UI", 8), bootstyle="secondary").pack(side=LEFT)

        ttk.Label(tab,
                  text=f"Splits into ~3.97 GB chunks (0x{EMUMMC_SPLIT:08X} bytes). "
                       "Adds BOOT0, BOOT1, file_based marker and emummc.ini.",
                  font=("Segoe UI", 8), bootstyle="secondary",
                  wraplength=650).pack(anchor=W, pady=(0, 4))

        ttk.Separator(tab, orient=HORIZONTAL).pack(fill=X, pady=10)
        ttk.Button(tab, text="Start Split", bootstyle="success", width=18,
                   command=self._run_emummc_split).pack(anchor=E)

    # ── Tab: emuMMC Join ──────────────────────────────────────────────────────

    def _tab_emummc_join(self, nb):
        tab = ttk.Frame(nb, padding="10")
        nb.add(tab, text="  emuMMC Join  ")

        self.ej_emmc_dir = tk.StringVar()
        self.ej_rawnand  = tk.StringVar()
        self.ej_boot0    = tk.StringVar()
        self.ej_boot1    = tk.StringVar()

        self._file_row(tab, "eMMC/ folder", self.ej_emmc_dir,
                       self._pick_dir(self.ej_emmc_dir,
                                      "Select eMMC/ folder (contains 00, 01, BOOT0, BOOT1)"))
        self._file_row(tab, "Output RAWNAND", self.ej_rawnand,
                       self._pick_save(self.ej_rawnand, "Save RAWNAND as",
                                       [("BIN files", "*.bin"), ("All", "*.*")]))

        ttk.Label(tab, text="Optional — extract boot partitions:",
                  font=("Segoe UI", 9, "bold"), bootstyle="secondary").pack(anchor=W, pady=(8, 2))

        self._file_row(tab, "Output BOOT0", self.ej_boot0,
                       self._pick_save(self.ej_boot0, "Save BOOT0 as",
                                       [("BIN files", "*.bin"), ("All", "*.*")]))
        self._file_row(tab, "Output BOOT1", self.ej_boot1,
                       self._pick_save(self.ej_boot1, "Save BOOT1 as",
                                       [("BIN files", "*.bin"), ("All", "*.*")]))

        ttk.Label(tab,
                  text="Joins 00, 01, 02, ... into a single RAWNAND dump.",
                  font=("Segoe UI", 8), bootstyle="secondary").pack(anchor=W, pady=(0, 4))

        ttk.Separator(tab, orient=HORIZONTAL).pack(fill=X, pady=10)
        ttk.Button(tab, text="Start Join", bootstyle="success", width=18,
                   command=self._run_emummc_join).pack(anchor=E)

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _file_row(self, parent, label, var, cmd):
        row = ttk.Frame(parent)
        row.pack(fill=X, pady=(0, 8))
        ttk.Label(row, text=label, font=("Segoe UI", 9, "bold"),
                  width=14).pack(side=LEFT)
        ttk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                  width=52).pack(side=LEFT, padx=(0, 5))
        ttk.Button(row, text="Browse", bootstyle="secondary",
                   command=cmd, width=7).pack(side=LEFT)

    def _pick_file(self, var, title, ftypes):
        def cmd():
            p = filedialog.askopenfilename(title=title, filetypes=ftypes)
            if p:
                var.set(p)
        return cmd

    def _pick_dir(self, var, title):
        def cmd():
            p = filedialog.askdirectory(title=title)
            if p:
                var.set(p)
        return cmd

    def _pick_save(self, var, title, ftypes):
        def cmd():
            p = filedialog.asksaveasfilename(title=title, filetypes=ftypes,
                                              defaultextension=".bin")
            if p:
                var.set(p)
        return cmd

    # ── Log / progress helpers ────────────────────────────────────────────────

    def _log(self, msg):
        self.log_box.configure(state=NORMAL)
        self.log_box.insert(END, msg + "\n")
        self.log_box.see(END)
        self.log_box.configure(state=DISABLED)

    def _set_progress(self, val):
        self.progress["value"] = val
        self.status_lbl.config(text=f"{val:.1f}%")

    def _clear_log(self):
        self.log_box.configure(state=NORMAL)
        self.log_box.delete("1.0", END)
        self.log_box.configure(state=DISABLED)

    def _launch(self, status, fn, done_msg):
        self._clear_log()
        self._set_progress(0)
        self.status_lbl.config(text=status, bootstyle="warning")

        def worker():
            try:
                fn()
                self.after(0, self.status_lbl.config,
                           {"text": done_msg, "bootstyle": "success"})
            except Exception as e:
                self.after(0, self._log, f"ERROR: {e}")
                self.after(0, self.status_lbl.config,
                           {"text": "Failed.", "bootstyle": "danger"})
                self.after(0, messagebox.showerror, "Error", str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ── Run: Backup Split ─────────────────────────────────────────────────────

    def _run_backup_split(self):
        rawnand  = self.bs_rawnand.get().strip()
        out_dir  = self.bs_out_dir.get().strip()
        chunk_sz = SIZE_2GB if self.bs_chunkvar.get() == "2GB" else SIZE_1GB

        if not rawnand or not out_dir:
            messagebox.showerror("Missing fields", "Please fill in RAWNAND dump and Output folder.")
            return
        if not os.path.exists(rawnand):
            messagebox.showerror("File not found", rawnand)
            return

        self._launch("Splitting...",
                     lambda: backup_split(rawnand, out_dir, chunk_sz,
                                          lambda v: self.after(0, self._set_progress, v),
                                          lambda m: self.after(0, self._log, m)),
                     "Split complete!")

    # ── Run: Backup Join ──────────────────────────────────────────────────────

    def _run_backup_join(self):
        in_dir   = self.bj_in_dir.get().strip()
        out_file = self.bj_out_file.get().strip()

        if not in_dir or not out_file:
            messagebox.showerror("Missing fields", "Please fill in Parts folder and Output RAWNAND.")
            return
        if not os.path.isdir(in_dir):
            messagebox.showerror("Not found", f"Folder not found:\n{in_dir}")
            return

        self._launch("Joining...",
                     lambda: backup_join(in_dir, out_file,
                                         lambda v: self.after(0, self._set_progress, v),
                                         lambda m: self.after(0, self._log, m)),
                     "Join complete!")

    # ── Run: emuMMC Split ─────────────────────────────────────────────────────

    def _run_emummc_split(self):
        rawnand = self.es_rawnand.get().strip()
        boot0   = self.es_boot0.get().strip()
        boot1   = self.es_boot1.get().strip()
        out_dir = self.es_out_dir.get().strip()
        slot    = self.es_slot.get().strip() or "SD00"

        missing = [n for n, v in [("RAWNAND dump", rawnand), ("BOOT0 dump", boot0),
                                   ("BOOT1 dump", boot1), ("Output folder", out_dir)] if not v]
        if missing:
            messagebox.showerror("Missing fields", "Please fill in:\n" +
                                 "\n".join(f"  • {n}" for n in missing))
            return
        for label, path in [("RAWNAND", rawnand), ("BOOT0", boot0), ("BOOT1", boot1)]:
            if not os.path.exists(path):
                messagebox.showerror("File not found", f"{label}: {path}")
                return

        self._launch("Splitting emuMMC...",
                     lambda: emummc_split(rawnand, boot0, boot1, out_dir, slot,
                                          lambda v: self.after(0, self._set_progress, v),
                                          lambda m: self.after(0, self._log, m)),
                     "emuMMC split complete!")

    # ── Run: emuMMC Join ──────────────────────────────────────────────────────

    def _run_emummc_join(self):
        emmc_dir  = self.ej_emmc_dir.get().strip()
        out_nand  = self.ej_rawnand.get().strip()
        out_boot0 = self.ej_boot0.get().strip() or None
        out_boot1 = self.ej_boot1.get().strip() or None

        if not emmc_dir or not out_nand:
            messagebox.showerror("Missing fields", "Please fill in eMMC/ folder and Output RAWNAND.")
            return
        if not os.path.isdir(emmc_dir):
            messagebox.showerror("Not found", f"Folder not found:\n{emmc_dir}")
            return

        self._launch("Joining emuMMC...",
                     lambda: emummc_join(emmc_dir, out_nand, out_boot0, out_boot1,
                                         lambda v: self.after(0, self._set_progress, v),
                                         lambda m: self.after(0, self._log, m)),
                     "emuMMC join complete!")


if __name__ == "__main__":
    app = App()
    app.mainloop()
