# -*- coding: utf-8 -*-
"""Xuất 3D cho SanNenPro: HTML xem trên trình duyệt, IFC cho Navisworks/Revit, LandXML cho Civil 3D."""
import json
import math
import re
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- tách đào đắp
def split_triangles(xy, zg, zd):
    """Tách tam giác theo đường h = zd - zg = 0.
    Trả về (đắp, đào); mỗi phần là danh sách tam giác [(x, y, zg, zd)] * 3."""
    fill, cut = [], []
    for p, g, d in zip(xy, zg, zd):
        h = d - g
        v = [(p[i][0], p[i][1], g[i], d[i], h[i]) for i in range(3)]
        pos, neg = [], []
        for i in range(3):
            a, b = v[i], v[(i + 1) % 3]
            if a[4] >= 0:
                pos.append(a[:4])
            if a[4] <= 0:
                neg.append(a[:4])
            if a[4] * b[4] < 0:
                t = a[4] / (a[4] - b[4])
                q = tuple(a[k] + t * (b[k] - a[k]) for k in range(4))
                pos.append(q)
                neg.append(q)
        for part, out, sign in ((pos, fill, 1), (neg, cut, -1)):
            if len(part) >= 3 and any(sign * q[3] - sign * q[2] > 1e-9 for q in part):
                out += [[part[0], part[i], part[i + 1]] for i in range(1, len(part) - 1)]
    return fill, cut


def split_all(xy, zg, zd):
    """Chia mọi tam giác theo đường h = 0, giữ cả phần không dày. Trả về [(x, y, zg, zd)] * 3."""
    out = []
    for p, g, d in zip(xy, zg, zd):
        h = d - g
        v = [(p[i][0], p[i][1], g[i], d[i], h[i]) for i in range(3)]
        pos, neg = [], []
        for i in range(3):
            a, b = v[i], v[(i + 1) % 3]
            (pos if a[4] >= 0 else neg).append(a[:4])
            if a[4] * b[4] < 0:
                t = a[4] / (a[4] - b[4])
                q = tuple(a[k] + t * (b[k] - a[k]) for k in range(4))
                pos.append(q)
                neg.append(q)
        for part in (pos, neg):
            if len(part) >= 3:
                out += [[part[0], part[i], part[i + 1]] for i in range(1, len(part) - 1)]
    return out


def body_mesh(tris, pinch=False):
    """Khối kín giữa mặt đất và mặt thiết kế: mặt trên, mặt dưới, vách biên.
    pinch=True: đỉnh có bề dày 0 dùng chung cho mặt trên và dưới, để AutoCAD đổi được sang solid."""
    ids, top, bot, faces = {}, [], [], []
    def vid(q):
        k = (round(q[0], 3), round(q[1], 3))
        if k not in ids:
            ids[k] = len(top)
            top.append((q[0], q[1], max(q[2], q[3])))
            bot.append((q[0], q[1], min(q[2], q[3])))
        return ids[k]
    tri = []
    for t in tris:
        if pinch and all(abs(q[2] - q[3]) <= 1e-3 for q in t):
            continue   # tam giác dày dưới 1 mm: bỏ để khối kín
        (x1, y1), (x2, y2), (x3, y3) = (q[:2] for q in t)
        if (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1) < 0:   # đưa về ngược chiều kim đồng hồ
            t = [t[0], t[2], t[1]]
        i, j, k = (vid(q) for q in t)
        if len({i, j, k}) == 3:
            tri.append((i, j, k))
    n = len(top)
    edges = {}
    for i, j, k in tri:
        faces.append((i, j, k))
        faces.append((k + n, j + n, i + n))
        for a, b in ((i, j), (j, k), (k, i)):
            e = (min(a, b), max(a, b))
            edges[e] = (a, b) if e not in edges else None
    for v in edges.values():
        if v:
            a, b = v
            faces.append((b, a, a + n))
            faces.append((b, a + n, b + n))
    if not pinch:
        return top + bot, faces
    pts, m = list(top), list(range(n))
    for i in range(n):
        if top[i][2] - bot[i][2] > 1e-3:
            m.append(len(pts))
            pts.append(bot[i])
        else:
            m.append(i)
    out = []
    for f in faces:
        g = tuple(m[k] for k in f)
        if len(set(g)) == 3:
            out.append(g)
    return pts, out


def mesh_volume(pts, faces):
    P = np.asarray(pts, float)
    F = np.asarray(faces, int)
    if not len(F):
        return 0.0
    c = P.mean(axis=0)
    a, b, d = P[F[:, 0]] - c, P[F[:, 1]] - c, P[F[:, 2]] - c
    return float(np.einsum("ij,ij->i", a, np.cross(b, d)).sum() / 6)


