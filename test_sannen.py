"""Kiểm thử SanNenPro bằng các bài toán có đáp số tính tay."""
import math, os, sys, tempfile
import numpy as np, ezdxf
from pathlib import Path
from shapely.geometry import Polygon, box
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sannen as sn
sn.LOG_SINK = lambda m: None
R = []
def check(name, got, want, tol):
    ok = abs(got - want) <= tol
    R.append(ok)
    print(f"{'OK ' if ok else 'SAI'} {name}: {got:.3f} / đáp số {want:.3f} (dung sai {tol})", flush=True)
def grid_pts(x0, x1, y0, y1, st, f):
    X, Y = np.meshgrid(np.arange(x0, x1 + 1e-6, st), np.arange(y0, y1 + 1e-6, st))
    return np.c_[X.ravel(), Y.ravel(), f(X.ravel(), Y.ravel())]
def zone(poly, td, cfg):
    return dict(name="KV-01", poly=poly, cells=sn.make_grid(poly, cfg["step"], 0, cfg["min_cell"]), rot=0,
                src=sn.Source(Path("x")), n_labels=0, design=sn.Design("flat", z=td))
cfg = dict(sn.DEFAULTS, round_dp=None)

# 1. mặt nghiêng z=0.01x, ranh 100x50, TK 0.5
tin = sn.TIN(grid_pts(-10, 110, -10, 60, 7, lambda x, y: 0.01 * x))
z = zone(box(0, 0, 100, 50), 0.5, cfg)
sn.compute([z], tin, cfg)
check("Mặt nghiêng TIN V đắp", z["tvf"], 50 * 0.5 * 50 / 2, 1e-6)
check("Mặt nghiêng TIN V đào", z["tvc"], 50 * 0.5 * 50 / 2, 1e-6)
check("Mặt nghiêng ô lưới V đắp", z["vf"], 625, 1e-6)
check("Tổng diện tích", z["tsf"] + z["tsc"], 5000, 1e-6)

# 2. ranh lõm chữ L, lưới xoay 30 độ, ô gộp
L = Polygon([(0, 0), (60, 0), (60, 20), (20, 20), (20, 50), (0, 50)])
tin = sn.TIN(grid_pts(-20, 80, -20, 70, 9, lambda x, y: 0 * x + 1.0))
cells = sn.make_grid(L, 5, 30, 0.25)
check("Ranh chữ L: tổng diện tích ô", sum(c["poly"].area for c in cells), L.area, 1e-6)
z = dict(zone(L, 2.0, cfg), cells=cells, rot=30)
sn.compute([z], tin, cfg)
check("Ranh chữ L: V đắp", z["vf"], L.area * 1.0, 1e-6)
check("Ranh chữ L: V TIN", z["tvf"], L.area * 1.0, 1e-6)

# 3. breakline: mương chữ V dọc y=25, sâu 1 m, miệng rộng 4 m; điểm đo thưa
far = grid_pts(0, 100, 0, 50, 12.5, lambda x, y: 0 * x)
far = far[np.abs(far[:, 1] - 25) >= 2]
top = np.array([[x, y, 0.0] for x in np.arange(0, 101, 12.5) for y in (23, 27)])
pts = np.vstack([far, top, [[0, 25, -1], [100, 25, -1]]])
pts = pts[np.unique(pts.round(3), axis=0, return_index=True)[1]]
tin0 = sn.TIN(pts)
tinb = sn.TIN(pts, [[(0, 25, -1.0), (100, 25, -1.0)]])
for t, nm, tol in ((tinb, "Có breakline", 1e-3), (tin0, "Không breakline, để so sánh", 1e9)):
    z = zone(box(0, 0, 100, 50), 0.0, cfg)
    sn.compute([z], t, cfg)
    check(f"Mương V ({nm}) V đắp", z["tvf"], 200.0, tol)
