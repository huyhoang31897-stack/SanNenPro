#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SanNenPro - Tính khối lượng san nền từ bản vẽ CAD (lưới ô vuông + mô hình TIN).

Đầu vào : DWG/DXF có cao độ tự nhiên (TEXT/POINT) và ranh giới (polyline kín).
Đầu ra  : Excel khối lượng, DXF/DWG mặt bằng san nền, PDF báo cáo.

Có taluy, đường gãy, tự sửa ranh giới. Hai cách tính chạy song song:
  - Lưới ô (giống HML): V = S x trung bình |h| các đỉnh, tách theo đường 0 đào/đắp.
  - TIN chính xác     : chồng mặt TIN lên cao độ thiết kế, tích phân từng tam giác.

Ví dụ:
  python sannen.py "ban ve.dwg" --td -0.6 --step 5
  python sannen.py a.dwg b.dwg --config config.json --out KetQua
  python sannen.py "ban ve.dwg" --use-grid        # dùng lại lưới HML có sẵn để đối chiếu
  python sannen.py "ban ve.dwg" --td 2.5 --taluy-dao 1 --taluy-dap 1.5 --boc 0.3
  python sannen.py "ban ve.dwg" --list-layers
  python sannen.py "ban ve.dwg" --td 2.5 --json --no-dwg
  python sannen.py "ban ve.dwg" --td 2.5 --3d          # thêm HTML 3D, IFC, LandXML
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import multiprocessing
import os
import pickle
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import ezdxf
import shapely
from ezdxf.addons import iterdxf
from ezdxf.enums import TextEntityAlignment
from scipy import ndimage
from scipy.spatial import Delaunay, cKDTree
from shapely.geometry import LineString, Point, Polygon, box
from shapely import affinity
from shapely.ops import unary_union
from shapely.strtree import STRtree

__version__ = "2.4"

DEFAULTS = {
    "layer_pts": "TL-CDTN",      # cao độ tự nhiên
    "layer_tk": "TL-CDTK",       # cao độ thiết kế dạng điểm (tuỳ chọn)
    "layer_bdy": "TL-Ranhgioi",  # ranh giới khu vực
    "layer_grid": "TL-Luoi",     # lưới có sẵn (khi --use-grid)
    "layer_brk": "TL-Breakline", # đường gãy
    "layer_cnt": "TL-DongMuc",   # đường đồng mức địa hình (polyline có cao độ)
    "auto_layer": True,   # không thấy layer khai báo thì tự nhận
    "fix_bdy": True,      # tự cắt chồng lấn, lấp khe hở giữa các khu
    "taluy_cut": None,    # hệ số mái đào m (1:m); None = không tính
    "taluy_fill": None,   # hệ số mái đắp m (1:m); None = không tính
    "taluy_res": 0.5,     # bước lưới tính taluy (m)
    "layer_noslope": "TL-KhongTaluy",  # cạnh không làm mái
    "strip": 0.0,         # chiều dày bóc phong hoá (m)
    "layer_pit": "TL-HoMong",  # hố móng, tầng hầm
    "pit_slope": 0.0,     # hệ số mái hố 1:m; 0 = thành đứng
    "pit_bottom": None,   # cao độ đáy hố nếu không ghi trong bản vẽ
    "layer_pile": "TL-Coc",    # cọc khoan nhồi (CIRCLE hoặc block)
    "pile_len": None,     # chiều dài cọc (m)
    "pile_dia": None,     # đường kính cọc nếu tim cọc là block (m)
    "export_3d": False,   # xuất SanNen_3D.dwg, SanNen_3D.html, SanNen_3D.ifc, SanNen_TIN.xml
    "taluy_max": 30.0,    # bề rộng mái tối đa (m)
    "step": 5.0,          # bước lưới (m)
    "rot": None,          # góc lưới (độ); None = theo cạnh dài ranh giới
    "td": None,           # cao độ thiết kế phẳng
    "k": 1.0,             # K = m3 đất đào cần cho 1 m3 đắp đã đầm
    "round_dp": 2,        # làm tròn cao độ đỉnh ô (HML dùng 2 số lẻ)
    "min_cell": 0.25,     # ô nhỏ hơn tỷ lệ này x step^2 thì gộp vào ô kề
    "margin": 30.0,       # lấy điểm đo trong phạm vi ranh giới + margin (m)
    "text_h": None,       # chiều cao chữ; None = tự tính theo bước lưới
    "use_grid": False,
    "saddle": "cut",      # ô yên ngựa: phía liền khối ("cut" giống HML)
    "project": "",
    "zones": {},          # {"KV-01": {"td": -0.6}} hoặc {"plane": {...}}
}

ACAD_GLOB = [r"C:\Program Files\Autodesk\AutoCAD *", r"C:\Program Files\Autodesk\Civil 3D *"]


LOG_SINK = None
NOWIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def log(msg=""):
    if LOG_SINK:
        LOG_SINK(msg)
    elif os.environ.get("SANNEN_STDERR"):       # chế độ --json, kể cả tiến trình con
        print(msg, file=sys.stderr, flush=True)
    elif sys.stdout:
        print(msg, flush=True)


# ---------------------------------------------------------------- DWG <-> DXF
def find_accore():
    env = os.environ.get("ACCORECONSOLE")
    if env and Path(env).exists():
        return env
    import glob
    found = []
    for pat in ACAD_GLOB:
        found += glob.glob(pat + r"\accoreconsole.exe")
    return sorted(found)[-1] if found else None