def surface_mesh(xy, z):
    ids, pts, faces = {}, [], []
    for p, q in zip(xy, z):
        f = []
        for i in range(3):
            k = (round(float(p[i][0]), 3), round(float(p[i][1]), 3))
            if k not in ids:
                ids[k] = len(pts)
                pts.append((float(p[i][0]), float(p[i][1]), float(q[i])))
            f.append(ids[k])
        if len(set(f)) == 3:
            faces.append(tuple(f))
    return pts, faces


# ---------------------------------------------------------------- IFC4
def ifc_str(s):
    out = []
    for c in str(s):
        if c == "'":
            out.append("''")
        elif c == "\\":
            out.append("\\\\")
        elif ord(c) < 128:
            out.append(c)
        else:
            out.append("\\X2\\%04X\\X0\\" % ord(c))
    return "'" + "".join(out) + "'"


ALPHA = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def guid(seed):
    n = uuid.uuid5(uuid.NAMESPACE_URL, "sannenpro/" + seed).int
    s = []
    for _ in range(22):
        s.append(ALPHA[n & 63])
        n >>= 6
    s[-1] = ALPHA[int(ALPHA.index(s[-1])) & 3]
    return "'" + "".join(reversed(s)) + "'"


def num(v):
    return f"{float(v):.4f}"


class Ifc:
    def __init__(self):
        self.lines = []
        self.n = 0

    def add(self, text):
        self.n += 1
        self.lines.append(f"#{self.n}={text};")
        return f"#{self.n}"