check("Breakline: đoạn chưa ép", tinb.brk_missing, 0, 0)

# 4. taluy: đất z=0, ranh 20x10, TK +1, mái 1:1.5; đáp số = lăng trụ + 1 nón
cfg2 = dict(cfg, taluy_fill=1.5, taluy_cut=1.0, taluy_res=0.1, taluy_max=5.0)
tin = sn.TIN(grid_pts(-40, 60, -40, 50, 10, lambda x, y: 0 * x))
z = zone(box(0, 0, 20, 10), 1.0, cfg2)
sn.compute([z], tin, cfg2)
T = sn.calc_taluy([z], tin, cfg2)
check("Taluy đắp 1:1.5", float(T["vf"].sum()), 60 * 1 * 1.5 / 2 + math.pi * 1.5 ** 2 / 3, 0.5)
check("Taluy đắp: không có đào", float(T["vc"].sum()), 0, 0)
tin = sn.TIN(grid_pts(-40, 60, -40, 50, 10, lambda x, y: 0 * x + 1))
z = zone(box(0, 0, 20, 10), 0.0, cfg2)
sn.compute([z], tin, cfg2)
T = sn.calc_taluy([z], tin, cfg2)
check("Taluy đào 1:1", float(T["vc"].sum()), 60 * 1 * 1 / 2 + math.pi / 3, 0.4)

# 5. sửa ranh: 2 khu chồng 1 m, 1 cặp khu hở 0.5 m
a, b, c = box(0, 0, 50, 20), box(49, 0, 100, 20), box(100.5, 0, 150, 20)
new, cut, filled = sn.fix_boundaries([a, b, c])
check("Cắt chồng lấn (m2)", cut, 20, 1e-6)
check("Lấp khe hở (m2)", filled, 10, 0.02)
check("Tổng sau sửa", sum(p.area for p in new), 3000, 0.02)
check("Không còn chồng lấn", sum(new[i].intersection(new[j]).area for i in range(3) for j in range(i + 1, 3)), 0, 1e-3)
L2 = [Polygon([(0, 0), (60, 0), (60, 20), (20, 20), (20, 50), (0, 50)]), box(60, 0, 80, 20)]
check("Ranh lõm ngoài biên: không báo khe hở", len(sn.find_gaps(L2)), 0, 0)

# 6. dị thường: sườn dốc không báo, điểm nhô 3 m thì báo
rng = np.random.default_rng(1)
p = grid_pts(0, 100, 0, 100, 5, lambda x, y: 0.2 * x + rng.normal(0, .05, x.size))
check("Sườn dốc: số cảnh báo", len(sn.check_points(p)["outlier"]), 0, 0)
p[220, 2] += 3
check("Điểm nhô 3 m: số cảnh báo", len(sn.check_points(p)["outlier"]), 1, 0)

# 7. tự nhận layer: file DXF tên layer lạ, đọc qua load_raw + run
d = Path(tempfile.mkdtemp())
doc = ezdxf.new("R2013"); m = doc.modelspace()
for l in ("CAO ĐỘ HIỆN TRẠNG", "Ranh khu đất", "Text khac"):
    doc.layers.add(l)
for x, y, zz in grid_pts(-10, 60, -10, 40, 6, lambda x, y: 0.02 * x + 1.5):
    m.add_text(f"{zz:.3f}", dxfattribs={"layer": "CAO ĐỘ HIỆN TRẠNG", "insert": (x, y)})
for i in range(30):
    m.add_text(str(i), dxfattribs={"layer": "Text khac", "insert": (i, 0)})
m.add_lwpolyline([(0, 0), (50, 0), (50, 30), (0, 30)], close=True, dxfattribs={"layer": "Ranh khu đất"})
f = d / "khac layer.dxf"; doc.saveas(f)
r = sn.run([f], dict(sn.DEFAULTS, td=3.0, k=1.0), d / "out", no_dwg=True)
check("Tự nhận layer: V đắp từ DXF", r["zones"][0]["tvf"], 1500 * (3 - (0.02 * 25 + 1.5)), 1e-3)