def dwg_to_dxf(path: Path) -> Path:
    """Chuyển DWG sang DXF bằng accoreconsole, có cache theo nội dung file."""
    acc = find_accore()
    if not acc:
        raise SystemExit("Không tìm thấy accoreconsole.exe. Hãy lưu bản vẽ sang DXF rồi chạy lại.")
    st = path.stat()
    key = hashlib.md5(f"{path}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:12]
    cache = Path(tempfile.gettempdir()) / "sannenpro_cache"
    cache.mkdir(exist_ok=True)
    dxf = cache / f"{key}.dxf"
    if dxf.exists() and dxf.stat().st_size > 0:
        return dxf
    dwg = cache / f"{key}.dwg"
    shutil.copy2(path, dwg)  # luôn làm trên bản sao, không đụng file gốc
    scr = cache / f"{key}.scr"
    scr.write_text(f'FILEDIA 0\nCMDDIA 0\n_.DXFOUT\n"{dxf.as_posix()}"\n16\n_.QUIT\n_Y\n', encoding="ascii")
    log(f"  Đang chuyển DWG -> DXF: {path.name}")
    subprocess.run([acc, "/i", str(dwg), "/s", str(scr), "/l", "en-US"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600, creationflags=NOWIN)
    dwg.unlink(missing_ok=True)
    if not dxf.exists():
        raise SystemExit(f"Chuyển DWG thất bại: {path}")
    return dxf


def dxf_to_dwg(dxf: Path) -> Path | None:
    acc = find_accore()
    if not acc:
        return None
    dwg = dxf.with_suffix(".dwg")
    tmp = Path(tempfile.mkdtemp())
    src, dst = tmp / "in.dxf", tmp / "out.dwg"
    shutil.copy2(dxf, src)
    scr = tmp / "s.scr"
    scr.write_text(f'FILEDIA 0\nCMDDIA 0\n_.ZOOM _E\n_.SAVEAS 2018 "{dst.as_posix()}"\n_.QUIT _Y\n', encoding="ascii")
    try:
        subprocess.run([acc, "/i", str(src), "/s", str(scr), "/l", "en-US"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, creationflags=NOWIN)
    except subprocess.TimeoutExpired:
        return None
    if dst.exists():
        shutil.copy2(dst, dwg)
        shutil.rmtree(tmp, ignore_errors=True)
        return dwg
    return None


# ------------------------------------------------------------------- Đọc CAD
NUM = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
SCAN_VER = 5
ELEV_TAGS = {"Z", "ELEV", "ELEVATION", "CAODO", "CAO_DO", "CD", "LEVEL", "H", "CDTN"}


@dataclass
class Source:
    path: Path
    pts: list = field(default_factory=list)     # [x,y,z]
    tk: list = field(default_factory=list)      # [x,y,z]
    bdys: list = field(default_factory=list)    # Polygon
    grids: list = field(default_factory=list)   # Polygon
    labels: list = field(default_factory=list)  # nhãn ô HML
    nodes: dict = field(default_factory=dict)   # cao độ nút HML
    brk: list = field(default_factory=list)     # đường gãy [[x,y,z],...]
    cnt: list = field(default_factory=list)     # đường đồng mức [[x,y,z],...]
    noslope: list = field(default_factory=list) # đường không làm taluy
    pits: list = field(default_factory=list)    # (Polygon, cao độ đáy)
    piles: list = field(default_factory=list)   # (x, y, bán kính)
    layers: dict = field(default_factory=dict)


def text_xy(e):
    if e.dxftype() == "TEXT":
        ins = e.dxf.insert
        if (e.dxf.get("halign", 0) or e.dxf.get("valign", 0)) and e.dxf.hasattr("align_point"):
            ins = e.dxf.align_point
        return ins[0], ins[1], e.dxf.text
    return e.dxf.insert[0], e.dxf.insert[1], e.plain_text()


def line_pts(e):
    """Trả về (đỉnh [x,y,z], kín?) của LINE/LWPOLYLINE/POLYLINE; cung tròn được chia nhỏ."""
    t = e.dxftype()
    if t == "LINE":
        a, b = e.dxf.start, e.dxf.end
        return [(a[0], a[1], a[2]), (b[0], b[1], b[2])], False
    if t == "LWPOLYLINE":
        z = float(e.dxf.get("elevation", 0.0))
        raw = list(e.get_points("xyb"))
        if any(abs(p[2]) > 1e-12 for p in raw):
            from ezdxf import path as dpath
            pts = [(float(v.x), float(v.y), z) for v in dpath.make_path(e).flattening(0.02)]
        else:
            pts = [(float(p[0]), float(p[1]), z) for p in raw]
        closed = bool(e.closed)
    else:
        pts = [(float(v.dxf.location[0]), float(v.dxf.location[1]), float(v.dxf.location[2])) for v in e.vertices]
        closed = bool(e.is_closed)
    if len(pts) > 2 and math.dist(pts[0][:2], pts[-1][:2]) < 1e-6:
        pts, closed = pts[:-1], True
    return pts, closed


def scan_entities(entities):
    """Gom dữ liệu theo layer, độc lập với cấu hình nên dùng lại được qua cache."""
    R = dict(num={}, closed={}, lines={}, labels=[], nodes={}, circles={}, inserts={})
    for e in entities:
        t, l = e.dxftype(), e.dxf.layer
        try:
            if t in ("TEXT", "MTEXT"):
                x, y, s = text_xy(e)
                s = s.strip().replace(",", ".")
                if NUM.match(s):
                    R["num"].setdefault(l, []).append([x, y, float(s)])
            elif t == "POINT":
                p = e.dxf.location
                R["num"].setdefault(l, []).append([p[0], p[1], p[2]])
            elif t == "CIRCLE":
                p = e.dxf.center
                R["circles"].setdefault(l, []).append([p[0], p[1], e.dxf.radius])
            elif t in ("LINE", "LWPOLYLINE", "POLYLINE"):
                pts, closed = line_pts(e)
                if len(pts) >= 2:
                    R["closed" if closed and len(pts) >= 3 else "lines"].setdefault(l, []).append(pts)
            elif t == "INSERT":
                a = [(x.dxf.tag.upper(), x.dxf.text.strip()) for x in e.attribs]
                p, name = e.dxf.insert, e.dxf.name.upper()
                R["inserts"].setdefault(l, []).append([p[0], p[1]])
                if "OKHOILUONG" in name and len(a) >= 5:
                    R["labels"].append(dict(x=p[0], y=p[1], name=a[0][1], sf=float(a[1][1]), sc=float(a[2][1]),
                                            vf=float(a[3][1]), vc=float(a[4][1])))
                    continue
                d = dict(a)
                if "CDTN" in d and "CDTK" in d:
                    R["nodes"][f"{p[0]:.2f},{p[1]:.2f}"] = float(d["CDTN"])
                    continue
                val = next((float(v.replace(",", ".")) for k, v in a if k in ELEV_TAGS and NUM.match(v)), None)
                if val is None and len(a) == 1 and NUM.match(a[0][1]) and "." in a[0][1].replace(",", "."):
                    val = float(a[0][1].replace(",", "."))
                if val is None and abs(p[2]) > 1e-9:
                    val = p[2]
                if val is not None:
                    R["num"].setdefault(l, []).append([p[0], p[1], val])
        except (ValueError, IndexError, AttributeError):
            continue
    return R


def load_raw(path):
    """Đọc 1 bản vẽ, có cache: lần chạy sau của cùng file gần như tức thì."""
    path = Path(path)
    st = path.stat()
    key = hashlib.md5(f"{path}|{st.st_size}|{st.st_mtime}|{SCAN_VER}".encode()).hexdigest()[:16]
    cache = Path(tempfile.gettempdir()) / "sannenpro_cache"
    cache.mkdir(exist_ok=True)
    pk = cache / f"{key}.pkl"
    if pk.exists():
        return pickle.loads(pk.read_bytes())
    is_dwg = path.suffix.lower() == ".dwg"
    dxf = dwg_to_dxf(path) if is_dwg else path
    types = ["TEXT", "MTEXT", "POINT", "INSERT", "LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE"]
    try:
        doc = iterdxf.opendxf(str(dxf))
        try:
            R = scan_entities(doc.modelspace(types=types))
        finally:
            doc.close()
    except Exception:
        R = scan_entities(ezdxf.readfile(dxf).modelspace())
    pk.write_bytes(pickle.dumps(R))
    if is_dwg:
        dxf.unlink(missing_ok=True)  # DXF rất nặng, đã có cache thì không giữ lại
    return R


def norm(s):
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def contour_lines(lines):
    """Đường đồng mức: mỗi đường một cao độ; layer phải có ít nhất 2 cao độ khác nhau (kể cả cao độ 0)."""
    q = [l for l in lines if len(l) >= 2 and np.ptp([v[2] for v in l]) < 1e-6]
    return q if len({round(l[0][2], 3) for l in q}) >= 2 else []


def pick_layers(raw, cfg):
    """Dùng layer khai báo nếu có dữ liệu; nếu không thì tự nhận theo tên và nội dung."""
    def score_pts(l, a):
        z = np.array([r[2] for r in a])
        if len(z) < 5 or np.ptp(z) < 1e-6 or np.abs(z).max() > 3000:
            return 0
        n = norm(l)
        if re.search(r"cdtk|thiet.?ke|design|luoi|grid|dim|toa.?do|coord|axis|truc", n):
            return 0
        s = len(z) * (0.15 if np.mean(np.abs(z - np.round(z)) < 1e-9) > 0.5 else 1.0)
        if re.search(r"cdtn|cao.?do|tu.?nhien|hien.?trang|\bht\b|spot|elev|level|survey|diem.?do|ground|\beg\b|\bcd\b", n):
            s *= 5
        return s
    num, closed = raw["num"], raw["closed"]
    pts = cfg["layer_pts"] if cfg["layer_pts"] in num else None
    if pts is None and cfg["auto_layer"]:
        sc = {l: score_pts(l, a) for l, a in num.items()}
        best = max(sc, key=sc.get, default=None)
        pts = best if best and sc[best] > 0 else None
    tk = cfg["layer_tk"] if cfg["layer_tk"] in num else None
    if tk is None and cfg["auto_layer"]:
        tk = next((l for l in num if l != pts and re.search(r"cdtk|thiet.?ke|design|\btk\b|ffl", norm(l))), None)
    bdy = cfg["layer_bdy"] if cfg["layer_bdy"] in closed else None
    if bdy is None and cfg["auto_layer"]:
        named = [l for l in closed if re.search(r"ranh|bound|\brg\b|khu.?vuc|pham.?vi|limit|site", norm(l))]
        if named:
            bdy = max(named, key=lambda l: sum(Polygon([q[:2] for q in r]).buffer(0).area for r in closed[l]))
        elif pts:
            P = [Point(r[0], r[1]) for r in num[pts]]
            def cover(l):
                if len(closed[l]) > 30:
                    return 0
                g = unary_union([Polygon([q[:2] for q in r]).buffer(0) for r in closed[l]])
                return sum(g.contains(p) for p in P)
            c = {l: cover(l) for l in closed}
            b = max(c, key=c.get, default=None)
            bdy = b if b and c[b] >= 0.6 * len(P) else None
    brk = cfg["layer_brk"] if cfg["layer_brk"] in raw["lines"] or cfg["layer_brk"] in closed else None
    if brk is None and cfg["auto_layer"]:
        brk = next((l for l in list(raw["lines"]) + list(closed) if re.search(r"break|duong.?gay|\bgay\b", norm(l))), None)
    pit = cfg["layer_pit"] if cfg["layer_pit"] in closed else None
    if pit is None and cfg["auto_layer"]:
        pit = next((l for l in closed if re.search(r"ho.?mong|excav|\bham\b|\bpit\b", norm(l))), None)
    pile = cfg["layer_pile"] if cfg["layer_pile"] in raw["circles"] or cfg["layer_pile"] in raw["inserts"] else None
    if pile is None and cfg["auto_layer"]:
        pile = next((l for l in list(raw["circles"]) + list(raw["inserts"]) if re.search(r"\bcoc\b|\bpile", norm(l))), None)
    ns = cfg["layer_noslope"] if cfg["layer_noslope"] in raw["lines"] or cfg["layer_noslope"] in closed else None
    if ns is None and cfg["auto_layer"]:
        ns = next((l for l in list(raw["lines"]) + list(closed) if re.search(r"khong.?taluy|no.?slope|tuong.?chan|retain", norm(l))), None)
    const_z = contour_lines
    cnt = cfg["layer_cnt"] if const_z(raw["lines"].get(cfg["layer_cnt"], []) + raw["closed"].get(cfg["layer_cnt"], [])) else None
    if cnt is None and cfg["auto_layer"]:
        used = {tk, bdy, brk, pit, ns}
        cand = [l for l in set(raw["lines"]) | set(closed) if l not in used and re.search(r"dong.?muc|contour|\bdm\b|dia.?hinh|topo", norm(l))]
        cand = [l for l in cand if len(const_z(raw["lines"].get(l, []) + raw["closed"].get(l, []))) >= 3]
        cnt = max(cand, key=lambda l: len(raw["lines"].get(l, [])) + len(raw["closed"].get(l, [])), default=None)
    return dict(pts=pts, tk=tk, bdy=bdy, brk=brk, cnt=cnt, pit=pit, pile=pile, noslope=ns)


def to_poly(ring):
    pg = Polygon([q[:2] for q in ring])
    if not pg.is_valid:
        pg = pg.buffer(0)
    return pg if pg.geom_type == "Polygon" and pg.area > 1e-3 else None


def make_source(path, raw, cfg):
    L = pick_layers(raw, cfg)
    src = Source(Path(path), layers=L)
    if L["pts"]:
        src.pts = [list(r) for r in raw["num"][L["pts"]]]
    if L["tk"]:
        src.tk = [list(r) for r in raw["num"][L["tk"]]]
    if L["bdy"]:
        src.bdys = [p for p in map(to_poly, raw["closed"][L["bdy"]]) if p is not None and p.area > 1]
    if cfg["layer_grid"] in raw["closed"]:
        src.grids = [p for p in map(to_poly, raw["closed"][cfg["layer_grid"]]) if p is not None]
    if L["brk"]:
        src.brk = raw["lines"].get(L["brk"], []) + [r + r[:1] for r in raw["closed"].get(L["brk"], [])]
    if L.get("cnt"):
        src.cnt = contour_lines(raw["lines"].get(L["cnt"], []) + [r + r[:1] for r in raw["closed"].get(L["cnt"], [])])
    src.labels, src.nodes = raw["labels"], raw["nodes"]
    if L["noslope"]:
        src.noslope = raw["lines"].get(L["noslope"], []) + [r + r[:1] for r in raw["closed"].get(L["noslope"], [])]
    if L["pit"]:
        texts = raw["num"].get(L["pit"], [])
        gs = list(filter(None, map(to_poly, raw["closed"][L["pit"]])))
        for g in gs:
            inner = [h for h in gs if h is not g and g.contains(h)]   # hố giật cấp: bỏ chữ nằm trong cấp sâu hơn
            zb = next((t[2] for t in texts if g.contains(Point(t[0], t[1])) and not any(h.contains(Point(t[0], t[1])) for h in inner)),
                      cfg["pit_bottom"])
            src.pits.append((g, zb))
    if L["pile"]:
        src.piles = [(c[0], c[1], c[2]) for c in raw["circles"].get(L["pile"], [])]
        src.piles += [(c[0], c[1], None) for c in raw["inserts"].get(L["pile"], [])]
    # bỏ các điểm mẫu nằm xa ranh giới (HML để template rất xa khu đo)
    if src.bdys:
        keep = unary_union(src.bdys).buffer(cfg["margin"])
        x0, y0, x1, y1 = keep.bounds
        for name in ("pts", "tk"):
            setattr(src, name, [r for r in getattr(src, name) if x0 <= r[0] <= x1 and y0 <= r[1] <= y1])
        src.cnt = [q for q in src.cnt if any(x0 <= v[0] <= x1 and y0 <= v[1] <= y1 for v in q)]
    log(f"  {src.path.name}: {len(src.pts)} điểm đo [{L['pts']}], {len(src.bdys)} ranh giới [{L['bdy']}], "
        f"{len(src.tk)} điểm TK [{L['tk']}], {len(src.brk)} đường gãy [{L['brk']}], {len(src.grids)} ô lưới"
        + (f", {len(src.cnt)} đường đồng mức [{L['cnt']}]" if src.cnt else "")
        + (f", {len(src.pits)} hố móng [{L['pit']}]" if src.pits else "") + (f", {len(src.piles)} cọc [{L['pile']}]" if src.piles else "")
        + (f", {len(src.noslope)} đoạn không taluy [{L['noslope']}]" if src.noslope else ""))
    return src


def read_sources(paths, cfg):
    paths = [Path(p) for p in paths]
    if len(paths) > 1:
        try:
            with ProcessPoolExecutor(max_workers=min(4, len(paths), os.cpu_count() or 1)) as ex:
                raws = list(ex.map(load_raw, paths))
        except Exception:
            raws = [load_raw(p) for p in paths]
    else:
        raws = [load_raw(paths[0])]
    return [make_source(p, r, cfg) for p, r in zip(paths, raws)]


def list_layers(paths):
    """Danh sách layer theo loại dữ liệu, cho giao diện."""
    num, closed, lines, pile = set(), set(), set(), set()
    for p in paths:
        r = load_raw(p)
        num |= set(r["num"])
        closed |= set(r["closed"])
        lines |= set(r["lines"])
        pile |= set(r["circles"]) | set(r["inserts"])
    return sorted(num), sorted(closed), sorted(lines | closed), sorted(pile)


def layer_report(paths):
    """Mô tả từng layer dưới dạng dict để AI hoặc script chọn layer trước khi tính."""
    out = {}
    for p in paths:
        r = load_raw(p)
        for key, name in (("num", "elevation_points"), ("closed", "closed_polylines"), ("lines", "open_lines"),
                          ("circles", "circles"), ("inserts", "block_inserts")):
            for l, a in r[key].items():
                d = out.setdefault(l, {})
                d[name] = d.get(name, 0) + len(a)
                if key == "num":
                    z = [q[2] for q in a]
                    d["z_min"] = min(z + [d.get("z_min", 1e18)])
                    d["z_max"] = max(z + [d.get("z_max", -1e18)])
    return dict(layers=out, auto=[pick_layers(load_raw(p), DEFAULTS) for p in paths])


# ---------------------------------------------------------------- Mặt TIN
def hull_extrap(q, edges):
    """Cao độ ngoài vùng điểm: lấy tại điểm gần nhất trên biên vùng, nội suy dọc cạnh biên (mặt liên tục)."""
    A, B, za, zb = edges
    d = B - A
    L2 = np.maximum((d ** 2).sum(axis=1), 1e-12)
    out = np.empty(len(q))
    for s in range(0, len(q), 4000):   # chia khối cho đỡ tốn bộ nhớ
        qq = q[s:s + 4000]
        t = np.clip(((qq[:, None, :] - A[None]) * d[None]).sum(axis=2) / L2[None], 0, 1)
        P = A[None] + t[..., None] * d[None]
        k = ((qq[:, None, :] - P) ** 2).sum(axis=2).argmin(axis=1)
        r = np.arange(len(qq))
        out[s:s + 4000] = za[k] + t[r, k] * (zb[k] - za[k])
    return out


class TIN:
    def __init__(self, pts: np.ndarray, breaks=None):
        pts = np.asarray(pts, float)
        self.off = pts[:, :2].mean(axis=0)
        P = np.c_[pts[:, :2] - self.off, pts[:, 2]]
        self.brk_added = self.brk_missing = 0
        if breaks:
            P = self._conform(pts, P, breaks)
        self.xy = P[:, :2]
        self.z = P[:, 2]
        self.tri = Delaunay(self.xy)
        self.tree = cKDTree(self.xy)
        hv = self.tri.convex_hull            # các cạnh biên (cặp chỉ số đỉnh)
        A, B = self.xy[hv[:, 0]], self.xy[hv[:, 1]]
        self._edges = (A, B, self.z[hv[:, 0]], self.z[hv[:, 1]])
        from shapely.geometry import MultiPoint
        self.hull = MultiPoint([tuple(p) for p in self.xy + self.off]).convex_hull

    def _conform(self, pts, P, breaks):
        """TIN ép theo đường gãy: chèn điểm giữa đến khi mỗi đoạn là cạnh tam giác."""
        base = TIN(pts)
        V = [tuple(r) for r in P]
        ids = {(round(r[0], 3), round(r[1], 3)): i for i, r in enumerate(V)}
        def vid(x, y, z):
            k = (round(x, 3), round(y, 3))
            if k not in ids:
                ids[k] = len(V)
                V.append((x, y, z))
            return ids[k]
        segs = []
        for line in breaks:
            a = np.array(line, float)
            if np.abs(a[:, 2]).max() < 1e-9:   # đường 2D: lấy cao độ từ mặt đất
                a[:, 2] = base.filled(a[:, :2])[0]
            a[:, :2] -= self.off
            q = [vid(*r) for r in a]
            segs += [(i, j) for i, j in zip(q, q[1:]) if i != j]
        def edges():
            sim = Delaunay(np.array(V)[:, :2]).simplices
            e = np.sort(np.vstack([sim[:, [0, 1]], sim[:, [1, 2]], sim[:, [0, 2]]]), axis=1)
            return set(map(tuple, e.tolist()))
        for _ in range(18):
            E = edges()
            new, change = [], False
            for i, j in segs:
                L = math.dist(V[i][:2], V[j][:2])
                if (min(i, j), max(i, j)) in E or L < 0.02:
                    new.append((i, j))
                    continue
                m = vid((V[i][0] + V[j][0]) / 2, (V[i][1] + V[j][1]) / 2, (V[i][2] + V[j][2]) / 2)
                new += [(i, m), (m, j)]
                change = True
            segs = new
            if not change:
                break
        E = edges()
        self.brk_added = len(V) - len(P)
        self.brk_missing = sum((min(s), max(s)) not in E for s in segs)
        return np.array(V)

    def __call__(self, xy):
        q = np.atleast_2d(np.asarray(xy, float)) - self.off
        s = self.tri.find_simplex(q)
        out = np.full(len(q), np.nan)
        ok = s >= 0
        if ok.any():
            T = self.tri.transform[s[ok]]
            b = np.einsum("ijk,ik->ij", T[:, :2, :2], q[ok] - T[:, 2])
            w = np.c_[b, 1 - b.sum(axis=1)]
            out[ok] = (w * self.z[self.tri.simplices[s[ok]]]).sum(axis=1)
        return out

    def filled(self, xy):
        """Như __call__, ngoài vùng điểm thì kéo dài liên tục từ biên vùng."""
        z = self(xy)
        miss = np.isnan(z)
        if miss.any():
            q = np.atleast_2d(np.asarray(xy, float))[miss] - self.off
            z[miss] = hull_extrap(q, self._edges)
        return z, miss

    def triangles(self):
        return self.xy[self.tri.simplices] + self.off, self.z[self.tri.simplices]


# ----------------------------------------------------- Cao độ thiết kế
class Design:
    def __init__(self, kind, **kw):
        self.kind, self.kw = kind, kw
        if kind == "tin":
            self.tin = TIN(kw["pts"])
            self.hull = self.tin.hull

    def __call__(self, xy):
        q = np.atleast_2d(np.asarray(xy, float))
        if self.kind == "flat":
            return np.full(len(q), float(self.kw["z"]))
        if self.kind == "plane":
            k = self.kw
            return k["z0"] + (q[:, 0] - k["x0"]) * k.get("ix", 0) + (q[:, 1] - k["y0"]) * k.get("iy", 0)
        return self.tin.filled(q)[0]

    def outside_area(self, poly):
        """Diện tích phần khu nằm ngoài vùng điểm thiết kế (m2)."""
        return poly.difference(self.hull).area if self.kind == "tin" else 0.0

    def triangles(self):
        return self.tin.triangles() if self.kind == "tin" else None

    def text(self):
        if self.kind == "flat":
            return f"{self.kw['z']:+.3f}"
        if self.kind == "plane":
            return f"Mặt nghiêng ix={self.kw.get('ix', 0)}, iy={self.kw.get('iy', 0)}"
        return f"TIN thiết kế ({len(self.kw['pts'])} điểm)"


def pick_design(name, cfg, tk_pts):
    zc = cfg["zones"].get(name, {})
    if cfg["td"] is not None:
        return Design("flat", z=cfg["td"])
    if "td" in zc:
        return Design("flat", z=zc["td"])
    if "plane" in zc:
        return Design("plane", **zc["plane"])
    if len(tk_pts):
        a = np.array(tk_pts, float)
        if np.ptp(a[:, 2]) < 1e-6 or len(a) < 3:
            return Design("flat", z=float(a[0, 2]))
        return Design("tin", pts=a)
    raise SystemExit(f"Chưa có cao độ thiết kế cho {name}. Dùng --td hoặc khai báo trong config.")


# ------------------------------------------------------------ Tạo lưới
def row_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def auto_rot(poly):
    c = list(poly.minimum_rotated_rectangle.exterior.coords)
    e = max(((c[i], c[i + 1]) for i in range(4)), key=lambda s: math.dist(*s))
    a = math.degrees(math.atan2(e[1][1] - e[0][1], e[1][0] - e[0][0]))
    return (a + 90) % 180 - 90


def make_grid(poly, step, rot, min_frac):
    """Lưới xoay cắt theo ranh giới; ô quá nhỏ gộp vào ô kề có cạnh chung dài nhất."""
    org = poly.centroid
    p = affinity.rotate(poly, -rot, origin=org)
    x0, y0, x1, y1 = p.bounds
    nx, ny = math.ceil((x1 - x0) / step - 1e-9), math.ceil((y1 - y0) / step - 1e-9)
    cells = []
    for j in range(ny):
        for i in range(nx):
            c = box(x0 + i * step, y0 + j * step, x0 + (i + 1) * step, y0 + (j + 1) * step).intersection(p)
            for g in getattr(c, "geoms", [c]):
                if g.geom_type == "Polygon" and g.area > 1e-4:
                    cells.append(dict(name=f"{row_name(j)}-{i + 1}", g=g))
    amin = min_frac * step * step
    for _ in range(len(cells)):
        small = [c for c in cells if c["g"].area < amin]
        if not small:
            break
        s = min(small, key=lambda c: c["g"].area)
        nb = [(s["g"].boundary.intersection(c["g"].boundary).length, id(c), c) for c in cells if c is not s]
        L, _, n = max(nb, key=lambda t: t[0])
        if L <= 1e-6:
            break
        n["g"] = unary_union([n["g"], s["g"]])
        cells.remove(s)
    out = []
    for c in cells:
        g = affinity.rotate(c["g"], rot, origin=org).simplify(1e-4)
        if g.geom_type == "Polygon":
            out.append(dict(name=c["name"], poly=g))
    return out


# ------------------------------------------------------- Tính theo ô lưới
def shoelace(p):
    p = np.asarray(p)
    x, y = p[:, 0], p[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def split_cell(xy, h, saddle="cut"):
    """Tách đa giác ô theo đường h=0.
    Trả về (phần đắp, phần đào, đoạn đường 0); mỗi phần là [(toạ độ, |h|), ...]."""
    n = len(h)
    ring = []
    for i in range(n):
        j = (i + 1) % n
        ring.append((xy[i][0], xy[i][1], float(h[i])))
        if h[i] * h[j] < 0:
            t = h[i] / (h[i] - h[j])
            ring.append((xy[i][0] + t * (xy[j][0] - xy[i][0]), xy[i][1] + t * (xy[j][1] - xy[i][1]), 0.0))
    if all(r[2] >= 0 for r in ring) or all(r[2] <= 0 for r in ring):
        part = [([r[:2] for r in ring], [abs(r[2]) for r in ring])]
        return (part, [], []) if any(r[2] > 0 for r in ring) else ([], part, [])
    k0 = next(i for i, r in enumerate(ring) if r[2] == 0)
    ring = ring[k0:] + ring[:k0]
    m = len(ring)
    arcs, cur, sign = [], [ring[0]], 0
    for i in range(1, m + 1):
        r = ring[i % m]
        cur.append(r)
        if r[2] == 0:
            s = np.sign(sum(q[2] for q in cur))
            if s != 0:
                arcs.append((s, cur))
            cur = [r]
    merged = []
    for s, a in arcs:
        if merged and merged[-1][0] == s:
            merged[-1] = (s, merged[-1][1] + a[1:])
        else:
            merged.append((s, a))
    if len(merged) > 1 and merged[0][0] == merged[-1][0]:
        s, a = merged.pop()
        merged[0] = (s, a + merged[0][1][1:])
    def pack(a):
        if math.dist(a[0][:2], a[-1][:2]) < 1e-9:
            a = a[:-1]
        return ([r[:2] for r in a], [abs(r[2]) for r in a])
    fill, cut, zero = [], [], []
    if len(merged) == 2:
        for s, a in merged:
            (fill if s > 0 else cut).append(pack(a))
            if s > 0:
                zero.append((a[0][:2], a[-1][:2]))
    else:  # ô yên ngựa: một phía liền khối, phía kia tách thành các tam giác góc
        keep = -1 if saddle == "cut" else 1
        solid = []
        for s, a in merged:
            if s == keep:
                solid += a
            else:
                (fill if s > 0 else cut).append(pack(a))
                zero.append((a[0][:2], a[-1][:2]))
        ded = [solid[0]]
        for r in solid[1:]:
            if math.dist(r[:2], ded[-1][:2]) > 1e-9:
                ded.append(r)
        (fill if keep > 0 else cut).append(pack(ded))
    return fill, cut, zero


def cell_calc(c, tin, design, cfg):
    xy = np.array(c["poly"].exterior.coords[:-1])
    zn, miss = tin.filled(xy)
    if cfg["round_dp"] is not None:
        zn = np.round(zn, cfg["round_dp"])
    zt = np.round(design(xy), 3)
    h = np.round(zt - zn + cfg["strip"], 6)
    fill, cut, zero = split_cell([tuple(p) for p in xy], h, cfg["saddle"])
    rec = dict(sf=0.0, sc=0.0, vf=0.0, vc=0.0)
    for parts, a, v in ((fill, "sf", "vf"), (cut, "sc", "vc")):
        for p, hh in parts:
            ar = shoelace(p)
            rec[a] += ar
            rec[v] += ar * float(np.mean(hh))
    c.update(xy=xy, zn=zn, zt=zt, h=h, fill=fill, cut=cut, zero=zero, extrap=int(miss.sum()),
             area=c["poly"].area, **rec)


# ------------------------------------------------------- Tính TIN chính xác
def ear_clip(p):
    """Tam giác hoá đa giác đơn (có thể lõm)."""
    p = [tuple(q) for q in p]
    if len(p) == 3:
        return [p]
    a = sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))
    if a < 0:
        p = p[::-1]
    out = []
    idx = list(range(len(p)))
    def cross(o, u, v):
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        done = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            A, B, C = p[i0], p[i1], p[i2]
            if cross(A, B, C) <= 1e-12:
                continue
            if any(cross(A, B, p[j]) >= 0 and cross(B, C, p[j]) >= 0 and cross(C, A, p[j]) >= 0
                   for j in idx if j not in (i0, i1, i2)):
                continue
            out.append([A, B, C])
            idx.pop(k)
            done = True
            break
        if not done:
            idx.pop(0)
    if len(idx) == 3:
        out.append([p[i] for i in idx])
    return out


def fine_split(p, size):
    """Chia đa giác thành các mảnh nhỏ theo lưới vuông cạnh size."""
    x0, y0, x1, y1 = p.bounds
    if max(x1 - x0, y1 - y0) <= size:
        return no_holes(p)
    out = []
    for x in np.arange(x0, x1, size):
        for y in np.arange(y0, y1, size):
            g = p.intersection(box(x, y, x + size, y + size))
            out += [r for q in getattr(g, "geoms", [g]) if q.geom_type == "Polygon" for r in no_holes(q) if r.area >= 1e-9]
    return out


def no_holes(p):
    """Tách đa giác có lỗ thành các đa giác không lỗ bằng đường cắt qua lỗ."""
    if not p.interiors:
        return [p]
    from shapely.ops import split
    from shapely.geometry import LineString
    c = p.interiors[0].centroid
    x0, y0, x1, y1 = p.bounds
    out = []
    for q in split(p, LineString([(c.x, y0 - 1), (c.x, y1 + 1)])).geoms:
        out += no_holes(q)
    return out


class Overlay:
    """Các tam giác TIN đã cắt theo ô: dùng chung cho tính khối lượng và cân bằng."""

    def __init__(self, tin: TIN, cells, design=None):
        V, Z = tin.triangles()
        polys = [Polygon(t) for t in V]
        tree = STRtree(polys)
        # mặt thiết kế dạng TIN: cắt thêm theo tam giác thiết kế để trong mỗi mảnh cả hai mặt đều phẳng
        dt = design.triangles() if design is not None and getattr(design, "kind", "") == "tin" else None
        if dt is not None:
            dpol = [Polygon(t) for t in dt[0]]
            dtree = STRtree(dpol)
            dhull = design.hull
        xy, zz, own, cover = [], [], [], {}
        self.outside = 0.0      # diện tích nằm ngoài vùng điểm đo (m2)
        polys_ok = lambda g: [p for q in getattr(g, "geoms", [g]) if q.geom_type == "Polygon" for p in no_holes(q) if p.area >= 1e-9]

        def by_design(parts):
            """Cắt thêm theo tam giác thiết kế; phần ngoài vùng điểm thiết kế chia mịn."""
            if dt is None:
                return parts
            sub = []
            for part in parts:
                for di in dtree.query(part):
                    sub += polys_ok(dpol[di].intersection(part))
                rest = part.difference(dhull)
                for q in polys_ok(rest):
                    sub += fine_split(q, fine)
            return sub

        def emit(part, ci, co):
            for tr in ear_clip(list(part.exterior.coords[:-1])):
                t = np.array(tr)
                xy.append(t)
                zz.append((t - tin.off) @ co[:2] + co[2] if co is not None else tin.filled(t)[0])
                own.append(ci)

        # hệ số mặt phẳng z = a x + b y + c cho từng tam giác (toạ độ cục bộ)
        P = V - tin.off
        for ci, c in enumerate(cells):
            pg = c["poly"]
            fine = max(0.5, math.sqrt(pg.area) / 5)
            got = 0.0
            for ti in tree.query(pg):
                parts = by_design(polys_ok(polys[ti].intersection(pg)))
                if not parts:
                    continue
                co = np.linalg.solve(np.c_[P[ti], np.ones(3)], Z[ti])
                for part in parts:
                    got += part.area
                    emit(part, ci, co)
            # phần ô nằm ngoài vùng điểm đo: cao độ đất kéo dài từ biên vùng, chia mịn
            out = pg.difference(tin.hull)
            if out.area >= 1e-6:
                self.outside += out.area
                for q in polys_ok(out):
                    for part in by_design(fine_split(q, fine)):
                        got += part.area
                        emit(part, ci, None)
            cover[ci] = got
        self.xy = np.array(xy)
        self.z = np.array(zz)
        self.own = np.array(own)
        self.cover = cover
        p = self.xy
        self.area = 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                                 - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))

    def volumes(self, h):
        """h: (n,3) = TK - TN. Trả về (V đắp, V đào, S đắp, S đào) theo từng tam giác."""
        A = self.area
        h = np.where(np.abs(h) < 1e-9, 1e-9, h)
        pos = h > 0
        np_ = pos.sum(axis=1)
        Vf, Vc, Sf, Sc = (np.zeros(len(h)) for _ in range(4))
        m = h.mean(axis=1)
        a = np_ == 3
        Vf[a] = A[a] * m[a]
        Sf[a] = A[a]
        b = np_ == 0
        Vc[b] = -A[b] * m[b]
        Sc[b] = A[b]
        mix = ~(a | b)
        if mix.any():
            hh = h[mix]
            p = pos[mix]
            odd = np.where(p.sum(axis=1) == 1, p.argmax(axis=1), (~p).argmax(axis=1))
            r = np.arange(len(hh))
            h0, h1, h2 = hh[r, odd], hh[r, (odd + 1) % 3], hh[r, (odd + 2) % 3]
            frac = h0 / (h0 - h1) * h0 / (h0 - h2)
            As = A[mix] * frac
            Vs = As * h0 / 3                    # chóp nhọn tại đỉnh lẻ (có dấu)
            Vt = A[mix] * hh.mean(axis=1)
            Vo = Vt - Vs                        # phần còn lại (có dấu ngược)
            f = h0 > 0
            Vf[mix] = np.where(f, Vs, Vo)
            Vc[mix] = np.where(f, -Vo, -Vs)
            Sf[mix] = np.where(f, As, A[mix] - As)
            Sc[mix] = A[mix] - Sf[mix]
        return Vf, Vc, Sf, Sc