def write_ifc(path, zones, tin_tris, T, X, cfg, origin):
    f = Ifc()
    ox, oy = origin
    a0 = f.add("IFCCARTESIANPOINT((0.,0.,0.))")
    world = f.add(f"IFCAXIS2PLACEMENT3D({a0},$,$)")
    m = f.add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    m2 = f.add("IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)")
    m3 = f.add("IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)")
    units = f.add(f"IFCUNITASSIGNMENT(({m},{m2},{m3}))")
    ctx = f.add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,{world},$)")
    sub = f.add(f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,{ctx},$,.MODEL_VIEW.,$)")
    name = cfg.get("project") or "San nen"
    proj = f.add(f"IFCPROJECT({guid('project' + name)},$,{ifc_str(name)},$,$,$,$,({ctx}),{units})")
    so = f.add(f"IFCCARTESIANPOINT(({num(ox)},{num(oy)},0.))")
    sp = f.add(f"IFCAXIS2PLACEMENT3D({so},$,$)")
    site_lp = f.add(f"IFCLOCALPLACEMENT($,{sp})")
    site = f.add(f"IFCSITE({guid('site' + name)},$,{ifc_str(name)},$,$,{site_lp},$,$,.ELEMENT.,$,$,$,$,$)")
    f.add(f"IFCRELAGGREGATES({guid('agg')},$,$,$,{proj},({site}))")
    zdir = f.add("IFCDIRECTION((0.,0.,1.))")
    xdir = f.add("IFCDIRECTION((1.,0.,0.))")
    styles = {}

    def style(rgb, tr=0.0):
        k = (rgb, tr)
        if k not in styles:
            c = f.add(f"IFCCOLOURRGB($,{rgb[0]},{rgb[1]},{rgb[2]})")
            r = f.add(f"IFCSURFACESTYLERENDERING({c},{tr},$,$,$,$,$,$,.NOTDEFINED.)")
            styles[k] = f.add(f"IFCSURFACESTYLE($,.BOTH.,({r}))")
        return styles[k]

    elements = []

    def element(kind, key, label, item, rtype, rgb, tr, props, placement=None, extra=""):
        f.add(f"IFCSTYLEDITEM({item},({style(rgb, tr)}),$)")
        sr = f.add(f"IFCSHAPEREPRESENTATION({sub},'Body',{rtype},({item}))")
        pds = f.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({sr}))")
        lp = placement or f.add(f"IFCLOCALPLACEMENT({site_lp},{world})")
        e = f.add(f"{kind}({guid(key)},$,{ifc_str(label)},$,$,{lp},{pds},${extra})")
        elements.append(e)
        if props:
            ps = []
            for n, v, typ in props:
                ps.append(f.add(f"IFCPROPERTYSINGLEVALUE({ifc_str(n)},$,{typ}({v}),$)"))
            s = f.add(f"IFCPROPERTYSET({guid(key + 'ps')},$,'SanNen',$,({','.join(ps)}))")
            f.add(f"IFCRELDEFINESBYPROPERTIES({guid(key + 'rel')},$,$,$,({e}),{s})")
        return e

    def mesh(pts, faces, closed=False):
        pl = ",".join(f"({num(x - ox)},{num(y - oy)},{num(z)})" for x, y, z in pts)
        p = f.add(f"IFCCARTESIANPOINTLIST3D(({pl}))")
        idx = ",".join(f"({a + 1},{b + 1},{c + 1})" for a, b, c in faces)
        return f.add(f"IFCTRIANGULATEDFACESET({p},$,{'.T.' if closed else '.F.'},({idx}),$)")

    gp, gf = surface_mesh(*tin_tris)
    element("IFCGEOGRAPHICELEMENT", "ground", "Mặt đất hiện trạng", mesh(gp, gf), "'Tessellation'",
            (0.62, 0.58, 0.5), 0.4, None, extra=",.TERRAIN.")
    for z in zones:
        ov = z["ov"]
        zg = ov.z - cfg["strip"]
        zd = z["design"](ov.xy.reshape(-1, 2)).reshape(-1, 3)
        p, q = surface_mesh(ov.xy, zd)
        element("IFCGEOGRAPHICELEMENT", "design" + z["name"], f"{z['name']} Mặt thiết kế", mesh(p, q), "'Tessellation'",
                (0.85, 0.85, 0.8), 0.5, None, extra=",.TERRAIN.")
        fill, cut = split_triangles(ov.xy, zg, zd)
        for tris, nm, v, s, rgb in ((fill, "Đắp", z["tvf"], z["tsf"], (0.12, 0.55, 0.25)), (cut, "Đào", z["tvc"], z["tsc"], (0.65, 0.15, 0.2))):
            if not tris:
                continue
            p, q = body_mesh(tris)
            element("IFCBUILDINGELEMENTPROXY", nm + z["name"], f"{z['name']} {nm}", mesh(p, q, True), "'Tessellation'", rgb, 0.0,
                    [("Khu vực", ifc_str(z["name"]), "IFCTEXT"), ("Loại", ifc_str(nm), "IFCTEXT"),
                     ("V (m3)", num(v), "IFCVOLUMEMEASURE"), ("S (m2)", num(s), "IFCAREAMEASURE"),
                     ("Cao độ thiết kế", ifc_str(z["design"].text()), "IFCTEXT")], extra=",.NOTDEFINED.")
    if T and T.get("mesh"):
        p, q = T["mesh"]["pts"], T["mesh"]["faces"]
        if q:
            element("IFCGEOGRAPHICELEMENT", "taluy", "Mái taluy", mesh(p, q), "'Tessellation'", (0.8, 0.6, 0.25), 0.2,
                    [("V đắp (m3)", num(T["vf"].sum()), "IFCVOLUMEMEASURE"), ("V đào (m3)", num(T["vc"].sum()), "IFCVOLUMEMEASURE")],
                    extra=",.TERRAIN.")
    if X:
        for p in X["pits"]:
            if p["zb"] is None:
                continue
            pm = pit_mesh(p, cfg)
            element("IFCBUILDINGELEMENTPROXY", "pit" + p["name"], p["name"], mesh(*pm, True), "'Tessellation'", (0.2, 0.45, 0.8), 0.3,
                    [("V (m3)", num(p["v"]), "IFCVOLUMEMEASURE"), ("Cao độ đáy", num(p["zb"]), "IFCLENGTHMEASURE")], extra=",.NOTDEFINED.")
        for i, c in enumerate(X.get("pile_items", [])):
            pr = f.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{num(c['d'] / 2)})")
            po = f.add(f"IFCCARTESIANPOINT((0.,0.,{num(-c['L'])}))")
            ap = f.add(f"IFCAXIS2PLACEMENT3D({po},$,$)")
            sol = f.add(f"IFCEXTRUDEDAREASOLID({pr},{ap},{zdir},{num(c['L'])})")
            ppt = f.add(f"IFCCARTESIANPOINT(({num(c['x'] - ox)},{num(c['y'] - oy)},{num(c['top'])}))")
            pax = f.add(f"IFCAXIS2PLACEMENT3D({ppt},$,$)")
            lp = f.add(f"IFCLOCALPLACEMENT({site_lp},{pax})")
            element("IFCPILE", f"pile{i}", f"Cọc {i + 1} D{c['d']}", sol, "'SweptSolid'", (0.55, 0.55, 0.55), 0.0, None, lp, ",.BORED.,$")
    el = ",".join(elements)
    f.add(f"IFCRELCONTAINEDINSPATIALSTRUCTURE({guid('contain')},$,$,$,({el}),{site})")
    head = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');\n"
            f"FILE_NAME({ifc_str(Path(path).name)},'',(''),(''),'SanNenPro','SanNenPro','');\n"
            "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n")
    Path(path).write_text(head + "\n".join(f.lines) + "\nENDSEC;\nEND-ISO-10303-21;\n", encoding="ascii")