# 8. bóc phong hoá: đất 0, TK +1, bóc 0.3 trên ranh 100x50
cfg3 = dict(cfg, strip=0.3)
tin = sn.TIN(grid_pts(-20, 120, -20, 70, 10, lambda x, y: 0 * x))
z = zone(box(0, 0, 100, 50), 1.0, cfg3)
sn.compute([z], tin, cfg3)
check("Bóc 0,3 m: V đắp ô", z["vf"], 5000 * 1.3, 1e-6)
check("Bóc 0,3 m: V đắp TIN", z["tvf"], 5000 * 1.3, 1e-6)

# 9. hố móng 10x10, đáy -2, mặt san 0
cfg4 = dict(cfg, pit_slope=0.0)
tin = sn.TIN(grid_pts(-40, 90, -40, 90, 10, lambda x, y: 0 * x))
z = zone(box(0, 0, 50, 50), 0.0, cfg4)
sn.compute([z], tin, cfg4)
pg = box(20, 20, 30, 30)
check("Hố thành đứng", sn.calc_pits([z], tin, cfg4, [(pg, -2.0)])[0]["v"], 200, 1.0)
cfg4["pit_slope"] = 1.0
check("Hố mái 1:1", sn.calc_pits([z], tin, cfg4, [(pg, -2.0)])[0]["v"], 200 + 40 * 2 + math.pi * 4 * 2 / 3, 2.0)
cfg4["pit_slope"] = 0.5
check("Hố mái 1:0,5", sn.calc_pits([z], tin, cfg4, [(pg, -2.0)])[0]["v"], 200 + 40 * 2 * 1 / 2 + math.pi * 1 * 2 / 3, 1.0)
check("Hố thiếu cao độ đáy: không tính", sn.calc_pits([z], tin, cfg4, [(pg, None)])[0]["v"], 0, 0)

# 10. cọc: 10 cọc D0.8 dài 20
p = sn.calc_piles(dict(cfg, pile_len=20.0), [(i, 0, 0.4) for i in range(10)])
check("Cọc D800 L20 x 10", p[0]["v"], 10 * math.pi / 4 * .64 * 20, 1e-6)

# 11. taluy bỏ 1 cạnh dài 20 m: mất lăng trụ 20 x 0,75 và phần nón hai góc
cfg5 = dict(cfg, taluy_fill=1.5, taluy_cut=1.0, taluy_res=0.1, taluy_max=5.0)
tin = sn.TIN(grid_pts(-40, 60, -40, 50, 10, lambda x, y: 0 * x))
z = zone(box(0, 0, 20, 10), 1.0, cfg5)
sn.compute([z], tin, cfg5)
T0 = sn.calc_taluy([z], tin, cfg5)
T1 = sn.calc_taluy([z], tin, cfg5, [[(0, 0, 0), (20, 0, 0)]])
check("Taluy bỏ 1 cạnh", float(T0["vf"].sum() - T1["vf"].sum()), 20 * .75 + math.pi * 2.25 / 6 + 2 * .5 * .75, 0.3)

# 12. taluy khác nhau từng khu
cfg6 = dict(cfg5, zones={"KV-01": {"taluy_fill": 3.0}})
T2 = sn.calc_taluy([z], tin, cfg6)
check("Taluy riêng từng khu 1:3", float(T2["vf"].sum()), 60 * 1 * 3 / 2 + math.pi * 9 / 3, 1.0)

