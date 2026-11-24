"""Local desktop controls for the reminder service."""
from contextlib import closing
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import time


def open_window(path, connect, planning):
    root = tk.Tk()
    root.title("Paco")
    root.geometry("740x440")
    panel = ttk.Frame(root, padding=16)
    panel.pack(fill="both", expand=True)
    status = tk.StringVar()
    ttk.Label(panel,textvariable=status, wraplength=680).pack(anchor="w", pady=6)
    table = ttk.Treeview(panel,columns=("state","title"),show="headings",selectmode="browse")
    table.heading("state",text="Status")
    table.heading("title",text="Task")
    table.column("state",width=85,stretch=False)
    table.pack(fill="both",expand=True)

    def refresh():
        selected = table.selection()
        with closing(connect(path)) as db:
            now = time.time()
            wait = planning.reason_to_wait(db,now)
            best = planning.ranked(db,now).fetchone()
            status.set(wait or ("Next: " + best["title"] if best else "No tasks ready"))
            table.delete(*table.get_children())
            for row in db.execute("SELECT * FROM task WHERE state!='done' ORDER BY priority DESC,due,id"):
                table.insert("", "end", iid=str(row["id"]),values=(row["state"],row["title"]))
        if selected and table.exists(selected[0]):
            table.selection_set(selected[0])

    def apply(action):
        selected = table.selection()
        if not selected:
            return
        args = [sys.executable,str(Path(__file__).with_name("paco.py")),"--db",str(path),action,selected[0]]
        if action in ("start","snooze"):
            args.append("25" if action=="start" else "15")
        result = subprocess.run(args,capture_output=True,text=True)
        if result.returncode:
            messagebox.showerror("Paco",result.stderr)
        refresh()

    bar = ttk.Frame(panel)
    bar.pack(fill="x",pady=8)
    for label, action in [("Focus 25 min","start"),("Snooze 15 min","snooze"),("Blocked","block"),
                          ("Resume","resume"),("Done","done")]:
        ttk.Button(bar,text=label,command=lambda a=action:apply(a)).pack(side="left",padx=2)
    def poll():
        refresh()
        root.after(15000,poll)
    poll()
    root.mainloop()
