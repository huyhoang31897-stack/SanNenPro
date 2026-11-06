;;; SanNenPro - lenh chay trong AutoCAD
;;; SANNEN    : luu ban ve, mo SanNenPro voi ban ve hien hanh
;;; SANNENKQ  : chen ket qua SanNen_MatBang.dwg vao ban ve (dung toa do),
;;;             chay lai thi thay ket qua cu
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

(defun c:SANNENKQ (/ f i n s e)
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
     (command "_.-INSERT" (strcat n "=" f) "_non" '(0.0 0.0 0.0) 1.0 1.0 0.0)
     (setvar "CMDECHO" e)
     (princ "\nDa chen ket qua tai dung toa do.")
    )
  )
  (princ)
)

(princ "\nSanNenPro: go SANNEN de tinh, SANNENKQ de chen ket qua.")
(princ)