# 13. cân bằng gồm taluy và hố: tổng đào = K x tổng đắp tại cao độ tìm được
tin = sn.TIN(grid_pts(-40, 140, -40, 90, 10, lambda x, y: 0.02 * x))
cfg7 = dict(cfg, taluy_fill=1.5, taluy_cut=1.0, taluy_res=0.5, taluy_max=10.0)
z = zone(box(0, 0, 100, 50), 1.0, cfg7)
ov = sn.compute([z], tin, cfg7)
mer = sn.Merged(ov)
c = sn.taluy_ctx([z], tin, cfg7, res=0.5)
td = sn.balance_full(mer, 1.15, c, 300.0)
Vf, Vc, _, _ = mer.volumes(td - mer.z)
G = sn.taluy_eval(c, np.full(len(c["d"]), td))[0]
a = float(Vc.sum()) + 300 + float(-G[G < 0].sum() * .25)
b = float(Vf.sum()) + float(G[G > 0].sum() * .25)
check("Cân bằng đầy đủ: đào - K x đắp", a - 1.15 * b, 0, 1.0)

# 14. mặt thiết kế không phẳng: đáp số tính độc lập bằng cắt đa giác (h tuyến tính trên từng mảnh)
from scipy.spatial import Delaunay as _Del
def exact(poly, gpts, dpts, strip=0.0):
    """Tích phân đắp, đào chính xác: chồng tam giác đất x tam giác thiết kế x ranh, cắt theo h = 0."""
    from shapely.geometry import Polygon as P_, box as B_
    def tris(p):
        t = _Del(p[:, :2]).simplices
        return [(Polygon(p[s, :2]), p[s]) for s in t]
    def plane(v):
        return np.linalg.solve(np.c_[v[:, :2], np.ones(3)], v[:, 2])
    G, D = tris(gpts), tris(dpts)
    f = c = 0.0
    for gp, gv in G:
        a = gp.intersection(poly)
        if a.area < 1e-12:
            continue
        cg = plane(gv)
        for dp, dv in D:
            b = dp.intersection(a)
            if b.area < 1e-12:
                continue
            cd = plane(dv)
            k = cd - cg; k[2] += strip          # h = kx x + ky y + k0
            for part in getattr(b, "geoms", [b]):
                if part.geom_type != "Polygon":
                    continue
                x0, y0, x1, y1 = part.bounds
                from shapely.geometry import LineString
                from shapely.ops import split
                if abs(k[0]) + abs(k[1]) > 1e-12:
                    if abs(k[1]) > abs(k[0]):
                        ln = LineString([(x0 - 1, -(k[0] * (x0 - 1) + k[2]) / k[1]), (x1 + 1, -(k[0] * (x1 + 1) + k[2]) / k[1])])
                    else:
                        ln = LineString([(-(k[1] * (y0 - 1) + k[2]) / k[0], y0 - 1), (-(k[1] * (y1 + 1) + k[2]) / k[0], y1 + 1)])
                    pieces = split(part, ln).geoms
                else:
                    pieces = [part]
                for q in pieces:
                    cc = q.centroid
                    hv = k[0] * cc.x + k[1] * cc.y + k[2]
                    if hv > 0:
                        f += q.area * hv
                    else:
                        c -= q.area * hv
    return f, c
def tzone(poly, design, cfg):
    return dict(zone(poly, 0, cfg), design=design)
