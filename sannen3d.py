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


def body_mesh(tris):
    """Khối kín giữa mặt đất và mặt thiết kế: mặt trên, mặt dưới, vách biên."""
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
    return top + bot, faces


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
    return [h, i, l]