def balance(ov, K, lo=None, hi=None):
    """Tìm cao độ phẳng (hoặc độ dịch mặt thiết kế khi mặt không phẳng) sao cho V đào = K x V đắp, và vẽ đường cong."""
    z = ov.z
    zd = getattr(ov, "zd", None)
    if zd is not None:
        dh = zd - z
        lo = -float(dh.max()) if lo is None else lo
        hi = -float(dh.min()) if hi is None else hi
        z = -dh   # h = d - z với z = mặt đất - thiết kế
    lo = float(z.min()) if lo is None else lo
    hi = float(z.max()) if hi is None else hi
    def f(td):
        Vf, Vc, _, _ = ov.volumes(td - z)
        return Vc.sum() - K * Vf.sum()
    a, b = lo - 1, hi + 1
    for _ in range(70):
        m = (a + b) / 2
        if f(m) > 0:
            a = m
        else:
            b = m
    td = (a + b) / 2
    curve = []
    for t in np.arange(math.floor(lo * 10) / 10, math.ceil(hi * 10) / 10 + 1e-9, 0.1):
        Vf, Vc, _, _ = ov.volumes(t - z)
        curve.append((round(float(t), 2), float(Vf.sum()), float(Vc.sum())))
    return td, curve


# ------------------------------------------------------------- Kiểm tra số liệu
def check_points(pts):
    """Điểm trùng và điểm nhô/lõm riêng lẻ: phải cao hơn (hoặc thấp hơn) mọi điểm lân cận.
    Sườn dốc, mương, gờ có lân cận cùng cao độ nên không bị báo nhầm."""
    res = dict(dup=[], outlier=[])
    tree = cKDTree(pts[:, :2])
    for i, j in sorted(tree.query_pairs(0.05)):
        res["dup"].append((pts[i].tolist(), pts[j].tolist()))
    k = min(7, len(pts))
    _, idx = tree.query(pts[:, :2], k=k)
    d = pts[:, 2, None] - pts[idx[:, 1:], 2]
    r = pts[:, 2] - np.median(pts[idx[:, 1:], 2], axis=1)
    lim = max(4 * 1.4826 * np.median(np.abs(r - np.median(r))), 0.5)
    same = (d > 0).all(axis=1) | (d < 0).all(axis=1)
    gap = np.abs(d).min(axis=1)
    for i in np.where(same & (gap > lim))[0]:
        res["outlier"].append((*pts[i].tolist(), float(gap[i])))
    res["lim"] = float(lim)
    return res


