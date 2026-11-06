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
print("TONG:", sum(R), "/", len(R), flush=True)