def pit_mesh(p, cfg):
    """Khối hố: đáy phẳng, miệng mở rộng theo mái, trả về đỉnh và mặt tam giác."""
    g = p["poly"]
    b = list(g.exterior.coords[:-1])
    if g.exterior.is_ccw is False:
        b = b[::-1]
    top = p["top"] if p["top"] is not None else p["zb"] + 1
    w = max(top - p["zb"], 0) * float(cfg["pit_slope"] or 0)
    n = len(b)
    wide = []
    for i in range(n):   # dời từng đỉnh ra ngoài theo phân giác, giữ đúng thứ tự đỉnh
        (x0, y0), (x1, y1), (x2, y2) = b[i - 1], b[i], b[(i + 1) % n]
        def nrm(ax, ay, bx, by):
            L = math.hypot(bx - ax, by - ay) or 1.0
            return ((by - ay) / L, -(bx - ax) / L)
        n1, n2 = nrm(x0, y0, x1, y1), nrm(x1, y1, x2, y2)
        k = 1 + n1[0] * n2[0] + n1[1] * n2[1]
        k = k if k > 0.2 else 0.2
        wide.append((x1 + w * (n1[0] + n2[0]) / k, y1 + w * (n1[1] + n2[1]) / k))
    pts = [(x, y, p["zb"]) for x, y in b] + [(x, y, top) for x, y in wide]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces += [(i, j, j + n), (i, j + n, i + n)]
    for i in range(1, n - 1):
        faces.append((0, i + 1, i))
        faces.append((n, n + i, n + i + 1))
    return pts, faces


# ---------------------------------------------------------------- LandXML
def write_landxml(path, surfaces, cfg):
    """LandXML 1.2. Thứ tự toạ độ trong <P> là Northing Easting Elevation."""
    name = escape(cfg.get("project") or "San nen")
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2" date="2026-01-01" time="00:00:00">',
           '<Units><Metric areaUnit="squareMeter" linearUnit="meter" volumeUnit="cubicMeter" temperatureUnit="celsius" pressureUnit="HPA"/></Units>',
           f'<Project name="{name}"/>', '<Application name="SanNenPro" manufacturer="SanNenPro"/>', "<Surfaces>"]
    for nm, pts, faces in surfaces:
        out.append(f'<Surface name="{escape(nm)}"><Definition surfType="TIN"><Pnts>')
        out += [f'<P id="{i + 1}">{y:.3f} {x:.3f} {z:.3f}</P>' for i, (x, y, z) in enumerate(pts)]
        out.append("</Pnts><Faces>")
        out += [f"<F>{a + 1} {b + 1} {c + 1}</F>" for a, b, c in faces]
        out.append("</Faces></Definition></Surface>")
    out += ["</Surfaces>", "</LandXML>"]
    Path(path).write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------- HTML
def write_html(path, zones, tin_tris, T, X, cfg, bal, origin):
    ox, oy = origin
    r3 = lambda a: [round(float(v), 3) for v in np.ravel(a)]
    gp, gf = surface_mesh(*tin_tris)
    xy, zg, zd, own, cells = [], [], [], [], []
    bd, grid = [], []
    for z in zones:
        ov = z["ov"]
        base = len(cells)
        for c in z["cells"]:
            cells.append(dict(n=c["name"], k=z["name"], a=round(c["area"], 2), sf=round(c["tsf"], 2), sc=round(c["tsc"], 2),
                              vf=round(c["tvf"], 2), vc=round(c["tvc"], 2), gf=round(c["vf"], 2), gc=round(c["vc"], 2)))
            grid.append(r3(np.asarray(c["xy"]) - (ox, oy)))
        xy.append((ov.xy - (ox, oy)).reshape(-1))
        zg.append((ov.z - cfg["strip"]).reshape(-1))
        zd.append(z["design"](ov.xy.reshape(-1, 2)))
        own.append(ov.own + base)
        bd.append(r3(np.array(z["poly"].exterior.coords)[:, :2] - (ox, oy)))
    data = dict(
        name=cfg.get("project") or "Khu san nền", strip=cfg["strip"], K=cfg["k"],
        ground=dict(v=r3(np.array(gp) - (ox, oy, 0)), t=np.ravel(gf).astype(int).tolist()),
        site=dict(xy=r3(np.concatenate(xy)), zg=r3(np.concatenate(zg)), zd=r3(np.concatenate(zd)), own=np.concatenate(own).astype(int).tolist()),
        cells=cells, grid=grid, bd=bd, bal=[round(bal[0], 3), round(bal[2], 3)],
        design=[z["design"].text() for z in zones], flat=all(z["design"].kind == "flat" for z in zones),
        extra=dict(tf=float(T["vf"].sum()) if T else 0, tc=float(T["vc"].sum()) if T else 0,
                   pit=sum(p["v"] for p in X["pits"]) if X else 0, pile=sum(p["v"] for p in X["piles"]) if X else 0),
        taluy=None, pits=[], piles=[])
    if T and T.get("mesh") and T["mesh"]["faces"]:
        data["taluy"] = dict(v=r3(np.array(T["mesh"]["pts"]) - (ox, oy, 0)), t=np.ravel(T["mesh"]["faces"]).astype(int).tolist())
    if X:
        for p in X["pits"]:
            if p["zb"] is not None:
                pts, faces = pit_mesh(p, cfg)
                data["pits"].append(dict(name=p["name"], v=r3(np.array(pts) - (ox, oy, 0)), t=np.ravel(faces).astype(int).tolist(), vol=round(p["v"], 2), zb=p["zb"]))
        data["piles"] = [[round(c["x"] - ox, 3), round(c["y"] - oy, 3), round(c["top"], 3), c["d"], c["L"]] for c in X.get("pile_items", [])]
    tpl = Path(viewer_template()).read_text(encoding="utf-8")
    html = tpl.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    html = html.replace("{{TITLE}}", escape(data["name"]))
    Path(path).write_text(html, encoding="utf-8")