def dedupe(pts):
    a = np.array(pts, float)
    _, u = np.unique(np.round(a, 3), axis=0, return_index=True)
    return a[np.sort(u)]


# ------------------------------------------------------------- Dựng khu vực
def natural(name):
    m = re.match(r"([A-Z]+)-(\d+)$", name)
    return (len(m[1]), m[1], int(m[2])) if m else (99, name, 0)


def zone_name(path, i, nb):
    m = re.search(r"san\s*n[eềê]n\s*(\d+)", path.stem, re.I)
    base = f"KV-{m[1]}" if m else None
    if base and nb == 1:
        return base
    return f"{base or 'KV'}-{i + 1:02d}" if nb > 1 or not base else base


def grid_rot(cells):
    w = {}
    for c in cells[:60]:
        xy = np.array(c["poly"].exterior.coords)
        d = np.diff(xy, axis=0)
        for v in d:
            a = round(((math.degrees(math.atan2(v[1], v[0])) + 45) % 90 - 45), 0)
            w[a] = w.get(a, 0) + math.hypot(*v)
    return max(w, key=w.get) if w else 0.0


def parts(g):
    return [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon"]


def find_gaps(polys, d=2.0):
    """Khe hở thật: phần lấp được khi đóng khe và chạm từ 2 khu trở lên."""
    if len(polys) < 2:
        return []
    u = unary_union(polys)
    g = u.buffer(d, join_style="mitre").buffer(-d, join_style="mitre").difference(u)
    out = []
    for p in parts(g):
        if p.area >= 0.01 and sum(1 for q in polys if p.buffer(0.02).intersection(q).area > 1e-4) >= 2:
            out.append(p)
    return out


def fix_boundaries(polys):
    """Phần chồng lấn thuộc về khu trước; khe hở nhập vào khu kề có cạnh chung dài nhất."""
    out, seen, cut = [], None, 0.0
    for p in polys:
        q = p if seen is None else p.difference(seen)
        cut += p.area - q.area
        q = max(parts(q.buffer(0)), key=lambda g: g.area)
        out.append(q)
        seen = q if seen is None else seen.union(q)
    gaps = find_gaps(out)
    filled = 0.0
    for g in gaps:
        i = max(range(len(out)), key=lambda k: g.buffer(0.02).intersection(out[k]).area)
        out[i] = max(parts(out[i].union(g.buffer(1e-6)).buffer(0)), key=lambda x: x.area)
        filled += g.area
    res = []
    for q in out:
        if q.interiors and sum(Polygon(r).area for r in q.interiors) < 5:
            q = Polygon(q.exterior)
        res.append(q.simplify(1e-3))
    return res, cut, filled


def build_zones(sources, cfg):
    entries = []
    for src in sources:
        for i, b in enumerate(src.bdys):
            entries.append([src, zone_name(src.path, i, len(src.bdys)), b])
    notes = []
    if cfg["fix_bdy"] and not cfg["use_grid"] and len(entries) > 1:
        new, cut, filled = fix_boundaries([e[2] for e in entries])
        for e, q in zip(entries, new):
            e[2] = q
        if cut > 0.01:
            notes.append(f"Đã cắt {cut:.2f} m2 chồng lấn, phần này chỉ tính cho khu đứng trước")
        if filled > 0.01:
            notes.append(f"Đã lấp {filled:.2f} m2 khe hở vào khu kề")
    zones = []
    for src, name, b in entries:
        if cfg["use_grid"]:
            cells, n = [], 0
            for g in src.grids:
                if not b.buffer(0.5).contains(g.representative_point()):
                    continue
                n += 1
                cells.append(dict(name=f"?-{n}", poly=g))
            rot = grid_rot(cells)
            labs = [L for L in src.labels if b.buffer(0.5).contains(Point(L["x"], L["y"]))]
            for L in labs:
                pt = Point(L["x"], L["y"])
                for c in cells:
                    if c["poly"].buffer(0.01).contains(pt):
                        c["name"], c["hml"] = L["name"], L
                        break
        else:
            rot = cfg["rot"] if cfg["rot"] is not None else auto_rot(b)
            cells = make_grid(b, cfg["step"], rot, cfg["min_cell"])
            labs = []
        cells.sort(key=lambda c: natural(c["name"]))
        used = {z["name"] for z in zones}
        if name in used:
            name = next(f"KV-{n:02d}" for n in range(1, 999) if f"KV-{n:02d}" not in used)
        zones.append(dict(name=name, poly=b, cells=cells, rot=rot, src=src, n_labels=len(labs),
                          design=pick_design(name, cfg, src.tk)))
    return zones, notes


def taluy_ctx(zones, tin, cfg, res=None, noslope=None):
    """Chuẩn bị lưới điểm ngoài ranh giới, dùng lại khi thử nhiều cao độ."""
    polys = [z["poly"] for z in zones]
    u = unary_union(polys)
    bd = u.boundary
    res = float(res or cfg["taluy_res"])
    W = float(cfg["taluy_max"])
    x0, y0, x1, y1 = u.buffer(W).bounds
    xs = np.arange(x0, x1 + res, res) + res / 2   # tâm ô, tránh điểm nằm đúng trên ranh
    ys = np.arange(y0, y1 + res, res) + res / 2
    X, Y = np.meshgrid(xs, ys)
    x, y = X.ravel(), Y.ravel()
    P = shapely.points(x, y)
    inside = shapely.contains_xy(u, x, y)
    dist = shapely.distance(P, bd)
    idx = np.where(~inside & (dist <= W))[0]
    d = dist[idx]
    edge = shapely.get_coordinates(shapely.get_point(shapely.shortest_line(P[idx], bd), 1))
    owner = STRtree(polys).nearest(shapely.points(edge))
    blocked = np.zeros(len(idx), bool)
    if noslope:
        g = unary_union([LineString([q[:2] for q in l]) for l in noslope]).buffer(0.5)
        blocked = shapely.contains_xy(g, edge[:, 0], edge[:, 1])
    zg, miss = tin.filled(np.c_[x[idx], y[idx]])
    zge = tin.filled(edge)[0]
    n = len(zones)
    zcfg = [cfg["zones"].get(z["name"], {}) for z in zones]
    mc = np.array([c.get("taluy_cut", cfg["taluy_cut"]) or 0 for c in zcfg], float)[owner]
    mf = np.array([c.get("taluy_fill", cfg["taluy_fill"]) or 0 for c in zcfg], float)[owner]
    D = np.full(x.size, np.inf)
    D[idx] = d
    return dict(res=res, W=W, xs=xs, ys=ys, shape=X.shape, idx=idx, d=d, edge=edge, owner=owner, blocked=blocked,
                zg=zg - cfg["strip"], zge=zge - cfg["strip"], miss=miss, mc=mc, mf=mf, n=n, D=D.reshape(X.shape),
                inside=inside.reshape(X.shape))


def taluy_eval(c, ze):
    """ze: cao độ thiết kế tại mép. Trả về lưới h (>0 đắp, <0 đào) sau khi bỏ phần không liền ranh."""
    d, zg, zge = c["d"], c["zg"], c["zge"]
    h = np.zeros(len(d))
    m = (ze >= zge) & (c["mf"] > 0) & ~c["blocked"]
    v = ze[m] - d[m] / c["mf"][m] - zg[m]
    h[m] = np.where(v > 0, v, 0)
    m = (ze < zge) & (c["mc"] > 0) & ~c["blocked"]
    v = ze[m] + d[m] / c["mc"][m] - zg[m]
    h[m] = np.where(v < 0, v, 0)
    G = np.zeros(c["shape"][0] * c["shape"][1])
    G[c["idx"]] = h
    G = G.reshape(c["shape"])
    keep = np.zeros(c["shape"], bool)
    for sign in (1, -1):
        lab, n = ndimage.label(sign * G > 0, structure=np.ones((3, 3)))
        if n:
            near = np.unique(lab[(c["D"] <= c["res"] * 1.5) & (lab > 0)])
            keep |= np.isin(lab, near)
    return np.where(keep, G, 0), keep


def calc_taluy(zones, tin, cfg, noslope=None):
    """Mái taluy từ mép ranh giới ra ngoài đến khi gặp mặt đất, tính trên lưới điểm.
    Mép đang đắp thì mái đổ xuống 1:m đắp, mép đang đào thì mái dốc lên 1:m đào.
    Cạnh nằm dọc đường trên layer không taluy (tường chắn, ranh đất) thì bỏ qua."""
    has_m = cfg["taluy_cut"] or cfg["taluy_fill"] or any(
        c.get("taluy_cut") or c.get("taluy_fill") for c in cfg["zones"].values())
    if not has_m:
        return None
    c = taluy_ctx(zones, tin, cfg, noslope=noslope)
    ze = np.zeros(len(c["d"]))
    for i, z in enumerate(zones):
        m = c["owner"] == i
        if m.any():
            ze[m] = z["design"](c["edge"][m])
    G, keep = taluy_eval(c, ze)
    g = G.ravel()[c["idx"]]
    n, owner = c["n"], c["owner"]
    da = c["res"] ** 2
    vf = np.bincount(owner, np.where(g > 0, g, 0) * da, n)
    vc = np.bincount(owner, np.where(g < 0, -g, 0) * da, n)
    sf = np.bincount(owner, (g > 0) * da, n)
    sc = np.bincount(owner, (g < 0) * da, n)
    from contourpy import contour_generator
    F = c["inside"] | keep
    lines = []
    for a in contour_generator(c["xs"], c["ys"], ndimage.gaussian_filter(F.astype(float), 0.7)).lines(0.5):
        if len(a) > 3:
            lines.append(np.array(LineString(a).simplify(c["res"] / 2).coords))
    band = np.count_nonzero(g)
    short = float(np.count_nonzero(c["miss"] & (g != 0)) / band) if band else 0.0
    width = float(c["d"][g != 0].max()) if band else 0.0
    # lưới tam giác mặt mái cho mô hình 3D, bước khoảng 1 m
    st = max(1, int(round(1.0 / c["res"])))
    Zg = np.full(c["shape"][0] * c["shape"][1], np.nan)
    Zg[c["idx"]] = c["zg"]
    top = (Zg.reshape(c["shape"]) + G)[::st, ::st]
    K = keep[::st, ::st] & ~np.isnan(top)
    xs, ys = c["xs"][::st], c["ys"][::st]
    vid = -np.ones(K.shape, int)
    vid[K] = np.arange(int(K.sum()))
    jj, ii = np.nonzero(K)
    pts = np.c_[xs[ii], ys[jj], top[K]].tolist() if K.any() else []
    a, b, cc, d = vid[:-1, :-1], vid[:-1, 1:], vid[1:, :-1], vid[1:, 1:]
    q = (a >= 0) & (b >= 0) & (cc >= 0) & (d >= 0)
    faces = np.r_[np.c_[a[q], b[q], d[q]], np.c_[a[q], d[q], cc[q]]].tolist()
    return dict(vf=vf, vc=vc, sf=sf, sc=sc, lines=lines, short=short, width=width, W=c["W"], mesh=dict(pts=pts, faces=faces),
                mc=cfg["taluy_cut"], mf=cfg["taluy_fill"], names=[z["name"] for z in zones],
                skipped=float(np.count_nonzero(c["blocked"]) * da))


def calc_pits(zones, tin, cfg, pits):
    """Hố móng, tầng hầm: đáy phẳng, mái 1:m (m = 0 là thành đứng), đào từ mặt sau san nền.
    Phần trong ranh lấy cao độ thiết kế, ngoài ranh lấy mặt đất.
    Các hố gần nhau tính chung trên một lưới: mặt đáy chung = thấp nhất của các hố tại mỗi điểm, nên
    hố chồng nhau không tính trùng, hố nằm trong hố (giật cấp) tự ra cơ giữa các cấp.
    Khối lượng phần chung gán cho hố sâu hơn ở điểm đó."""
    res = 0.25
    polys = [z["poly"] for z in zones]
    u = unary_union(polys)
    ztree = STRtree(polys)
    m = float(cfg["pit_slope"] or 0)
    out = [dict(name=f"HM-{i + 1:02d}", area=pg.area, zb=zb, v=0.0, top=None, poly=pg, note="") for i, (pg, zb) in enumerate(pits)]
    ok = [i for i, (pg, zb) in enumerate(pits) if zb is not None]
    if not ok:
        return out
    # phạm vi ảnh hưởng của từng hố (gồm mái), rồi gom các hố có phạm vi giao nhau thành cụm
    reach = {}
    for i in ok:
        pg, zb = pits[i]
        probe = np.array(pg.exterior.coords)
        tmax = float(max(np.max(tin.filled(probe)[0]), max(z["design"](probe).max() for z in zones)))
        W = max((tmax - zb) * m, 0) + 1.0
        reach[i] = (W, pg.buffer(W if m else res, join_style=2))
    groups, left = [], set(ok)
    while left:
        g = {left.pop()}
        grow = True
        while grow:
            grow = False
            for k in list(left):
                if any(reach[k][1].intersects(reach[q][1]) for q in g):
                    g.add(k); left.discard(k); grow = True
        groups.append(sorted(g))
    for g in groups:
        x0, y0, x1, y1 = unary_union([reach[i][1] for i in g]).bounds
        X, Y = np.meshgrid(np.arange(x0, x1 + res, res) + res / 2, np.arange(y0, y1 + res, res) + res / 2)
        x, y = X.ravel(), Y.ravel()
        P = shapely.points(x, y)
        B = np.full(len(x), np.inf)          # mặt đáy chung
        own = np.full(len(x), -1)
        for i in g:
            pg, zb = pits[i]
            d = shapely.distance(P, pg)
            b = np.where(d <= 0, zb, zb + d / m if m else np.inf)
            b[d > reach[i][0]] = np.inf
            w = b < B
            B[w], own[w] = b[w], i
        keep = np.isfinite(B)
        x, y, P, B, own = x[keep], y[keep], P[keep], B[keep], own[keep]
        top = tin.filled(np.c_[x, y])[0] - cfg["strip"]
        ins = shapely.contains_xy(u, x, y)
        if ins.any():
            who = ztree.nearest(P[ins])
            q = np.c_[x[ins], y[ins]]
            zd = np.zeros(len(q))
            for k, z in enumerate(zones):
                w = who == k
                if w.any():
                    zd[w] = z["design"](q[w])
            top[ins] = zd
        h = np.maximum(top - B, 0)
        for i in g:
            pg = pits[i][0]
            w = own == i
            out[i]["v"] = float(h[w].sum() * res * res)
            inside = shapely.contains_xy(pg, x, y)
            out[i]["top"] = float(top[inside].mean()) if inside.any() else None
        # ghi chú quan hệ giữa các hố
        for a in g:
            for b in g:
                if a < b:
                    A, Bp = pits[a][0], pits[b][0]
                    if A.contains(Bp) or Bp.contains(A):
                        o, n = (a, b) if A.contains(Bp) else (b, a)
                        out[n]["note"] = f"giật cấp trong {out[o]['name']}"
                    elif A.intersects(Bp) and A.intersection(Bp).area > 1e-6:
                        out[b]["note"] = (out[b]["note"] + "; " if out[b]["note"] else "") + f"chồng với {out[a]['name']}, phần chung tính một lần"
    return out


def calc_piles(cfg, piles):
    L = cfg["pile_len"]
    rows = {}
    for x, y, r in piles:
        dia = 2 * r if r else cfg["pile_dia"]
        rows.setdefault(round(dia, 3) if dia else None, []).append((x, y))
    out = []
    for dia, a in sorted(rows.items(), key=lambda t: t[0] or 0):
        v = len(a) * math.pi / 4 * dia ** 2 * L if dia and L else 0.0
        out.append(dict(d=dia, n=len(a), L=L, v=v))
    return out


def balance_full(mer, K, ctx, extra, ze0=None):
    """Cao độ phẳng (hoặc độ dịch mặt thiết kế) để tổng đào (gồm taluy, hố móng, cọc) = K x tổng đắp (gồm taluy).
    ze0: cao độ thiết kế tại mép taluy khi cân bằng theo độ dịch."""
    z = mer.z if mer.zd is None else mer.z - mer.zd
    lo, hi = float(z.min()) - 1, float(z.max()) + 1
    def f(td):
        Vf, Vc, _, _ = mer.volumes(td - z)
        a, b = float(Vc.sum()) + extra, float(Vf.sum())
        if ctx:
            G = taluy_eval(ctx, np.full(len(ctx["d"]), td) if ze0 is None else ze0 + td)[0]
            da = ctx["res"] ** 2
            a += float(-G[G < 0].sum() * da)
            b += float(G[G > 0].sum() * da)
        return a - K * b
    for _ in range(28):
        m = (lo + hi) / 2
        if f(m) > 0:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def summary(zones, T, X, bal, cfg, Q, inputs, out, files, layers):
    S = lambda k: float(sum(z[k] for z in zones))
    tf, tc = (float(T["vf"].sum()), float(T["vc"].sum())) if T else (0.0, 0.0)
    pv, cv = sum(p["v"] for p in X["pits"]), sum(p["v"] for p in X["piles"])
    K = cfg["k"]
    return dict(
        version=__version__, inputs=[str(p) for p in inputs], output_dir=str(out), layers=layers,
        params={k: cfg[k] for k in ("td", "step", "rot", "k", "strip", "taluy_cut", "taluy_fill", "pit_slope", "pile_len", "pile_dia")},
        zones=[dict(name=z["name"], design=z["design"].text(), cells=len(z["cells"]), area_m2=round(z["area"], 2),
                    fill_grid_m3=round(z["vf"], 2), cut_grid_m3=round(z["vc"], 2),
                    fill_tin_m3=round(z["tvf"], 2), cut_tin_m3=round(z["tvc"], 2)) for z in zones],
        totals=dict(area_m2=round(S("area"), 2), fill_grid_m3=round(S("vf"), 2), cut_grid_m3=round(S("vc"), 2),
                    fill_tin_m3=round(S("tvf"), 2), cut_tin_m3=round(S("tvc"), 2),
                    strip_m3=round(X["strip_v"], 2), slope_fill_m3=round(tf, 2), slope_cut_m3=round(tc, 2),
                    pit_m3=round(pv, 2), pile_m3=round(cv, 2),
                    surplus_tin_m3=round(S("tvc") + tc + pv + cv - K * (S("tvf") + tf), 2)),
        pits=[dict(name=p["name"], area_m2=round(p["area"], 2), bottom=p["zb"], volume_m3=round(p["v"], 2), note=p.get("note", "")) for p in X["pits"]],
        piles=[dict(diameter=p["d"], count=p["n"], length=p["L"], volume_m3=round(p["v"], 2)) for p in X["piles"]],
        balance=dict(mode=bal_mode(bal), level_inside=round(bal[0], 3), level_all_items=round(bal[2], 3)),
        warnings=[f"{t}: {x}" for l, t, x in Q if l == "CẢNH BÁO"],
        errors=[f"{t}: {x}" for l, t, x in Q if l == "LỖI"],
        fixed=[x for l, t, x in Q if l == "ĐÃ SỬA"], files=[str(f) for f in files])


def compute(zones, tin, cfg):
    pieces = []
    for z in zones:
        nodes = z["src"].nodes if cfg["use_grid"] else {}
        for c in z["cells"]:
            cell_calc(c, tin, z["design"], cfg)
            if nodes:
                dz = [abs(nodes[k] - v) for k, v in ((f"{q[0]:.2f},{q[1]:.2f}", v) for q, v in zip(c["xy"], c["zn"])) if k in nodes]
                c["node_diff"] = max(dz, default=0.0)
        ov = Overlay(tin, z["cells"], z["design"])
        h = z["design"](ov.xy.reshape(-1, 2)).reshape(-1, 3) - (ov.z - cfg["strip"])
        Vf, Vc, Sf, Sc = ov.volumes(h)
        n = len(z["cells"])
        vf, vc = np.bincount(ov.own, Vf, n), np.bincount(ov.own, Vc, n)
        sf, sc = np.bincount(ov.own, Sf, n), np.bincount(ov.own, Sc, n)
        for i, c in enumerate(z["cells"]):
            c.update(tvf=float(vf[i]), tvc=float(vc[i]), tsf=float(sf[i]), tsc=float(sc[i]), cover=ov.cover[i])
        z["ov"] = ov
        for k in ("sf", "sc", "vf", "vc", "tvf", "tvc", "tsf", "tsc"):
            z[k] = sum(c[k] for c in z["cells"])
        z["area"] = sum(c["area"] for c in z["cells"])
        pieces.append(ov)
        log(f"  {z['name']}: {len(z['cells'])} ô, S={z['area']:.1f} m2, TK {z['design'].text()} | "
            f"Ô lưới: đắp {z['vf']:.1f} / đào {z['vc']:.1f} | TIN: đắp {z['tvf']:.1f} / đào {z['tvc']:.1f} m3")
    return pieces


def bal_mode(bal):
    return bal[3] if len(bal) > 3 else "level"


class Merged:
    """Ghép overlay các khu để tính cân bằng toàn công trường."""
    volumes = Overlay.volumes

    def __init__(self, ovs, zd=None):
        self.z = np.vstack([o.z for o in ovs])
        self.area = np.concatenate([o.area for o in ovs])
        self.zd = None if zd is None else np.vstack(zd)   # cao độ thiết kế tại đỉnh: có thì cân bằng theo độ dịch


def hml_cause(c):
    h = c["hml"]
    d = max(abs(c["sf"] - h["sf"]), abs(c["sc"] - h["sc"]), abs(c["vf"] - h["vf"]), abs(c["vc"] - h["vc"]))
    if d <= 0.02:
        return "Khớp"
    if c.get("node_diff", 0) > 0.011:
        return "Cao độ nút HML khác TIN"
    if np.any(np.abs(c["h"]) < 1e-9):
        return "Có đỉnh h = 0, HML chia trung bình khác"
    return "Làm tròn cao độ nút 1 cm"


def quality(zones, pts, chk, cfg, tin, T, notes, X=None):
    Q = []
    def add(level, topic, text):
        Q.append((level, topic, text))
    add("OK", "Điểm đo", f"{len(pts)} điểm, cao độ {pts[:, 2].min():.3f} ÷ {pts[:, 2].max():.3f} m")
    add("OK" if not chk["dup"] else "CẢNH BÁO", "Điểm trùng", f"{len(chk['dup'])} cặp điểm cách nhau dưới 5 cm")
    if chk["outlier"]:
        for x, y, z, r in chk["outlier"][:15]:
            add("CẢNH BÁO", "Điểm dị thường", f"X={x:.3f} Y={y:.3f} Z={z:.3f}: cao/thấp hơn mọi điểm lân cận, lệch tối thiểu {r:.2f} m")
    else:
        add("OK", "Điểm dị thường", f"Không có điểm nhô/lõm riêng lẻ quá {chk['lim']:.2f} m so với mọi điểm lân cận")
    if cfg.get("_brk"):
        ok = tin.brk_missing == 0
        add("OK" if ok else "CẢNH BÁO", "Đường gãy", f"{cfg['_brk']} đường, thêm {tin.brk_added} điểm phụ vào TIN"
            + ("" if ok else f"; {tin.brk_missing} đoạn chưa ép được thành cạnh TIN"))
    if cfg.get("_cnt"):
        V, Z = tin.triangles()
        U = unary_union([z["poly"] for z in zones])
        flat = [Polygon(v) for v, zz in zip(V, Z) if np.ptp(zz) < 1e-6]
        fa = sum(p.intersection(U).area for p in flat) if flat else 0.0
        pf = 100 * fa / U.area
        add("OK" if pf < 5 else "CẢNH BÁO", "Đồng mức", f"{cfg['_cnt']} đường đồng mức dùng làm đường gãy"
            + (f"; {fa:.0f} m2 ({pf:.1f}%) là tam giác phẳng nằm giữa cùng một đường đồng mức (đỉnh đồi, đáy trũng), nên bổ sung điểm cao độ ở đó" if pf >= 0.5 else ""))
    for t in notes:
        add("ĐÃ SỬA", "Ranh giới", t)
    tree = cKDTree(pts[:, :2])
    for z in zones:
        n = z["name"]
        out = z["poly"].difference(tin.hull).area
        pa = 100 * out / z["poly"].area
        add("OK" if pa < 0.5 else "CẢNH BÁO" if pa < 5 else "LỖI", n,
            "Toàn khu nằm trong vùng điểm đo" if out < 0.01 else
            f"{out:.1f} m2 ({pa:.1f}% diện tích khu) nằm ngoài vùng điểm đo, cao độ tự nhiên ở đó kéo dài từ các điểm đo ngoài cùng; nên đo bổ sung")
        dA = z["area"] - z["poly"].area
        add("OK" if abs(dA) < 0.5 else "LỖI", n, f"Tổng diện tích ô {z['area']:.2f} m2, ranh giới {z['poly'].area:.2f} m2, lệch {dA:+.2f} m2")
        far = [c["name"] for c in z["cells"]
               if tree.query(np.array(c["poly"].representative_point().coords)[0])[0] > 1.5 * cfg["step"]]
        add("OK" if not far else "CẢNH BÁO", n, f"{len(far)} ô có tâm cách điểm đo gần nhất trên {1.5 * cfg['step']:.1f} m"
            + (": " + ", ".join(far[:12]) if far else ""))
        d = z["design"]
        if d.kind == "tin":
            out = d.outside_area(z["poly"])
            pa = 100 * out / z["poly"].area
            add("OK" if pa < 0.5 else "CẢNH BÁO", n, f"Mặt thiết kế TIN {len(d.kw['pts'])} điểm, cao độ {np.min(d.kw['pts'], axis=0)[2]:.3f} ÷ {np.max(d.kw['pts'], axis=0)[2]:.3f} m"
                + (f"; {out:.1f} m2 ({pa:.1f}%) nằm ngoài vùng điểm thiết kế, cao độ ở đó kéo dài từ biên vùng điểm" if pa >= 0.5 else ""))
        base = z["tvf"] + z["tvc"]
        dv = z["vf"] + z["vc"] - base
        pc = 100 * dv / base if base else 0
        add("OK" if abs(pc) <= 3 or abs(dv) <= 5 else "CẢNH BÁO", n,
            f"Chênh lưới ô so với TIN: {pc:+.2f}% (đắp {z['vf'] - z['tvf']:+.1f}, đào {z['vc'] - z['tvc']:+.1f} m3)")
        if z["n_labels"]:
            lack = [c["name"] for c in z["cells"] if "hml" not in c]
            if lack:
                a = sum(c["area"] for c in z["cells"] if "hml" not in c)
                v = sum(c["vf"] + c["vc"] for c in z["cells"] if "hml" not in c)
                add("LỖI", n, f"{len(lack)} ô lưới không có nhãn khối lượng HML, tổng {a:.1f} m2, {v:.1f} m3 bị bỏ sót")
    ov_total = 0.0
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            s = a["poly"].intersection(b["poly"]).area
            ov_total += s
            if s > 0.05:
                add("CẢNH BÁO", "Ranh giới", f"{a['name']} chồng lấn {b['name']}: {s:.2f} m2, khối lượng phần này bị tính hai lần")
    gaps = find_gaps([z["poly"] for z in zones])
    gap = sum(g.area for g in gaps)
    if gap > 0.05:
        add("CẢNH BÁO", "Ranh giới", f"Khe hở giữa các khu: {gap:.2f} m2 chưa được tính")
    elif len(zones) > 1 and ov_total <= 0.05:
        add("OK", "Ranh giới", "Các khu khít nhau, không chồng lấn, không khe hở")
    if T:
        add("OK" if T["short"] < 0.05 else "CẢNH BÁO", "Taluy", f"{100 * T['short']:.1f}% diện tích mái nằm ngoài vùng có điểm đo, cao độ đất tại đó lấy theo điểm gần nhất")
        if T["width"] >= T["W"] - 2 * cfg["taluy_res"]:
            add("CẢNH BÁO", "Taluy", f"Mái chạm giới hạn rộng {T['W']:.0f} m, khối lượng taluy có thể thiếu")
    if T and T.get("skipped"):
        add("OK", "Taluy", f"Bỏ mái ở các cạnh trên layer không taluy, khoảng {T['skipped']:.0f} m2 mặt bằng ngoài ranh")
    if X:
        if cfg["strip"]:
            add("OK", "Bóc phong hoá", f"Dày {cfg['strip']} m, khối lượng {X['strip_v']:.2f} m3")
        for p in X["pits"]:
            if p["zb"] is None:
                add("CẢNH BÁO", "Hố móng", f"{p['name']} chưa có cao độ đáy, chưa tính. Ghi TEXT cao độ trong polyline hoặc nhập cao độ đáy")
            elif p.get("note"):
                add("OK", "Hố móng", f"{p['name']}: {p['note']}")
        for p in X["piles"]:
            if not p["v"]:
                add("CẢNH BÁO", "Cọc", f"{p['n']} cọc chưa tính được khối lượng, thiếu chiều dài hoặc đường kính")
    if cfg["use_grid"]:
        C = {}
        for z in zones:
            for c in z["cells"]:
                if "hml" in c:
                    k = hml_cause(c)
                    C[k] = C.get(k, 0) + 1
        add("OK", "Đối chiếu HML", "; ".join(f"{k}: {v} ô" for k, v in sorted(C.items(), key=lambda t: -t[1])))
    return Q


# ---------------------------------------------------------------- Excel
def write_excel(path, zones, cfg, bal, Q, K, T=None, X=None):
    X = X or dict(strip_v=0.0, pits=[], piles=[])
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as CL

    NAVY, TEAL, GREY = "1F3864", "D9E7F5", "F2F2F2"
    thin = Side(style="thin", color="BFBFBF")
    B = Border(left=thin, right=thin, top=thin, bottom=thin)
    fn = "Arial"
    def head(c):
        c.font = Font(name=fn, bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = B
    def body(c, nf=None, bold=False, fill=None):
        c.font = Font(name=fn, size=10, bold=bold)
        c.border = B
        if nf:
            c.number_format = nf
        if fill:
            c.fill = PatternFill("solid", fgColor=fill)
    def title(ws, text, sub=None):
        ws["A1"] = text
        ws["A1"].font = Font(name=fn, bold=True, size=14, color=NAVY)
        if sub:
            ws["A2"] = sub
            ws["A2"].font = Font(name=fn, italic=True, size=10, color="595959")

    wb = Workbook()
    ws = wb.active
    ws.title = "Tổng hợp"
    zone_ref = []
    # sheet từng khu
    for z in zones:
        s = wb.create_sheet(z["name"][:31])
        nv = max(4, max(len(c["zn"]) for c in z["cells"]))
        title(s, f"BẢNG TÍNH KHỐI LƯỢNG SAN NỀN - {z['name']} / Earthwork quantities",
              f"Cao độ thiết kế: {z['design'].text()}  |  Bước lưới {cfg['step']} m  |  Đơn vị: m, m2, m3"
              + (f"  |  Đã trừ bóc phong hoá {cfg['strip']} m khi tính khối lượng" if cfg["strip"] else ""))
        r1, r2 = 4, 5
        cols = ["Tên ô"]
        s.cell(r1, 1, "Tên ô\nCell")
        s.merge_cells(start_row=r1, start_column=1, end_row=r2, end_column=1)
        def grp(col, n, text):
            s.cell(r1, col, text)
            if n > 1:
                s.merge_cells(start_row=r1, start_column=col, end_row=r1, end_column=col + n - 1)
        grp(2, nv, "Cao độ tự nhiên / Existing level")
        grp(2 + nv, nv, "Cao độ thiết kế / Design level")
        c0 = 2 + 2 * nv
        grp(c0, 2, "Diện tích (m2) / Area")
        grp(c0 + 2, 2, "Khối lượng lưới ô (m3)")
        grp(c0 + 4, 2, "Khối lượng TIN (m3)")
        for i in range(nv):
            s.cell(r2, 2 + i, i + 1)
            s.cell(r2, 2 + nv + i, i + 1)
        for i, t in enumerate(["Đắp / Fill", "Đào / Cut"] * 3):
            s.cell(r2, c0 + i, t)
        for r in (r1, r2):
            for col in range(1, c0 + 6):
                head(s.cell(r, col))
        r = r2 + 1
        first = r
        for c in z["cells"]:
            body(s.cell(r, 1, c["name"]))
            for i in range(nv):
                body(s.cell(r, 2 + i, float(c["zn"][i]) if i < len(c["zn"]) else None), "0.00")
                body(s.cell(r, 2 + nv + i, float(c["zt"][i]) if i < len(c["zt"]) else None), "0.00")
            for i, k in enumerate(("sf", "sc", "vf", "vc", "tvf", "tvc")):
                body(s.cell(r, c0 + i, round(c[k], 3)), "#,##0.00")
            r += 1
        last = r - 1
        body(s.cell(r, 1, "TỔNG CỘNG"), bold=True, fill=TEAL)
        for col in range(2, c0):
            body(s.cell(r, col), fill=TEAL)
        for i in range(6):
            L = CL(c0 + i)
            body(s.cell(r, c0 + i, f"=SUM({L}{first}:{L}{last})"), "#,##0.00", True, TEAL)
        zone_ref.append((z, s.title, [f"'{s.title}'!{CL(c0 + i)}{r}" for i in range(6)]))
        s.freeze_panes = s.cell(first, 2)
        s.column_dimensions["A"].width = 10
        for col in range(2, c0):
            s.column_dimensions[CL(col)].width = 8
        for col in range(c0, c0 + 6):
            s.column_dimensions[CL(col)].width = 11
        s.row_dimensions[r1].height = 30
        s.sheet_view.showGridLines = False
        s.page_setup.orientation = "landscape"
        s.page_setup.fitToWidth = 1
        s.page_setup.fitToHeight = 0
        s.sheet_properties.pageSetUpPr.fitToPage = True
        s.print_title_rows = f"{r1}:{r2}"

    # Tổng hợp
    title(ws, "BẢNG TỔNG HỢP KHỐI LƯỢNG SAN NỀN / Earthwork summary",
          (f"{cfg['project']}  |  " if cfg["project"] else "") + f"Lập ngày {dt.date.today():%d/%m/%Y}  |  SanNenPro {__version__}")
    hdr = ["STT", "Khu vực\nZone", "Cao độ TK\nDesign level", "Số ô\nCells", "Diện tích ô (m2)\nArea", "S đắp (m2)\nFill area", "S đào (m2)\nCut area",
           "V đắp lưới ô (m3)", "V đào lưới ô (m3)", "V đắp TIN (m3)", "V đào TIN (m3)", "Chênh lưới ô/TIN (%)"]
    r0 = 4
    for i, t in enumerate(hdr):
        head(ws.cell(r0, 1 + i, t))
    ws.row_dimensions[r0].height = 44
    r = r0 + 1
    for i, (z, sn, ref) in enumerate(zone_ref):
        body(ws.cell(r, 1, i + 1))
        body(ws.cell(r, 2, z["name"]))
        body(ws.cell(r, 3, z["design"].text()))
        body(ws.cell(r, 4, len(z["cells"])))
        body(ws.cell(r, 5, f"=F{r}+G{r}"), "#,##0.00")
        for j, k in enumerate((0, 1, 2, 3, 4, 5)):
            body(ws.cell(r, 6 + j, "=" + ref[k]), "#,##0.00")
        body(ws.cell(r, 12, f'=IF(J{r}+K{r}=0,0,(H{r}+I{r}-J{r}-K{r})/(J{r}+K{r}))'), "0.00%")
        r += 1
    a, b = r0 + 1, r - 1
    body(ws.cell(r, 1), fill=TEAL)
    body(ws.cell(r, 2, "TỔNG CỘNG"), bold=True, fill=TEAL)
    body(ws.cell(r, 3), fill=TEAL)
    body(ws.cell(r, 4, f"=SUM(D{a}:D{b})"), None, True, TEAL)
    for col in range(5, 12):
        L = CL(col)
        body(ws.cell(r, col, f"=SUM({L}{a}:{L}{b})"), "#,##0.00", True, TEAL)
    body(ws.cell(r, 12, f'=IF(J{r}+K{r}=0,0,(H{r}+I{r}-J{r}-K{r})/(J{r}+K{r}))'), "0.00%", True, TEAL)
    tot = r
    r += 2
    ws.cell(r, 2, "CÂN ĐỐI ĐẤT / Earthwork balance").font = Font(name=fn, bold=True, size=11, color=NAVY)
    r += 1
    head(ws.cell(r, 2, "Hạng mục"))
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
    head(ws.cell(r, 5, "Lưới ô (m3)"))
    head(ws.cell(r, 6, "TIN (m3)"))
    r += 1
    kr = r
    def line(text, a, b, nf="#,##0.00", bold=False):
        nonlocal r
        body(ws.cell(r, 2, text), bold=bold)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        body(ws.cell(r, 5, a), nf, bold)
        body(ws.cell(r, 6, b), nf, bold)
        r += 1
    line("Hệ số K (đào / đắp đã đầm)", K, f"=E{kr}", "0.00")
    ws.cell(kr, 5).fill = PatternFill("solid", fgColor="FFF2CC")
    a0 = r
    line("V đắp trong ranh", f"=H{tot}", f"=J{tot}")
    line("V đào trong ranh", f"=I{tot}", f"=K{tot}")
    tf = tc = 0.0
    if T:
        tf, tc = float(T["vf"].sum()), float(T["vc"].sum())
    line("V đắp taluy", round(tf, 2), round(tf, 2))
    line("V đào taluy", round(tc, 2), round(tc, 2))
    pv, cv = sum(p["v"] for p in X["pits"]), sum(p["v"] for p in X["piles"])
    line("V đào hố móng", round(pv, 2), round(pv, 2))
    line("V đất khoan cọc", round(cv, 2), round(cv, 2))
    line("Đất cần cho đắp (K x V đắp)", f"=E{kr}*(E{a0}+E{a0 + 2})", f"=F{kr}*(F{a0}+F{a0 + 2})")
    line("Đất thừa (+) / thiếu (-)", f"=E{a0 + 1}+E{a0 + 3}+E{a0 + 4}+E{a0 + 5}-E{a0 + 6}", f"=F{a0 + 1}+F{a0 + 3}+F{a0 + 4}+F{a0 + 5}-F{a0 + 6}",
         "#,##0.00;[Red]-#,##0.00", True)
    line("Đất bóc phong hoá, không dùng đắp", round(X["strip_v"], 2), round(X["strip_v"], 2))
    if bal_mode(bal) == "level":
        line("Cao độ cân bằng trong ranh (TIN)", round(bal[0], 3), None, "0.000", True)
        line("Cao độ cân bằng gồm mọi hạng mục", round(bal[2], 3), None, "0.000", True)
    else:
        line("Dịch mặt thiết kế để cân bằng, trong ranh (m)", round(bal[0], 3), None, "+0.000;-0.000;0.000", True)
        line("Dịch mặt thiết kế để cân bằng, gồm mọi hạng mục (m)", round(bal[2], 3), None, "+0.000;-0.000;0.000", True)
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 13
    ws.column_dimensions["D"].width = 8
    for col in range(5, 13):
        ws.column_dimensions[CL(col)].width = 13
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    # Cân bằng
    s = wb.create_sheet("Cân bằng")
    title(s, "ĐƯỜNG CONG CÂN BẰNG ĐÀO ĐẮP / Balance curve",
          f"San phẳng toàn bộ phạm vi tính ở một cao độ, K = {K}. Cao độ cân bằng: {bal[0]:.3f} m" if bal_mode(bal) == "level" else
          f"Giữ hình dạng mặt thiết kế, nâng hạ cả mặt, K = {K}. Dịch để cân bằng: {bal[0]:+.3f} m")
    for i, t in enumerate(["Cao độ san (m)" if bal_mode(bal) == "level" else "Dịch mặt thiết kế (m)", "V đắp (m3)", "V đào (m3)", "Đất thừa/thiếu (m3)"]):
        head(s.cell(4, 1 + i, t))
    r = 5
    for t, vf, vc in bal[1]:
        body(s.cell(r, 1, t), "0.00")
        body(s.cell(r, 2, round(vf, 2)), "#,##0.0")
        body(s.cell(r, 3, round(vc, 2)), "#,##0.0")
        body(s.cell(r, 4, f"=C{r}-{K}*B{r}"), "#,##0.0;[Red]-#,##0.0")
        r += 1
    for col, w in zip("ABCD", (14, 14, 14, 18)):
        s.column_dimensions[col].width = w
    ch = LineChart()
    ch.title = "Khối lượng theo cao độ san"
    ch.height, ch.width = 10, 18
    ch.y_axis.title = "m3"
    ch.x_axis.title = "Cao độ san (m)"
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ch.add_data(Reference(s, min_col=2, max_col=3, min_row=4, max_row=r - 1), titles_from_data=True)
    ch.set_categories(Reference(s, min_col=1, min_row=5, max_row=r - 1))
    s.add_chart(ch, "F4")
    s.sheet_view.showGridLines = False

    # Taluy
    if T:
        s = wb.create_sheet("Taluy")
        title(s, "KHỐI LƯỢNG MÁI TALUY / Slope quantities",
              f"Mái đào 1:{T['mc'] or '-'}  |  Mái đắp 1:{T['mf'] or '-'}  |  Tính ngoài ranh giới, lưới {cfg['taluy_res']} m")
        for i, t in enumerate(["Khu vực", "S đắp (m2)", "S đào (m2)", "V đắp (m3)", "V đào (m3)"]):
            head(s.cell(4, 1 + i, t))
        r = 5
        for i, n in enumerate(T["names"]):
            body(s.cell(r, 1, n))
            for j, k in enumerate(("sf", "sc", "vf", "vc")):
                body(s.cell(r, 2 + j, round(float(T[k][i]), 2)), "#,##0.00")
            r += 1
        body(s.cell(r, 1, "TỔNG CỘNG"), bold=True, fill=TEAL)
        for j in range(4):
            L = CL(2 + j)
            body(s.cell(r, 2 + j, f"=SUM({L}5:{L}{r - 1})"), "#,##0.00", True, TEAL)
        for col in "ABCDE":
            s.column_dimensions[col].width = 14
        s.sheet_view.showGridLines = False

    # Hố móng, cọc
    if X["pits"] or X["piles"]:
        s = wb.create_sheet("Hố móng, cọc")
        title(s, "HỐ MÓNG VÀ CỌC / Pits and piles", f"Mái hố 1:{cfg['pit_slope']}, đào từ mặt sau san nền")
        for i, t in enumerate(["Hạng mục", "Diện tích đáy (m2)", "Cao độ đáy", "Số cọc", "D (m)", "L (m)", "V (m3)"]):
            head(s.cell(4, 1 + i, t))
        r = 5
        for p in X["pits"]:
            for j, v in enumerate((p["name"] + (f" ({p['note']})" if p.get("note") else ""), round(p["area"], 2), p["zb"], None, None, None, round(p["v"], 2))):
                body(s.cell(r, 1 + j, v), None if j in (0, 3, 4, 5) else "#,##0.00")
            r += 1
        for p in X["piles"]:
            for j, v in enumerate((f"Cọc D{p['d']}", None, None, p["n"], p["d"], p["L"], round(p["v"], 2))):
                body(s.cell(r, 1 + j, v), "#,##0.00" if j == 6 else None)
            r += 1
        body(s.cell(r, 1, "TỔNG CỘNG"), bold=True, fill=TEAL)
        for j in range(2, 7):
            body(s.cell(r, j), fill=TEAL)
        body(s.cell(r, 7, f"=SUM(G5:G{r - 1})"), "#,##0.00", True, TEAL)
        for col in "ABCDEFG":
            s.column_dimensions[col].width = 14
        s.sheet_view.showGridLines = False

    # Kiểm tra
    s = wb.create_sheet("Kiểm tra")
    title(s, "KIỂM TRA SỐ LIỆU / Quality checks")
    for i, t in enumerate(["Mức", "Hạng mục", "Nội dung"]):
        head(s.cell(3, 1 + i, t))
    colr = {"OK": "E2EFDA", "CẢNH BÁO": "FFF2CC", "LỖI": "F8CBAD", "ĐÃ SỬA": "DDEBF7"}
    for i, (lv, tp, tx) in enumerate(Q):
        body(s.cell(4 + i, 1, lv), fill=colr[lv])
        body(s.cell(4 + i, 2, tp))
        c = s.cell(4 + i, 3, tx)
        body(c)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    s.column_dimensions["A"].width = 12
    s.column_dimensions["B"].width = 18
    s.column_dimensions["C"].width = 95
    s.sheet_view.showGridLines = False

    # Đối chiếu HML
    if any("hml" in c for z in zones for c in z["cells"]):
        s = wb.create_sheet("Đối chiếu HML")
        title(s, "ĐỐI CHIẾU VỚI KẾT QUẢ HML TRONG BẢN VẼ / Comparison with HML labels")
        hd = ["Khu vực", "Ô", "S đắp HML", "S đắp script", "S đào HML", "S đào script", "V đắp HML", "V đắp script", "V đào HML", "V đào script", "Lệch |V| (m3)", "Nguyên nhân"]
        for i, t in enumerate(hd):
            head(s.cell(3, 1 + i, t))
        s.row_dimensions[3].height = 30
        r = 4
        for z in zones:
            for c in z["cells"]:
                h = c.get("hml")
                if not h:
                    continue
                vals = [z["name"], c["name"], h["sf"], round(c["sf"], 2), h["sc"], round(c["sc"], 2), h["vf"], round(c["vf"], 2), h["vc"], round(c["vc"], 2)]
                for i, v in enumerate(vals):
                    body(s.cell(r, 1 + i, v), None if i < 2 else "#,##0.00")
                body(s.cell(r, 11, f"=ABS(G{r}-H{r})+ABS(I{r}-J{r})"), "0.00")
                body(s.cell(r, 12, hml_cause(c)))
                r += 1
        for col in range(1, 12):
            s.column_dimensions[CL(col)].width = 11
        s.column_dimensions["L"].width = 38
        s.freeze_panes = "C4"
        s.sheet_view.showGridLines = False
    wb.save(path)
    recalc_excel(path)


def recalc_excel(path):
    """Mở bằng Excel (nếu có) để lưu sẵn giá trị công thức, xem được trên điện thoại."""
    try:
        import pythoncom
        import win32com.client as w
        pythoncom.CoInitialize()
        xl = w.DispatchEx("Excel.Application")
    except Exception:
        return
    try:
        xl.Visible = False
        xl.DisplayAlerts = False
        b = xl.Workbooks.Open(str(Path(path).resolve()))
        xl.CalculateFull()
        b.Save()
        b.Close(False)
    except Exception as e:
        log(f"  Bỏ qua bước Excel tính lại công thức: {e}")
    finally:
        xl.Quit()


# ---------------------------------------------------------------- Bản vẽ DXF
LAYERS = {
    "SN-RanhGioi": 1, "SN-Luoi": 8, "SN-DiemDo": 9, "SN-Nut": 7, "SN-DuongKhong": 6,
    "SN-Dap": 3, "SN-Dao": 1, "SN-O": 7, "SN-Bang": 7, "SN-Taluy": 30, "SN-HoMong": 5,
    "SN-TIN-TuNhien": 92, "SN-TIN-ThietKe": 10, "SN-DiemTK": 10,
}


def text_rot(a):
    """Góc chữ dễ đọc nhất trong họ góc của lưới (-45..45 độ)."""
    return (a + 45) % 90 - 45


def write_dxf(path, zones, pts, cfg, K, bal, T=None, X=None, tin=None):
    doc = ezdxf.new("R2013", setup=False)
    doc.header["$INSUNITS"] = 6
    doc.styles.add("SN", font="arial.ttf")
    for n, col in LAYERS.items():
        doc.layers.add(n, color=col)
    th = cfg["text_h"] or round(cfg["step"] * 0.075, 2)
    txt = {"style": "SN", "height": th, "layer": "0"}

    nb = doc.blocks.new("SN_NUT")
    r = th * 0.5
    nb.add_line((-r, 0), (r, 0))
    nb.add_line((0, -r), (0, r))
    for tag, y, col in (("CDTK", th * 0.3, 1), ("CDTN", -th * 1.1, 3)):
        a = nb.add_attdef(tag, (th * 0.5, y), dxfattribs={**txt, "color": col, "height": th * 0.8})
    nb.add_attdef("CC", (-th * 0.5, th * 0.3), dxfattribs={**txt, "color": 5, "height": th * 0.8}).set_placement(
        (-th * 0.5, th * 0.3), align=TextEntityAlignment.BOTTOM_RIGHT)

    ob = doc.blocks.new("SN_O")
    for i, tag in enumerate(("TEN", "SDAP", "SDAO", "VDAP", "VDAO")):
        h = th * (1.2 if i == 0 else 0.9)
        ob.add_attdef(tag, (0, 0), dxfattribs={**txt, "height": h, "color": 2 if i == 0 else 7}).set_placement(
            (0, (2 - i) * th * 1.35), align=TextEntityAlignment.MIDDLE_CENTER)

    msp = doc.modelspace()
    for x, y, z in pts:
        msp.add_point((x, y, z), dxfattribs={"layer": "SN-DiemDo"})
        msp.add_text(f"{z:.3f}", dxfattribs={"layer": "SN-DiemDo", "style": "SN", "height": th * 0.55, "insert": (x, y)})
    # mạng tam giác để kiểm tra bằng mắt: TIN tự nhiên và TIN thiết kế (nếu có)
    U = unary_union([z["poly"] for z in zones]).buffer(2 * cfg["step"])
    def tin_lines(V, Z, layer):
        seen = set()
        for v, zz in zip(V, Z):
            if not U.intersects(Polygon(v)):
                continue
            for i in range(3):
                a, b = (tuple(np.round(v[i], 3)), float(zz[i])), (tuple(np.round(v[(i + 1) % 3], 3)), float(zz[(i + 1) % 3]))
                k = (a[0], b[0]) if a[0] < b[0] else (b[0], a[0])
                if k not in seen:
                    seen.add(k)
                    msp.add_line((*a[0], a[1]), (*b[0], b[1]), dxfattribs={"layer": layer})
    if tin is not None:
        tin_lines(*tin.triangles(), "SN-TIN-TuNhien")
    done = set()
    for z in zones:
        d = z["design"]
        key = tuple(np.round(np.asarray(d.kw["pts"], float).ravel(), 3)) if d.kind == "tin" else None
        if key and key not in done:
            done.add(key)
            tin_lines(*d.tin.triangles(), "SN-TIN-ThietKe")
            for x, y, zz in d.kw["pts"]:
                msp.add_text(f"{zz:.3f}", dxfattribs={"layer": "SN-DiemTK", "style": "SN", "height": th * 0.55, "insert": (x, y)})

    def hatch(p, layer, color):
        h = msp.add_hatch(color=color, dxfattribs={"layer": layer})
        h.paths.add_polyline_path([tuple(q) for q in p], is_closed=True)
        h.transparency = 0.6

    for z in zones:
        msp.add_lwpolyline(list(z["poly"].exterior.coords[:-1]), close=True,
                           dxfattribs={"layer": "SN-RanhGioi", "const_width": th * 0.25})
        nodes = {}
        for c in z["cells"]:
            msp.add_lwpolyline([tuple(q) for q in c["xy"]], close=True, dxfattribs={"layer": "SN-Luoi"})
            for p, _ in c["fill"]:
                hatch(p, "SN-Dap", 3)
            for p, _ in c["cut"]:
                hatch(p, "SN-Dao", 1)
            for a, b in c["zero"]:
                msp.add_line(a, b, dxfattribs={"layer": "SN-DuongKhong"})
            for q, zn, zt in zip(c["xy"], c["zn"], c["zt"]):
                nodes[(round(q[0], 3), round(q[1], 3))] = (zn, zt)
            pt = c["poly"].representative_point()
            ref = msp.add_blockref("SN_O", (pt.x, pt.y), dxfattribs={"layer": "SN-O", "rotation": text_rot(z["rot"])})
            ref.add_auto_attribs(dict(TEN=c["name"], SDAP=f"Sđắp={c['sf']:.2f}", SDAO=f"Sđào={c['sc']:.2f}",
                                      VDAP=f"Vđắp={c['vf']:.2f}", VDAO=f"Vđào={c['vc']:.2f}"))
        for (x, y), (zn, zt) in nodes.items():
            ref = msp.add_blockref("SN_NUT", (x, y), dxfattribs={"layer": "SN-Nut", "rotation": text_rot(z["rot"])})
            ref.add_auto_attribs(dict(CDTN=f"{zn:.2f}", CDTK=f"{zt:.2f}", CC=f"{zt - zn + cfg['strip']:+.2f}"))

    # bảng tổng hợp đặt bên phải khu vực
    B = unary_union([z["poly"] for z in zones]).bounds
    u = cfg["step"] * 1.2
    x0, y0 = B[2] + 4 * u, B[3]
    cols = [("Khu vực", 3.2), ("Diện tích (m²)", 3.2), ("V đắp ô (m³)", 3.2), ("V đào ô (m³)", 3.2), ("V đắp TIN (m³)", 3.2), ("V đào TIN (m³)", 3.2)]
    W = [c[1] * u for c in cols]
    rows = [[z["name"], z["area"], z["vf"], z["vc"], z["tvf"], z["tvc"]] for z in zones]
    if T:
        rows.append(["Taluy", float(T["sf"].sum() + T["sc"].sum()), float(T["vf"].sum()), float(T["vc"].sum()), float(T["vf"].sum()), float(T["vc"].sum())])
        for a in T["lines"]:
            msp.add_lwpolyline([tuple(q) for q in a], dxfattribs={"layer": "SN-Taluy"})
    for p in (X or {}).get("pits", []):
        msp.add_lwpolyline(list(p["poly"].exterior.coords[:-1]), close=True, dxfattribs={"layer": "SN-HoMong"})
        c = p["poly"].representative_point()
        msp.add_text(f"{p['name']} V={p['v']:,.1f}", dxfattribs={"layer": "SN-HoMong", "style": "SN", "height": th * 1.3, "insert": (c.x, c.y)})
    if X and X["pits"]:
        v = sum(p["v"] for p in X["pits"])
        rows.append(["Hố móng", sum(p["area"] for p in X["pits"]), 0.0, v, 0.0, v])
    if X and X["piles"]:
        v = sum(p["v"] for p in X["piles"])
        rows.append(["Cọc", 0.0, 0.0, v, 0.0, v])
    rows.append(["TỔNG", *[sum(r[i] for r in rows) for i in range(1, 6)]])
    rh = u * 0.8
    Hh = th * 2.2
    msp.add_text("BẢNG TỔNG HỢP KHỐI LƯỢNG SAN NỀN", dxfattribs={"layer": "SN-Bang", "style": "SN", "height": Hh, "insert": (x0, y0 + rh * 0.5)})
    def cell(i, j, s, bold=False):
        x = x0 + sum(W[:i]) + W[i] / 2
        y = y0 - (j + 0.5) * rh
        t = msp.add_text(str(s), dxfattribs={"layer": "SN-Bang", "style": "SN", "height": th * (1.5 if bold else 1.3)})
        t.set_placement((x, y), align=TextEntityAlignment.MIDDLE_CENTER)
    for i, (t, _) in enumerate(cols):
        cell(i, 0, t, True)
    for j, r in enumerate(rows):
        for i, v in enumerate(r):
            cell(i, j + 1, v if i == 0 else f"{v:,.2f}", j == len(rows) - 1)
    nr = len(rows) + 1
    tw = sum(W)
    for j in range(nr + 1):
        msp.add_line((x0, y0 - j * rh), (x0 + tw, y0 - j * rh), dxfattribs={"layer": "SN-Bang"})
    xx = x0
    for w in [0] + W:
        xx += w
        msp.add_line((xx, y0), (xx, y0 - nr * rh), dxfattribs={"layer": "SN-Bang"})
    # chú giải
    ly = y0 - (nr + 1.5) * rh
    notes = [("Đắp / Fill", 3), ("Đào / Cut", 1)]
    for i, (s, col) in enumerate(notes):
        y = ly - i * rh
        hatch([(x0, y), (x0 + u, y), (x0 + u, y + rh * .6), (x0, y + rh * .6)], "SN-Bang", col)
        msp.add_text(s, dxfattribs={"layer": "SN-Bang", "style": "SN", "height": th * 1.3, "insert": (x0 + u * 1.3, y + rh * .1)})
    msp.add_text(f"Bước lưới {cfg['step']} m  |  K = {K}  |  " + (f"Cao độ cân bằng: {bal[2]:.3f} m" if bal_mode(bal) == "level" else f"Dịch mặt thiết kế để cân bằng: {bal[2]:+.3f} m"),
                 dxfattribs={"layer": "SN-Bang", "style": "SN", "height": th * 1.2, "insert": (x0, ly - 2 * rh)})
    doc.saveas(path)


# ---------------------------------------------------------------- PDF báo cáo
def write_pdf(path, zones, cfg, K, bal, Q, T=None, X=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.collections import PolyCollection, LineCollection
    from matplotlib.colors import TwoSlopeNorm
    import logging
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    plt.rcParams["font.family"] = ["Arial", "DejaVu Sans"]
    polys, vals = [], []
    for z in zones:
        for c in z["cells"]:
            for parts, sgn in ((c["fill"], 1), (c["cut"], -1)):
                for p, hh in parts:
                    polys.append(np.array(p))
                    vals.append(sgn * float(np.mean(hh)))
    vals = np.array(vals)
    vm = max(abs(vals).max(), 0.01)
    with PdfPages(path) as pdf:
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        pc = PolyCollection(polys, array=vals, cmap="RdYlGn", norm=TwoSlopeNorm(0, -vm, vm), edgecolors="none")
        ax.add_collection(pc)
        for z in zones:
            ax.add_collection(LineCollection([c["xy"].tolist() + [c["xy"][0].tolist()] for c in z["cells"]], colors="#00000022", linewidths=.25))
            x, y = z["poly"].exterior.xy
            ax.plot(x, y, color="#1F3864", lw=1.1)
            p = z["poly"].representative_point()
            ax.text(p.x, p.y, z["name"], ha="center", va="center", fontsize=9, weight="bold", color="#1F3864", rotation=text_rot(zones[0]["rot"]))
        if T:
            for a in T["lines"]:
                ax.plot(a[:, 0], a[:, 1], color="#B45F06", lw=.9, ls="--")
        ax.set_aspect("equal")
        ax.autoscale_view()
        ax.set_title(f"{cfg['project'] or 'San nền'}: chiều cao đắp (+) / đào (-) theo ô", fontsize=13, weight="bold", color="#1F3864", loc="left")
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.ticklabel_format(useOffset=False, style="plain")
        fig.colorbar(pc, ax=ax, shrink=.7, label="h = TK - TN (m)")
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

        fig, (a1, a2) = plt.subplots(2, 1, figsize=(11.69, 8.27), gridspec_kw=dict(height_ratios=[1.1, 1]))
        a1.axis("off")
        a1.set_title("Tổng hợp khối lượng (m³)", loc="left", fontsize=13, weight="bold", color="#1F3864")
        hdr = ["Khu vực", "Cao độ TK", "Diện tích (m²)", "V đắp ô", "V đào ô", "V đắp TIN", "V đào TIN"]
        rows = [[z["name"], z["design"].text()[:20], f"{z['area']:,.1f}", f"{z['vf']:,.1f}", f"{z['vc']:,.1f}", f"{z['tvf']:,.1f}", f"{z['tvc']:,.1f}"] for z in zones]
        tf, tc, ts = (float(T["vf"].sum()), float(T["vc"].sum()), float(T["sf"].sum() + T["sc"].sum())) if T else (0, 0, 0)
        if T:
            rows.append(["Taluy", "", f"{ts:,.1f}", f"{tf:,.1f}", f"{tc:,.1f}", f"{tf:,.1f}", f"{tc:,.1f}"])
        pv = sum(p["v"] for p in X["pits"]) if X else 0
        cv = sum(p["v"] for p in X["piles"]) if X else 0
        if pv:
            rows.append(["Hố móng", "", "", "0.0", f"{pv:,.1f}", "0.0", f"{pv:,.1f}"])
        if cv:
            rows.append(["Cọc", "", "", "0.0", f"{cv:,.1f}", "0.0", f"{cv:,.1f}"])
        s = lambda k: sum(z[k] for z in zones)
        ex = tc + pv + cv
        rows.append(["TỔNG", "", f"{s('area') + ts:,.1f}", f"{s('vf') + tf:,.1f}", f"{s('vc') + ex:,.1f}", f"{s('tvf') + tf:,.1f}", f"{s('tvc') + ex:,.1f}"])
        t = a1.table(cellText=rows, colLabels=hdr, loc="upper center", cellLoc="center")
        t.auto_set_font_size(False)
        t.set_fontsize(9)
        t.scale(1, 1.25)
        for (i, j), c in t.get_celld().items():
            c.set_edgecolor("#BFBFBF")
            if i == 0:
                c.set_facecolor("#1F3864")
                c.set_text_props(color="w", weight="bold")
            elif i == len(rows):
                c.set_facecolor("#D9E7F5")
                c.set_text_props(weight="bold")
        tt, vf, vc = map(np.array, zip(*bal[1]))
        a2.plot(tt, vf, color="#2E7D32", lw=2, label="V đắp")
        a2.plot(tt, vc, color="#C62828", lw=2, label="V đào")
        a2.axvline(bal[0], color="#1F3864", ls="--", lw=1)
        a2.text(bal[0], a2.get_ylim()[1] * .92, f"  Cân bằng trong ranh {bal[0]:{'.3f' if bal_mode(bal) == 'level' else '+.3f'}} m (K={K})", color="#1F3864", fontsize=10)
        a2.set_xlabel("Cao độ san phẳng (m)" if bal_mode(bal) == "level" else "Dịch mặt thiết kế (m)")
        a2.set_ylabel("m³")
        a2.grid(alpha=.3)
        a2.legend(frameon=False)
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

        bad = [q for q in Q if q[0] != "OK"]
        if bad:
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            ax.axis("off")
            ax.set_title("Các điểm cần kiểm tra", loc="left", fontsize=13, weight="bold", color="#1F3864")
            y = .97
            for lv, tp, tx in bad[:32]:
                ax.text(0, y, f"[{lv}] {tp}: {tx}"[:150], fontsize=9, color="#C62828" if lv == "LỖI" else "#7F6000", transform=ax.transAxes)
                y -= .03
            pdf.savefig(fig)
            plt.close(fig)


# ---------------------------------------------------------------- Chương trình chính
def run(inputs, cfg, out=None, no_dwg=False):
    inputs = [Path(p) for p in inputs]
    for p in inputs:
        if not p.exists():
            raise SystemExit(f"Không thấy file: {p}")
    out = Path(out) if out else inputs[0].parent / f"{inputs[0].stem}_SANNEN"
    out.mkdir(parents=True, exist_ok=True)

    log(f"SanNenPro {__version__}\n1. Đọc bản vẽ")
    sources = read_sources(inputs, cfg)
    cnt = [q for s in sources for q in s.cnt]
    pts = dedupe([r for s in sources for r in s.pts] + [list(v) for q in cnt for v in q])
    if len(pts) < 3:
        raise SystemExit("Không tìm thấy điểm cao độ. Hãy chọn đúng layer cao độ tự nhiên.")
    if not any(s.bdys for s in sources):
        raise SystemExit("Không tìm thấy ranh giới (polyline kín). Hãy chọn đúng layer ranh giới.")
    brk, seen = [], set()
    for s in sources:
        for line in s.brk + s.cnt:
            k = tuple(np.round(np.array(line).ravel(), 3))
            if k not in seen:
                seen.add(k)
                brk.append(line)
    cfg = dict(cfg, _brk=len(brk), _cnt=len(cnt))

    log(f"2. Dựng TIN từ {len(pts)} điểm, {len(brk)} đường gãy" + (f" (gồm {len(cnt)} đường đồng mức)" if cnt else "") + " và tính khối lượng")
    tin = TIN(pts, brk or None)
    chk = check_points(pts)
    zones, notes = build_zones(sources, cfg)
    ovs = compute(zones, tin, cfg)
    noslope = [l for s in sources for l in s.noslope]
    T = calc_taluy(zones, tin, cfg, noslope)
    if T:
        log(f"  Taluy: đắp {T['vf'].sum():.1f} / đào {T['vc'].sum():.1f} m3")
    seen_p, pits = set(), []
    for s in sources:
        for g, zb in s.pits:
            k = tuple(np.round(g.bounds, 2))
            if k not in seen_p:
                seen_p.add(k)
                pits.append((g, zb))
    piles = list({(round(x, 2), round(y, 2)): (x, y, r) for s in sources for x, y, r in s.piles}.values())
    X = dict(strip_v=sum(z["area"] for z in zones) * cfg["strip"], pits=calc_pits(zones, tin, cfg, pits), piles=calc_piles(cfg, piles))
    for p in X["pits"]:
        log(f"  {p['name']}: đáy {p['zb']}, V = {p['v']:.1f} m3")
    for p in X["piles"]:
        log(f"  Cọc D{p['d']}: {p['n']} cọc, V = {p['v']:.1f} m3")
    if piles and cfg["pile_len"]:
        pp = []
        for x, y, r in piles:
            dia = 2 * r if r else cfg["pile_dia"]
            if not dia:
                continue
            pt = Point(x, y)
            top = min((p["zb"] for p in X["pits"] if p["zb"] is not None and p["poly"].contains(pt)), default=None)
            if top is None:
                zz = [z for z in zones if z["poly"].contains(pt)]
                top = float(zz[0]["design"](np.array([[x, y]]))[0]) if zz else float(tin.filled(np.array([[x, y]]))[0][0] - cfg["strip"])
            pp.append(dict(x=x, y=y, top=top, d=dia, L=cfg["pile_len"]))
        X["pile_points"] = pp

    log("3. Cân bằng đào đắp và kiểm tra số liệu")
    flat = all(z["design"].kind == "flat" for z in zones)
    mer = Merged(ovs, None if flat else [z["design"](o.xy.reshape(-1, 2)).reshape(-1, 3) for z, o in zip(zones, ovs)])
    mer.z = mer.z - cfg["strip"]
    b0 = balance(mer, cfg["k"])
    extra = sum(p["v"] for p in X["pits"]) + sum(p["v"] for p in X["piles"])
    ctx = taluy_ctx(zones, tin, cfg, res=max(1.0, cfg["taluy_res"]), noslope=noslope) if T else None
    ze0 = None
    if ctx and not flat:
        ze0 = np.zeros(len(ctx["d"]))
        for i, z in enumerate(zones):
            m = ctx["owner"] == i
            if m.any():
                ze0[m] = z["design"](ctx["edge"][m])
    bal = (b0[0], b0[1], balance_full(mer, cfg["k"], ctx, extra, ze0) if (ctx or extra) else b0[0], "level" if flat else "offset")
    Q = quality(zones, pts, chk, cfg, tin, T, notes, X)
    for lv, tp, tx in Q:
        if lv != "OK":
            log(f"  [{lv}] {tp}: {tx}")

    log("4. Xuất kết quả")
    write_excel(out / "SanNen_KhoiLuong.xlsx", zones, cfg, bal, Q, cfg["k"], T, X)
    dxf = out / "SanNen_MatBang.dxf"
    write_dxf(dxf, zones, pts, cfg, cfg["k"], bal, T, X, tin)
    write_pdf(out / "SanNen_BaoCao.pdf", zones, cfg, cfg["k"], bal, Q, T, X)
    if not no_dwg:
        d = dxf_to_dwg(dxf)
        log("  DWG: " + (d.name if d else "bỏ qua, dùng file DXF"))
    if cfg["export_3d"]:
        import sannen3d
        log("  Đang dựng khối 3D" + (" và đổi sang solid trong AutoCAD" if find_accore() else ""))
        f3, chk3 = sannen3d.export(out, zones, tin, T, X, cfg, bal)
        log("  3D: " + ", ".join(p.name for p in f3))
        if chk3.get("solid"):
            for k, v in chk3["solid"]["layers"].items():
                d = v["solid"] - v["table"]
                log(f"    Solid {k}: {v['solid']:,.2f} m3, bảng tính {v['table']:,.2f} m3" + ("" if abs(d) <= max(0.05, 0.001 * v["table"]) else f", chênh {d:+,.2f}"))
            if chk3["solid"]["mesh_left"]:
                log(f"    [CẢNH BÁO] {chk3['solid']['mesh_left']} khối chưa đổi được sang solid, vẫn để dạng mesh")

    S = lambda k: sum(z[k] for z in zones)
    log(f"\nKẾT QUẢ\n  Lưới ô: đắp {S('vf'):,.2f} | đào {S('vc'):,.2f} m3\n  TIN   : đắp {S('tvf'):,.2f} | đào {S('tvc'):,.2f} m3")
    if T:
        log(f"  Taluy : đắp {T['vf'].sum():,.2f} | đào {T['vc'].sum():,.2f} m3")
    if X["strip_v"] or X["pits"] or X["piles"]:
        log(f"  Bóc phong hoá {X['strip_v']:,.2f} | hố móng {sum(p['v'] for p in X['pits']):,.2f} | cọc {sum(p['v'] for p in X['piles']):,.2f} m3")
    if bal_mode(bal) == "level":
        log(f"  Cao độ cân bằng (K={cfg['k']}): {bal[0]:.3f} m trong ranh, {bal[2]:.3f} m gồm mọi hạng mục\n  Thư mục: {out}")
    else:
        log(f"  Mặt thiết kế không phẳng. Dịch cả mặt để cân bằng (K={cfg['k']}): {bal[0]:+.3f} m trong ranh, {bal[2]:+.3f} m gồm mọi hạng mục\n  Thư mục: {out}")
    files = sorted(p for p in out.iterdir() if p.name.startswith("SanNen_"))
    res = summary(zones, T, X, bal, cfg, Q, inputs, out, files, [s.layers for s in sources])
    if cfg["export_3d"]:
        res["check_3d"] = chk3
    (out / "SanNen_KetQua.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(zones=zones, Q=Q, bal=bal, T=T, X=X, out=out, tin=tin, summary=res)


def main(argv=None):
    ap = argparse.ArgumentParser(description="SanNenPro: tính khối lượng san nền từ DWG/DXF")
    ap.add_argument("inputs", nargs="+", help="file DWG hoặc DXF")
    ap.add_argument("--config", help="file JSON cấu hình")
    ap.add_argument("--td", type=float, help="cao độ thiết kế phẳng (m)")
    ap.add_argument("--step", type=float, help="bước lưới (m)")
    ap.add_argument("--rot", type=float, help="góc xoay lưới (độ)")
    ap.add_argument("--k", type=float, help="hệ số K đất đào / đất đắp đã đầm")
    ap.add_argument("--taluy-dao", type=float, dest="taluy_cut", help="hệ số mái đào m (1:m)")
    ap.add_argument("--taluy-dap", type=float, dest="taluy_fill", help="hệ số mái đắp m (1:m)")
    ap.add_argument("--boc", type=float, dest="strip", help="chiều dày bóc phong hoá (m)")
    ap.add_argument("--mai-ho", type=float, dest="pit_slope", help="hệ số mái hố móng m (1:m); 0 = thành đứng")
    ap.add_argument("--day-ho", type=float, dest="pit_bottom", help="cao độ đáy hố khi bản vẽ không ghi")
    ap.add_argument("--dai-coc", type=float, dest="pile_len", help="chiều dài cọc khoan nhồi (m)")
    ap.add_argument("--d-coc", type=float, dest="pile_dia", help="đường kính cọc khi tim cọc là block (m)")
    ap.add_argument("--layer", action="append", default=[], metavar="LOAI=TEN",
                    help="chỉ định layer: pts, tk, bdy, brk, cnt (đồng mức), pit, pile, noslope; lặp lại được")
    ap.add_argument("--3d", action="store_true", dest="export_3d", help="xuất mô hình 3D: DWG solid cho AutoCAD, HTML, IFC (Navisworks, Revit), LandXML (Civil 3D)")
    ap.add_argument("--list-layers", action="store_true", help="in JSON các layer và layer tự nhận, không tính")
    ap.add_argument("--json", action="store_true", help="in JSON kết quả ra stdout, nhật ký chuyển sang stderr")
    ap.add_argument("--use-grid", action="store_true", help="dùng lại lưới TL-Luoi có sẵn để đối chiếu HML")
    ap.add_argument("--no-fix-ranh", action="store_true", help="không tự sửa chồng lấn, khe hở ranh giới")
    ap.add_argument("--project", help="tên dự án")
    ap.add_argument("--out", help="thư mục kết quả")
    ap.add_argument("--no-dwg", action="store_true", help="không xuất DWG")
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS)
    if a.config:
        cfg.update(json.loads(Path(a.config).read_text(encoding="utf-8")))
    for k in ("td", "step", "rot", "k", "project", "taluy_cut", "taluy_fill", "strip", "pit_slope", "pit_bottom", "pile_len", "pile_dia"):
        v = getattr(a, k)
        if v is not None:
            cfg[k] = v
    cfg["use_grid"] = cfg["use_grid"] or a.use_grid
    cfg["fix_bdy"] = cfg["fix_bdy"] and not a.no_fix_ranh
    cfg["export_3d"] = cfg["export_3d"] or a.export_3d
    for item in a.layer:
        key, _, name = item.partition("=")
        if f"layer_{key}" not in cfg or not name:
            raise SystemExit(f"--layer sai: {item}. Dạng đúng: pts=TEN_LAYER")
        cfg[f"layer_{key}"] = name
    if a.list_layers:
        print(json.dumps(layer_report(a.inputs), ensure_ascii=False, indent=2))
        return None
    if a.json:
        os.environ["SANNEN_STDERR"] = "1"
    r = run(a.inputs, cfg, a.out, a.no_dwg)
    if a.json:
        print(json.dumps(r["summary"], ensure_ascii=False, indent=2))
    return r


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        r = main()
    except SystemExit as e:
        if isinstance(e.code, str):       # lỗi đầu vào: thông báo ra stderr, mã 2
            print(e.code, file=sys.stderr)
            sys.exit(2)
        raise
    if r and r["summary"]["errors"]:
        sys.exit(3)                       # có kết quả nhưng sheet Kiểm tra báo LỖI