# 14a. mặt thiết kế nghiêng hai phương trên đất nghiêng
gp = grid_pts(-20, 120, -20, 70, 8, lambda x, y: 0.02 * y + 0.3)
pl = sn.Design("plane", z0=0.5, x0=0, y0=0, ix=0.01, iy=-0.004)
z = tzone(box(0, 0, 100, 50), pl, cfg)
sn.compute([z], sn.TIN(gp), cfg)
dp = np.array([[x, y, 0.5 + 0.01 * x - 0.004 * y] for x in (-20, 120) for y in (-20, 70)])
ef, ec = exact(box(0, 0, 100, 50), gp, dp)
check("TK mặt nghiêng: V đắp TIN", z["tvf"], ef, 1e-3)
check("TK mặt nghiêng: V đào TIN", z["tvc"], ec, 1e-3)
# 14b. TK là TIN điểm cao độ lệch lưới đất, đất gợn sóng, có đào có đắp
rng = np.random.default_rng(7)
gp = grid_pts(-20, 120, -20, 70, 6, lambda x, y: 0.5 * np.sin(x / 17) + 0.3 * np.cos(y / 11))
gp[:, :2] += rng.uniform(-1.5, 1.5, (len(gp), 2))
dp = np.array([[-20, -20, 0.2], [120, -20, -0.4], [120, 70, 0.6], [-20, 70, 0.1], [50, 25, 1.2], [30, 40, -0.3], [75, 12, 0.9], [62, 44, 0.0], [12, 8, 0.7]])
td = sn.Design("tin", pts=dp)
poly = Polygon([(0, 0), (100, 3), (96, 50), (40, 46), (4, 50)])
z = tzone(poly, td, cfg)
sn.compute([z], sn.TIN(gp), cfg)
ef, ec = exact(poly, gp, dp)
check("TK là TIN: V đắp TIN", z["tvf"], ef, 1e-3)
check("TK là TIN: V đào TIN", z["tvc"], ec, 1e-3)
check("TK là TIN: lưới ô gần TIN (%)", 100 * abs(z["vf"] + z["vc"] - ef - ec) / (ef + ec), 0, 6)
# 14c. bóc phong hoá cùng TK là TIN
cfgS = dict(cfg, strip=0.2)
z = tzone(poly, td, cfgS)
sn.compute([z], sn.TIN(gp), cfgS)
ef, ec = exact(poly, gp, dp, strip=0.2)
check("TK là TIN + bóc 0,2: V đắp", z["tvf"], ef, 1e-3)
check("TK là TIN + bóc 0,2: V đào", z["tvc"], ec, 1e-3)
# 14d. vùng điểm TK nhỏ hơn ranh: mặt kéo dài liên tục, có cảnh báo diện tích ngoài
dp2 = np.array([[10, 10, 0.5], [90, 10, 0.8], [90, 40, 0.2], [10, 40, 0.4], [50, 25, 1.0]])
d2 = sn.Design("tin", pts=dp2)
check("Vùng điểm TK nhỏ hơn ranh: diện tích ngoài (m2)", d2.outside_area(box(0, 0, 100, 50)), 5000 - 2400, 1e-6)
e = d2(np.array([[0, 25], [5, 25], [9.999, 25], [10.001, 25]]))
check("Mặt TK kéo dài liên tục qua biên vùng điểm", abs(e[2] - e[3]), 0, 1e-3)
z = tzone(box(0, 0, 100, 50), d2, cfg)
sn.compute([z], sn.TIN(grid_pts(-20, 120, -20, 70, 10, lambda x, y: 0 * x)), cfg)
xs = np.arange(0.05, 100, 0.1); ys = np.arange(0.05, 50, 0.1); XX, YY = np.meshgrid(xs, ys)
hh = d2(np.c_[XX.ravel(), YY.ravel()])
check("Vùng điểm TK nhỏ hơn ranh: V đắp so với tích phân số", z["tvf"], float(hh[hh > 0].sum() * 0.01), 0.002 * z["tvf"])
# 14e. cân bằng khi TK không phẳng: dịch cả mặt thiết kế, đào = K x đắp
gp3 = grid_pts(-20, 120, -20, 70, 6, lambda x, y: 0.5 * np.sin(x / 17) + 0.3 * np.cos(y / 11))
z = tzone(poly, td, cfg)
ov = sn.compute([z], sn.TIN(gp3), cfg)
zd = [td(o.xy.reshape(-1, 2)).reshape(-1, 3) for o in ov]
mer = sn.Merged(ov, zd)
dlt = sn.balance(mer, 1.1)[0]
Vf, Vc, _, _ = mer.volumes(zd[0] + dlt - mer.z)
check("Cân bằng TK không phẳng: đào - K x đắp", float(Vc.sum() - 1.1 * Vf.sum()), 0, 0.5)
dl2 = sn.balance_full(mer, 1.1, None, 0.0)
check("Cân bằng TK không phẳng: hai hàm cùng kết quả", dl2, dlt, 1e-3)