def viewer_template():
    import sys
    base = Path(getattr(sys, "_MEIPASS", HERE))
    return base / "sannen3d_view.html"


# ---------------------------------------------------------------- DWG 3D cho AutoCAD
LAYERS_3D = {   # layer: (màu RGB, mô tả)
    "SN3D_NEN": ((175, 175, 175), "Nền đất sau san"),
    "SN3D_DAO": ((235, 135, 35), "Khối đào"),
    "SN3D_DAP": ((205, 35, 35), "Khối đắp"),
    "SN3D_BOC": ((140, 100, 60), "Lớp bóc phong hoá"),
    "SN3D_TALUY": ((200, 180, 120), "Mái taluy"),
    "SN3D_HO_MONG": ((60, 125, 215), "Hố móng"),
    "SN3D_COC": ((110, 110, 110), "Cọc"),
    "SN3D_DAT_XQ": ((120, 130, 115), "Mặt đất xung quanh"),
    "SN3D_CHU": ((255, 255, 255), "Ghi chú"),
}
SOLID_LAYERS = ("SN3D_NEN", "SN3D_DAO", "SN3D_DAP", "SN3D_BOC", "SN3D_HO_MONG")
CHECK_LAYERS = ("SN3D_DAO", "SN3D_DAP", "SN3D_BOC", "SN3D_HO_MONG", "SN3D_COC")


def model_3d(zones, tin_tris, T, X, cfg, origin):
    """Các khối 3D theo toạ độ cục bộ (trừ gốc). Trả về dict: bodies, surfaces, piles, labels, khung."""
    ox, oy = origin
    bodies, surfaces = [], []      # (layer, tên, pts, faces, V bảng tính hoặc None)
    sub = lambda pts: [(x - ox, y - oy, z) for x, y, z in pts]
    zs = []
    for z in zones:
        ov = z["ov"]
        zd = z["design"](ov.xy.reshape(-1, 2)).reshape(-1, 3)
        zs += [ov.z.min() - cfg["strip"], zd.min()]
    zbase = math.floor(min(zs) - 2.0)
    for z in zones:
        ov = z["ov"]
        zg = ov.z - cfg["strip"]
        zd = z["design"](ov.xy.reshape(-1, 2)).reshape(-1, 3)
        allp = split_all(ov.xy, zg, zd)
        p, q = body_mesh([[(a[0], a[1], min(a[2], a[3]), zbase) for a in t] for t in allp], pinch=True)
        bodies.append(("SN3D_NEN", z["name"] + " nền", sub(p), q, None))
        fill, cut = split_triangles(ov.xy, zg, zd)
        for tris, lay, nm, v in ((fill, "SN3D_DAP", "đắp", z["tvf"]), (cut, "SN3D_DAO", "đào", z["tvc"])):
            if tris:
                p, q = body_mesh(tris, pinch=True)
                bodies.append((lay, f"{z['name']} {nm}", sub(p), q, v))
        if cfg["strip"] > 0:
            tris = [[(a[0], a[1], a[2] + cfg["strip"], a[2]) for a in t]
                    for t in ([[(x, y, g, g) for (x, y), g in zip(pp, gg)] for pp, gg in zip(ov.xy, zg)])]
            p, q = body_mesh(tris, pinch=True)
            bodies.append(("SN3D_BOC", z["name"] + " bóc", sub(p), q, None))
    if T and T.get("mesh") and T["mesh"]["faces"]:
        surfaces.append(("SN3D_TALUY", "Mái taluy", sub(T["mesh"]["pts"]), [tuple(f) for f in T["mesh"]["faces"]]))
    # mặt đất ngoài ranh
    from shapely.geometry import Point
    from shapely.ops import unary_union
    U = unary_union([z["poly"] for z in zones])
    V, Z = tin_tris
    keep = [i for i, t in enumerate(V) if not U.contains(Point(float(np.mean(t[:, 0])), float(np.mean(t[:, 1]))))]
    if keep:
        p, q = surface_mesh(V[keep], Z[keep])
        surfaces.append(("SN3D_DAT_XQ", "Mặt đất xung quanh", sub(p), q))
    piles = []
    if X:
        for p in X["pits"]:
            if p["zb"] is not None:
                pts, faces = pit_mesh(p, cfg)
                bodies.append(("SN3D_HO_MONG", p["name"], sub(pts), faces, p["v"]))
        piles = [(c["x"] - ox, c["y"] - oy, c["top"], c["d"], c["L"]) for c in X.get("pile_items", [])]
    return dict(bodies=bodies, surfaces=surfaces, piles=piles, zbase=zbase)


