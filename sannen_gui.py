# -*- coding: utf-8 -*-
"""Giao diện SanNenPro. Chạy: SanNenPro.exe [file.dwg ...]"""
import multiprocessing
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

AUTO = "(Tự nhận)"
NAVY = "#1F3864"


def register_exe():
    """Tạo run.bat để lệnh SANNEN trong AutoCAD gọi được chương trình."""
    if not getattr(sys, "frozen", False):
        return
    d = Path(os.environ.get("LOCALAPPDATA", "")) / "SanNenPro"
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.bat").write_text(f'@echo off\r\nchcp 65001 >nul\r\nstart "" "{sys.executable}" %*\r\n', encoding="utf-8")


def cli(argv):
    import sannen as sn
    lf = os.environ.get("SANNEN_LOG")
    if lf:
        f = open(lf, "a", encoding="utf-8")
        sn.LOG_SINK = lambda m: (f.write(str(m) + "\n"), f.flush())
    try:
        sn.main(argv)
    except Exception:
        sn.log("LỖI:\n" + traceback.format_exc())
        raise


def gui(files, auto=False):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    import sannen as sn

    root = tk.Tk()
    root.title(f"SanNenPro {sn.__version__}: tính khối lượng san nền")
    root.geometry("920x800")
    root.minsize(820, 640)
    st = ttk.Style()
    if "vista" in st.theme_names():
        st.theme_use("vista")
    st.configure("Run.TButton", font=("Segoe UI", 11, "bold"))
    root.option_add("*Font", ("Segoe UI", 10))
    q = queue.Queue()
    result = {}

    head = tk.Frame(root, bg=NAVY)
    head.pack(fill="x")
    tk.Label(head, text="SanNenPro", bg=NAVY, fg="white", font=("Segoe UI", 15, "bold")).pack(side="left", padx=14, pady=8)
    tk.Label(head, text="Lưới ô + TIN, taluy, đường gãy, cân bằng đào đắp", bg=NAVY, fg="#D9E7F5").pack(side="left", pady=8)

    body = ttk.Frame(root, padding=10)
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)
    body.rowconfigure(3, weight=1)

    # bản vẽ
    fb = ttk.LabelFrame(body, text="Bản vẽ DWG/DXF", padding=6)
    fb.grid(row=0, column=0, columnspan=2, sticky="ew")
    fb.columnconfigure(0, weight=1)
    lb = tk.Listbox(fb, height=4, activestyle="none")
    lb.grid(row=0, column=0, rowspan=3, sticky="ew", padx=(0, 6))
    for p in files:
        lb.insert("end", p)

    def add():
        for p in filedialog.askopenfilenames(filetypes=[("Bản vẽ", "*.dwg *.dxf")]):
            lb.insert("end", p)

    def remove():
        for i in reversed(lb.curselection()):
            lb.delete(i)
    ttk.Button(fb, text="Thêm", command=add).grid(row=0, column=1, sticky="ew")
    ttk.Button(fb, text="Bỏ", command=remove).grid(row=1, column=1, sticky="ew")

    # thông số
    fp = ttk.LabelFrame(body, text="Thông số", padding=6)
    fp.grid(row=1, column=0, sticky="nsew", pady=6, padx=(0, 4))
    fp.columnconfigure(1, weight=1)
    V = {}
    rows = [("td", "Cao độ thiết kế (m), trống = đọc layer", ""), ("step", "Bước lưới (m)", "5"),
            ("rot", "Góc lưới (độ), trống = theo ranh", ""), ("k", "Hệ số K", "1"),
            ("taluy_cut", "Mái đào 1:m, trống = không tính", ""), ("taluy_fill", "Mái đắp 1:m, trống = không tính", ""),
            ("strip", "Bóc phong hoá dày (m)", ""), ("pit_slope", "Mái hố móng 1:m, trống = thành đứng", ""),
            ("pit_bottom", "Cao độ đáy hố nếu bản vẽ không ghi", ""),
            ("pile_len", "Dài cọc khoan nhồi (m)", ""), ("pile_dia", "D cọc nếu tim cọc là block (m)", ""),
            ("project", "Tên dự án", "")]
    for i, (k, t, v) in enumerate(rows):
        ttk.Label(fp, text=t).grid(row=i, column=0, sticky="w", pady=1)
        V[k] = tk.StringVar(value=v)
        ttk.Entry(fp, textvariable=V[k], width=16).grid(row=i, column=1, sticky="ew", padx=(6, 0))

    # layer
    fl = ttk.LabelFrame(body, text="Layer", padding=6)
    fl.grid(row=1, column=1, sticky="nsew", pady=6, padx=(4, 0))
    fl.columnconfigure(1, weight=1)
    C = {}
    for i, (k, t) in enumerate((("layer_pts", "Cao độ tự nhiên"), ("layer_tk", "Cao độ thiết kế"),
                                ("layer_bdy", "Ranh giới"), ("layer_brk", "Đường gãy"), ("layer_noslope", "Cạnh không taluy"),
                                ("layer_pit", "Hố móng"), ("layer_pile", "Cọc"))):
        ttk.Label(fl, text=t).grid(row=i, column=0, sticky="w", pady=1)
        C[k] = ttk.Combobox(fl, values=[AUTO])
        C[k].set(AUTO)
        C[k].grid(row=i, column=1, sticky="ew", padx=(6, 0))
    fix = tk.BooleanVar(value=True)
    hml = tk.BooleanVar(value=False)
    x3d = tk.BooleanVar(value=True)
    ttk.Checkbutton(fl, text="Tự sửa chồng lấn, khe hở ranh giới", variable=fix).grid(row=7, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(fl, text="Đối chiếu lưới và nhãn HML trong bản vẽ", variable=hml).grid(row=8, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(fl, text="Xuất 3D: HTML, IFC cho Navisworks, LandXML cho Civil 3D", variable=x3d).grid(row=10, column=0, columnspan=2, sticky="w")
    read_btn = ttk.Button(fl, text="Đọc danh sách layer")
    read_btn.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    # chạy
    fr = ttk.Frame(body)
    fr.grid(row=2, column=0, columnspan=2, sticky="ew")
    fr.columnconfigure(1, weight=1)
    out = tk.StringVar()
    ttk.Label(fr, text="Thư mục kết quả").grid(row=0, column=0, sticky="w")
    ttk.Entry(fr, textvariable=out).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Button(fr, text="Chọn", command=lambda: out.set(filedialog.askdirectory() or out.get())).grid(row=0, column=2)
    run_btn = ttk.Button(fr, text="CHẠY", style="Run.TButton")
    run_btn.grid(row=1, column=0, sticky="ew", pady=6, ipady=3)
    bar = ttk.Progressbar(fr, mode="indeterminate")
    bar.grid(row=1, column=1, sticky="ew", padx=6)
    open_btn = ttk.Button(fr, text="Mở kết quả", state="disabled")
    open_btn.grid(row=1, column=2)

    # nhật ký
    txt = tk.Text(body, wrap="word", height=10, bg="#F7F9FC", relief="flat")
    txt.grid(row=3, column=0, columnspan=2, sticky="nsew")
    sb = ttk.Scrollbar(body, command=txt.yview)
    sb.grid(row=3, column=2, sticky="ns")
    txt.configure(yscrollcommand=sb.set)
    txt.tag_configure("warn", foreground="#7F6000")
    txt.tag_configure("err", foreground="#C62828")
    txt.tag_configure("ok", foreground="#2E7D32")

    def write(m):
        s = str(m)
        tag = "err" if "[LỖI]" in s or s.startswith("LỖI") else "warn" if "[CẢNH BÁO]" in s else "ok" if "[ĐÃ SỬA]" in s else ""
        txt.insert("end", s + "\n", tag)
        txt.see("end")

    def num(k):
        s = V[k].get().strip().replace(",", ".")
        return float(s) if s else None

    def config():
        cfg = dict(sn.DEFAULTS)
        for k in ("td", "rot", "taluy_cut", "taluy_fill", "pit_bottom", "pile_len", "pile_dia"):
            cfg[k] = num(k)
        cfg["strip"] = num("strip") or 0.0
        cfg["pit_slope"] = num("pit_slope") or 0.0
        cfg["step"] = num("step") or 5.0
        cfg["k"] = num("k") or 1.0
        cfg["project"] = V["project"].get().strip()
        cfg["fix_bdy"] = fix.get()
        cfg["use_grid"] = hml.get()
        cfg["export_3d"] = x3d.get()
        for k, c in C.items():
            if c.get() != AUTO:
                cfg[k] = c.get()
        return cfg

    def busy(on):
        run_btn.configure(state="disabled" if on else "normal")
        read_btn.configure(state="disabled" if on else "normal")
        bar.start(12) if on else bar.stop()

    def worker(fn):
        def go():
            try:
                fn()
            except SystemExit as e:
                q.put(f"LỖI: {e}")
            except Exception:
                sn.log("LỖI:\n" + traceback.format_exc())
            q.put(None)
        threading.Thread(target=go, daemon=True).start()

    def do_run():
        ps = list(lb.get(0, "end"))
        if not ps:
            messagebox.showinfo("SanNenPro", "Hãy thêm bản vẽ.")
            return
        try:
            cfg = config()
        except ValueError:
            messagebox.showerror("SanNenPro", "Thông số phải là số.")
            return
        txt.delete("1.0", "end")
        open_btn.configure(state="disabled")
        result.clear()
        busy(True)

        def job():
            r = sn.run(ps, cfg, out.get().strip() or None)
            result["out"] = r["out"]
        worker(job)

    def do_read():
        ps = list(lb.get(0, "end"))
        if not ps:
            return
        busy(True)
        q.put("Đang đọc bản vẽ, file nặng có thể mất vài phút...")

        def job():
            num_l, closed, lines, pile = sn.list_layers(ps)
            q.put(("layers", num_l, closed, lines, pile))
            q.put(f"Đọc xong: {len(num_l)} layer có cao độ, {len(closed)} layer có polyline kín.")
        worker(job)

    def do_open():
        if "out" in result:
            os.startfile(result["out"])

    run_btn.configure(command=do_run)
    read_btn.configure(command=do_read)
    open_btn.configure(command=do_open)

    def poll():
        try:
            while True:
                m = q.get_nowait()
                if m is None:
                    busy(False)
                    if "out" in result:
                        open_btn.configure(state="normal")
                        write("\nHoàn thành.")
                    if auto:
                        root.after(3000, root.destroy)
                elif isinstance(m, tuple):
                    a = [AUTO]
                    C["layer_pts"].configure(values=a + m[1])
                    C["layer_tk"].configure(values=a + m[1])
                    C["layer_bdy"].configure(values=a + m[2])
                    C["layer_brk"].configure(values=a + m[3])
                    C["layer_noslope"].configure(values=a + m[3])
                    C["layer_pit"].configure(values=a + m[2])
                    C["layer_pile"].configure(values=a + m[4])
                else:
                    write(m)
        except queue.Empty:
            pass
        root.after(100, poll)

    sn.LOG_SINK = q.put
    write("Chọn bản vẽ, nhập cao độ thiết kế rồi bấm CHẠY.")
    if auto:
        V["td"].set("-0.6")
        lf = os.environ.get("SANNEN_LOG")
        if lf:
            f = open(lf, "a", encoding="utf-8")
            old = sn.LOG_SINK
            sn.LOG_SINK = lambda m: (f.write(str(m) + "\n"), f.flush(), old(m))
        out.set(os.environ.get("SANNEN_OUT", ""))
        root.after(1500, do_run)
    poll()
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    register_exe()
    args = sys.argv[1:]
    if args[:1] == ["--cli"]:
        cli(args[1:])
    elif args[:1] == ["--auto"]:
        gui(args[1:], auto=True)
    else:
        gui(args)