# 15. cao độ tự nhiên
# 15a. khu vượt ra ngoài vùng điểm đo: trước đây phần ngoài bị bỏ sót khối lượng
gp = grid_pts(0, 80, -10, 60, 8, lambda x, y: 0.02 * x)
z = zone(box(0, 0, 100, 50), 2.0, cfg)
sn.compute([z], sn.TIN(gp), cfg)
check("Khu vượt vùng điểm đo: V đắp TIN (kéo dài từ biên)", z["tvf"], 50 * (80 * 2.0 - 0.01 * 80 ** 2) + 20 * 50 * (2.0 - 1.6), 1e-3)
check("Khu vượt vùng điểm đo: diện tích ngoài (m2)", z["ov"].outside, 1000, 1e-6)
check("Khu vượt vùng điểm đo: lưới ô = TIN", z["vf"], z["tvf"], 1e-3)
# 15b. chỉ có đường đồng mức (polyline có cao độ), không có điểm: mặt nghiêng z = 0,02x, đọc từ DXF
d = Path(tempfile.mkdtemp())
doc = ezdxf.new("R2013"); m = doc.modelspace()
for l in ("DUONG DONG MUC", "RANH"):
    doc.layers.add(l)
for x in range(-10, 121, 10):
    pl = m.add_lwpolyline([(x, -10), (x, 25), (x, 60)], dxfattribs={"layer": "DUONG DONG MUC"})
    pl.dxf.elevation = 0.02 * x + 1.0
m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True, dxfattribs={"layer": "RANH"})
f = d / "dong muc.dxf"; doc.saveas(f)
r = sn.run([f], dict(sn.DEFAULTS, td=2.5, k=1.0), d / "out", no_dwg=True)
check("Chỉ có đồng mức: V đắp TIN", r["zones"][0]["tvf"], 50 * (75 * 1.5 - 0.01 * 75 ** 2), 1e-3)
# 15c. điểm đo kèm đồng mức: đồng mức ép cạnh TIN, sườn núi chữ V (đỉnh đường đồng mức gãy góc)
doc = ezdxf.new("R2013"); m = doc.modelspace()
for l in ("TL-CDTN", "TL-DongMuc", "RANH"):
    doc.layers.add(l)
for k in range(0, 6):     # z = |x - 50| * 0.04 + ..., đồng mức hình chữ V quanh rãnh x = 50
    zc = 0.4 * k
    pl = m.add_lwpolyline([(50 - 10 * k, -10), (50 - 10 * k, 60)], dxfattribs={"layer": "TL-DongMuc"}); pl.dxf.elevation = zc
    if k:
        pl = m.add_lwpolyline([(50 + 10 * k, -10), (50 + 10 * k, 60)], dxfattribs={"layer": "TL-DongMuc"}); pl.dxf.elevation = zc
for x, y in ((25, 25), (75, 25)):
    m.add_text(f"{abs(x - 50) * 0.04:.3f}", dxfattribs={"layer": "TL-CDTN", "insert": (x, y)})
m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True, dxfattribs={"layer": "RANH"})
f = d / "rach.dxf"; doc.saveas(f)
r = sn.run([f], dict(sn.DEFAULTS, td=2.0, k=1.0), d / "out2", no_dwg=True)
check("Đồng mức + điểm, rãnh chữ V: V đắp TIN", r["zones"][0]["tvf"], 50 * 2 * (50 * 2.0 - 0.02 * 50 ** 2), 1e-3)