def write_dxf3d(path, M, zones, T, X, cfg, origin, shift=(0.0, 0.0)):
    """Ghi DXF 3D. Toạ độ = cục bộ + shift (shift = gốc khi không có AutoCAD để đổi solid)."""
    import ezdxf
    from ezdxf.math import OCS
    doc = ezdxf.new("R2018", setup=True)
    doc.units = 6
    doc.header["$INSUNITS"] = 6
    st = doc.styles.new("SN3D_ARIAL")
    st.dxf.font = "arial.ttf"
    for nm, (rgb, desc) in LAYERS_3D.items():
        for suf in ("", "_TACH"):
            if nm == "SN3D_CHU" and suf:
                continue
            ly = doc.layers.add(nm + suf)
            ly.rgb = rgb
            ly.description = desc + (" (hình tách)" if suf else "")
    msp = doc.modelspace()
    sx, sy = shift

    def add_mesh(layer, pts, faces, dx=0.0, dz=0.0):
        m = msp.add_mesh(dxfattribs={"layer": layer})
        with m.edit_data() as d:
            d.vertices = [(x + sx + dx, y + sy, z + dz) for x, y, z in pts]
            d.faces = [list(f) for f in faces]

    for lay, nm, p, q, v in M["bodies"]:
        add_mesh(lay, p, q)
    for lay, nm, p, q in M["surfaces"]:
        add_mesh(lay, p, q)
    # cọc dạng lăng trụ 24 cạnh (khi có AutoCAD sẽ thay bằng trụ tròn)
    for x, y, top, d, L in M["piles"]:
        n = 24
        ring = [(x + d / 2 * math.cos(2 * math.pi * i / n), y + d / 2 * math.sin(2 * math.pi * i / n)) for i in range(n)]
        pts = [(a, b, top - L) for a, b in ring] + [(a, b, top) for a, b in ring]
        faces = [(i, (i + 1) % n, (i + 1) % n + n) for i in range(n)] + [(i, (i + 1) % n + n, i + n) for i in range(n)]
        faces += [(0, i + 1, i) for i in range(1, n - 1)] + [(n, n + i, n + i + 1) for i in range(1, n - 1)]
        add_mesh("SN3D_COC", pts, faces)

    # hình tách khối, đặt bên phải
    allp = np.array([pt for b in M["bodies"] for pt in b[2]])
    x0, y0 = allp[:, 0].min(), allp[:, 1].min()
    x1, y1 = allp[:, 0].max(), allp[:, 1].max()
    zb, zt = M["zbase"], allp[:, 2].max()
    W = max(x1 - x0, y1 - y0)
    dx = (x1 - x0) + 0.35 * W + 0.1 * W
    lift = max(4.0, 0.5 * (zt - zb))
    zmin = {k: min(pt[2] for b in M["bodies"] if b[0] == k for pt in b[2]) for k in ("SN3D_NEN", "SN3D_DAP", "SN3D_DAO", "SN3D_BOC")
            if any(b[0] == k for b in M["bodies"])}
    lifts = {"SN3D_NEN": 0.0, "SN3D_DAP": lift, "SN3D_DAO": 2 * lift, "SN3D_BOC": 3 * lift}
    for lay, nm, p, q, v in M["bodies"]:
        if lay in lifts:
            add_mesh(lay + "_TACH", p, q, dx=dx, dz=lifts[lay])

    # chữ: mặt phẳng đứng nhìn từ hướng Đông Nam (góc nhìn SE ISO)
    ocs = OCS((1, -1, 0))
    h = max(0.8, round(W * 0.025, 1))

    def label(text, x, y, z, color=None):
        t = msp.add_text(text, height=h, dxfattribs={"layer": "SN3D_CHU", "style": "SN3D_ARIAL"})
        t.dxf.extrusion = (1, -1, 0)
        t.set_placement(ocs.from_wcs((x + sx, y + sy, z)), align=ezdxf.enums.TextEntityAlignment.BOTTOM_RIGHT)
        if color:
            t.rgb = color

    S = lambda k: sum(z[k] for z in zones)
    vals = {"SN3D_NEN": None, "SN3D_DAP": S("tvf"), "SN3D_DAO": S("tvc"), "SN3D_BOC": X.get("strip_v", 0) if X else 0}
    names = {"SN3D_NEN": "NỀN SAU SAN", "SN3D_DAP": "KHỐI ĐẮP", "SN3D_DAO": "KHỐI ĐÀO", "SN3D_BOC": "BÓC PHONG HOÁ"}
    for k in zmin:
        txt = names[k] + ("" if vals[k] is None else f"  {vals[k]:,.2f} m³")
        zz = zmin[k] + lifts[k] + (0.0 if k != "SN3D_NEN" else 0.5)
        label(txt, x0 + dx - 0.04 * W, y0 - 0.04 * W, zz, LAYERS_3D[k][0])
    label("HIỆN TRẠNG + THIẾT KẾ", x0 - 0.04 * W, y0 - 0.04 * W, zt + 1.0)
    label("TÁCH KHỐI", x0 + dx - 0.04 * W, y0 - 0.04 * W, zt + 4 * lift + 1.0)
    doc.set_modelspace_vport(height=1.2 * (x1 - x0 + dx), center=((x0 + x1 + dx) / 2 + sx, (y0 + y1) / 2 + sy))
    doc.saveas(path)


