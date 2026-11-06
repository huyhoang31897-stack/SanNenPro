;;; SanNenPro - lenh chay trong AutoCAD
;;; SANNEN    : luu ban ve, mo SanNenPro voi ban ve hien hanh
;;; SANNENKQ  : chen ket qua SanNen_MatBang.dwg vao ban ve (dung toa do),
;;;             chay lai thi thay ket qua cu
;;; SANNEN3D  : chen mo hinh 3D SanNen_3D.dwg (khoi solid) vao ban ve, dung toa do,
;;;             chuyen goc nhin 3D. Chay lai thi thay mo hinh cu
;;; Can chay SanNenPro.exe it nhat 1 lan truoc khi dung lenh.

(defun sn:bat (/ f)
  (setq f (strcat (getenv "LOCALAPPDATA") "\\SanNenPro\\run.bat"))
  (if (findfile f) f nil)
)

(defun sn:dwg ()
  (strcat (getvar "DWGPREFIX") (getvar "DWGNAME"))
)

(defun sn:kq ()
  (strcat (getvar "DWGPREFIX") (vl-filename-base (getvar "DWGNAME")) "_SANNEN\\SanNen_MatBang.dwg")
)

(defun sn:kq3 ()
  (strcat (getvar "DWGPREFIX") (vl-filename-base (getvar "DWGNAME")) "_SANNEN\\SanNen_3D.dwg")
)

(defun c:SANNEN (/ b)
  (cond
    ((= (getvar "DWGTITLED") 0) (princ "\nHay luu ban ve truoc khi chay SANNEN."))
    ((null (setq b (sn:bat))) (princ "\nChua co SanNenPro. Hay mo SanNenPro.exe mot lan roi chay lai."))
    (T
     (if (/= (getvar "DBMOD") 0) (command "_.QSAVE"))
     (startapp "cmd.exe" (strcat "/c \"\"" b "\" \"" (sn:dwg) "\"\""))
     (princ "\nDa mo SanNenPro. Tinh xong go SANNENKQ de chen ket qua.")
    )
  )
  (princ)
)

(defun c:SANNENKQ (/ f i n s e u)
  (setq f (sn:kq))
  (cond
    ((null (findfile f)) (princ (strcat "\nChua co ket qua: " f)))
    (T
     (setq e (getvar "CMDECHO") i 1)
     (setvar "CMDECHO" 0)
     (if (setq s (ssget "_X" '((0 . "INSERT") (2 . "SanNen_KQ*"))))
       (command "_.ERASE" s "")
     )
     (while (tblsearch "BLOCK" (setq n (strcat "SanNen_KQ" (itoa i)))) (setq i (1+ i)))
     ;; ket qua ghi theo met, giu ty le 1:1 du ban ve dat don vi gi
     (setq u (getvar "INSUNITS"))
     (setvar "INSUNITS" 6)
     (command "_.-INSERT" (strcat n "=" f) "_non" '(0.0 0.0 0.0) 1.0 1.0 0.0)
     (setvar "INSUNITS" u)
     (setvar "CMDECHO" e)
     (princ "\nDa chen ket qua tai dung toa do.")
    )
  )
  (princ)
)

(defun c:SANNEN3D (/ f i n s e u)
  (setq f (sn:kq3))
  (cond
    ((null (findfile f)) (princ (strcat "\nChua co mo hinh 3D: " f "\nChay SanNenPro co tick Xuat 3D roi chay lai.")))
    (T
     (setq e (getvar "CMDECHO") i 1)
     (setvar "CMDECHO" 0)
     (if (setq s (ssget "_X" '((8 . "SN3D_*")))) (command "_.ERASE" s ""))
     (while (tblsearch "BLOCK" (setq n (strcat "SanNen_3D" (itoa i)))) (setq i (1+ i)))
     ;; ket qua ghi theo met, giu ty le 1:1 du ban ve dat don vi gi
     (setq u (getvar "INSUNITS"))
     (setvar "INSUNITS" 6)
     (command "_.-INSERT" (strcat n "=" f) "_non" '(0.0 0.0 0.0) 1.0 1.0 0.0)
     (setvar "INSUNITS" u)
     (command "_.EXPLODE" (entlast))
     (command "_.-VIEW" "_SE")
     (vl-catch-all-apply 'vl-cmdf '("_.VSCURRENT" "_E"))
     (command "_.ZOOM" "_E")
     (setvar "CMDECHO" e)
     (princ "\nDa chen mo hinh 3D. Chon khoi va go MASSPROP de xem the tich.")
    )
  )
  (princ)
)

(princ "\nSanNenPro: go SANNEN de tinh, SANNENKQ de chen mat bang, SANNEN3D de chen mo hinh 3D.")
(princ)