# 16. hố móng chồng nhau và hố giật cấp
tin0 = sn.TIN(grid_pts(-30, 60, -30, 60, 10, lambda x, y: 0 * x))
zz = [dict(poly=box(-20, -20, 40, 40), design=sn.Design("flat", z=0.0))]
c0 = dict(cfg, pit_slope=0, strip=0)
P = sn.calc_pits(zz, tin0, c0, [(box(0, 0, 10, 10), -2.0), (box(5, 5, 15, 15), -2.0)])
check("Hai hố chồng nhau, thành đứng: tổng không tính trùng", sum(p["v"] for p in P), 2 * 175, 1e-6)
check("Hai hố chồng nhau: có ghi chú chồng", "chồng" in P[1]["note"], True, 0)
P = sn.calc_pits(zz, tin0, c0, [(box(0, 0, 20, 20), -2.0), (box(5, 5, 15, 15), -5.0)])
check("Hố giật cấp thành đứng: tổng", sum(p["v"] for p in P), 400 * 2 + 100 * 3, 1e-6)
check("Hố giật cấp: cấp sâu nhận phần sâu", P[1]["v"], 100 * 5, 1e-6)
check("Hố giật cấp: có ghi chú", "giật cấp" in P[1]["note"], True, 0)
# giật cấp có mái 1:1, cơ rộng 5 m, sâu thêm 3 m: tách được thành hai khối chóp cụt cộng lại
c1 = dict(cfg, pit_slope=1.0, strip=0)
P = sn.calc_pits(zz, tin0, c1, [(box(0, 0, 20, 20), -2.0), (box(5, 5, 15, 15), -5.0)])
# đáp số tính số học độc lập: tích phân h(x, y) trên lưới mịn 0,05 m
xs = np.arange(-10, 30, 0.05) + 0.025
XX, YY = np.meshgrid(xs, xs)
from shapely import points as _pts, distance as _dist
Pp = _pts(XX.ravel(), YY.ravel())
b1 = -2.0 + _dist(Pp, box(0, 0, 20, 20)); b2 = -5.0 + _dist(Pp, box(5, 5, 15, 15))
hh = np.maximum(0 - np.minimum(b1, b2), 0)
check("Hố giật cấp mái 1:1: tổng so với tích phân mịn", sum(p["v"] for p in P), float(hh.sum() * 0.0025), 0.003 * float(hh.sum() * 0.0025))
# hố giật cấp đọc từ DXF: hai polyline lồng nhau, mỗi cấp một chữ cao độ đáy
doc = ezdxf.new("R2013"); m = doc.modelspace()
for l in ("TL-CDTN", "TL-HoMong", "RANH"):
    doc.layers.add(l)
for x in range(-30, 61, 10):
    for y in range(-30, 61, 10):
        m.add_text("0.000", dxfattribs={"layer": "TL-CDTN", "insert": (x, y)})
m.add_lwpolyline([(-20, -20), (40, -20), (40, 40), (-20, 40)], close=True, dxfattribs={"layer": "RANH"})
m.add_lwpolyline([(0, 0), (20, 0), (20, 20), (0, 20)], close=True, dxfattribs={"layer": "TL-HoMong"})
m.add_lwpolyline([(5, 5), (15, 5), (15, 15), (5, 15)], close=True, dxfattribs={"layer": "TL-HoMong"})
m.add_text("-2.0", dxfattribs={"layer": "TL-HoMong", "insert": (2, 2)})
m.add_text("-5.0", dxfattribs={"layer": "TL-HoMong", "insert": (10, 10)})
f = d / "ho giat cap.dxf"; doc.saveas(f)
r = sn.run([f], dict(sn.DEFAULTS, td=0.0, pit_slope=0), d / "out3", no_dwg=True)
check("Hố giật cấp từ DXF: tổng", sum(p["v"] for p in r["X"]["pits"]), 1100, 1e-6)
print("TONG:", sum(R), "/", len(R), flush=True)