def acad_script(dxf, dwg, mpr, M, origin):
    """Script accoreconsole: đổi mesh sang solid, vẽ cọc trụ tròn, đo MASSPROP, dời về toạ độ thật, lưu DWG."""
    ox, oy = origin
    lays = ",".join(SOLID_LAYERS) + "," + ",".join(l + "_TACH" for l in SOLID_LAYERS)
    L = ["FILEDIA 0", "CMDDIA 0", "CMDECHO 0", "OSMODE 0", "(setvar \"SMOOTHMESHCONVERT\" 2)", "(setvar \"DELOBJ\" 1)",
         f'(if (setq ss (ssget "_X" \'((0 . "MESH") (8 . "{lays}")))) (command "_.CONVTOSOLID" ss ""))']
    if M["piles"]:
        L.append('(if (setq ss (ssget "_X" \'((0 . "MESH") (8 . "SN3D_COC")))) (command "_.ERASE" ss ""))')
        L.append('(setvar "CLAYER" "SN3D_COC")')
        for x, y, top, d, Lc in M["piles"]:
            L.append(f'(command "_.CYLINDER" \'({x:.4f} {y:.4f} {top - Lc:.4f}) {d / 2:.4f} {Lc:.4f})')
        L.append('(setvar "CLAYER" "0")')
    m = mpr.as_posix()
    L.append(f'(setq ss (ssget "_X" \'((0 . "3DSOLID") (8 . "{",".join(CHECK_LAYERS)}"))) i 0)')
    L.append(f'(if ss (repeat (sslength ss) (setq e (ssname ss i) i (1+ i)) '
             f'(command "_.MASSPROP" e "" "_Y" (strcat "{m}/" (cdr (assoc 8 (entget e))) "_" (cdr (assoc 5 (entget e))) ".mpr"))))')
    L.append(f'(if (setq ss (ssget "_X" \'((0 . "MESH") (8 . "{lays}")))) (progn (setq f (open "{m}/mesh_left.txt" "w")) (write-line (itoa (sslength ss)) f) (close f)))')
    L.append(f'(command "_.MOVE" (ssget "_X") "" \'(0 0 0) \'({ox:.3f} {oy:.3f} 0))')
    L.append('(command "_.-VIEW" "_SE")')
    L.append('(command "_.ZOOM" "_E")')
    L.append(f'_.SAVEAS 2018 "{dwg.as_posix()}"')
    L.append("_.QUIT _Y")
    return "\n".join(L) + "\n"


def read_mpr(folder):
    """Đọc thể tích từ file MASSPROP: {layer: [V, ...]}."""
    out = {}
    for f in Path(folder).glob("*.mpr"):
        t = f.read_text(encoding="utf-8", errors="ignore")
        mm = re.search(r"Volume:\s*([-\d.,]+)", t)
        if mm:
            lay = f.stem.rsplit("_", 1)[0]
            out.setdefault(lay, []).append(float(mm.group(1).replace(",", "")))
    return out


def write_dwg3d(out, zones, tin_tris, T, X, cfg, origin):
    """Tạo SanNen_3D.dwg (solid thật, cần AutoCAD) hoặc SanNen_3D.dxf (mesh). Trả về (file, kiểm tra)."""
    import os
    import shutil
    import subprocess
    import tempfile
    M = model_3d(zones, tin_tris, T, X, cfg, origin)
    chk = dict(bodies=[], solid=None)
    S = lambda k: sum(z[k] for z in zones)
    # thể tích khối mesh so với bảng tính
    for lay in ("SN3D_DAP", "SN3D_DAO", "SN3D_HO_MONG"):
        vm = sum(mesh_volume(b[2], b[3]) for b in M["bodies"] if b[0] == lay)
        vt = sum(b[4] for b in M["bodies"] if b[0] == lay)
        if vt or vm:
            chk["bodies"].append(dict(layer=lay, mesh=round(vm, 2), table=round(vt, 2)))
    acc = None
    try:
        import sannen
        acc = sannen.find_accore()
    except Exception:
        acc = None
    out = Path(out)
    if not acc:
        p = out / "SanNen_3D.dxf"
        write_dxf3d(p, M, zones, T, X, cfg, origin, shift=origin)
        return p, chk
    tmp = Path(tempfile.mkdtemp())
    src, dst, mpr = tmp / "in.dxf", tmp / "out.dwg", tmp / "mpr"
    mpr.mkdir()
    write_dxf3d(src, M, zones, T, X, cfg, origin)
    scr = tmp / "s.scr"
    scr.write_text(acad_script(src, dst, mpr, M, origin), encoding="utf-8")
    try:
        subprocess.run([acc, "/i", str(src), "/s", str(scr), "/l", "en-US"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=1800, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        pass
    if not dst.exists():
        p = out / "SanNen_3D.dxf"
        write_dxf3d(p, M, zones, T, X, cfg, origin, shift=origin)
        shutil.rmtree(tmp, ignore_errors=True)
        return p, chk
    vol = read_mpr(mpr)
    left = mpr / "mesh_left.txt"
    tab = {"SN3D_DAP": S("tvf"), "SN3D_DAO": S("tvc"), "SN3D_BOC": X.get("strip_v", 0) if X else 0,
           "SN3D_HO_MONG": sum(p["v"] for p in X["pits"]) if X else 0, "SN3D_COC": sum(p["v"] for p in X["piles"]) if X else 0}
    chk["solid"] = dict(mesh_left=int(left.read_text().strip()) if left.exists() else 0,
                        layers={k: dict(solid=round(sum(v), 2), n=len(v), table=round(tab.get(k, 0), 2)) for k, v in vol.items()})
    p = out / "SanNen_3D.dwg"
    shutil.copy2(dst, p)
    shutil.rmtree(tmp, ignore_errors=True)
    return p, chk


# ---------------------------------------------------------------- xuất tất cả
def export(out, zones, tin, T, X, cfg, bal, ear_clip=None):
    """Tạo SanNen_3D.html, SanNen_3D.ifc, SanNen_TIN.xml, trả về danh sách file."""
    out = Path(out)
    V, Z = tin.triangles()
    Z = Z - cfg["strip"]
    tin_tris = (V, Z)
    allxy = np.concatenate([z["ov"].xy.reshape(-1, 2) for z in zones])
    origin = (float(np.round(allxy[:, 0].mean())), float(np.round(allxy[:, 1].mean())))
    X = dict(X) if X else dict(pits=[], piles=[])
    items = []
    for c in X.get("pile_points", []):
        items.append(c)
    X["pile_items"] = items
    h = out / "SanNen_3D.html"
    i = out / "SanNen_3D.ifc"
    l = out / "SanNen_TIN.xml"
    write_html(h, zones, tin_tris, T, X, cfg, bal, origin)
    write_ifc(i, zones, tin_tris, T, X, cfg, origin)
    surf = [("Hien trang",) + surface_mesh(*tin_tris)]
    dx, dz = [], []
    for z in zones:
        dx.append(z["ov"].xy)
        dz.append(z["design"](z["ov"].xy.reshape(-1, 2)).reshape(-1, 3))
    surf.append(("Thiet ke",) + surface_mesh(np.concatenate(dx), np.concatenate(dz)))
    write_landxml(l, surf, cfg)
    d, chk = write_dwg3d(out, zones, tin_tris, T, X, cfg, origin)
    (out / "SanNen_3D_KiemTra.json").write_text(json.dumps(chk, ensure_ascii=False, indent=1), encoding="utf-8")
    return [d, h, i, l]
