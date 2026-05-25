import cv2
import numpy as np


class OMRProcessor:
    """OMR V4 PRO: page-warp + locked layout + blob/score verification.

    Bu versiyada asosiy o'zgarish:
    - Avval qog'oz varaqasi topilib 900x1273 canonical formatga tekislanadi.
    - Keyin eski blankangiz uchun aniq layout ishlatiladi.
    - Hough/KMeans faqat mayda siljishni tuzatish uchun yordamchi sifatida ishlatiladi.
    - 1-32 savollar A/B/C/D, 33-35 savollar A/B/C/D/E/F.
    """

    W = 900
    H = 1273
    OPTIONS4 = ["A", "B", "C", "D"]
    OPTIONS6 = ["A", "B", "C", "D", "E", "F"]

    # Canonical page layout. Ushbu qiymatlar siz yuborgan blankaga mos.
    BASE = {
        "L": {"x": [186, 223, 260, 297], "y0": 266, "step": 41.0, "rows": 18},
        "R": {"x": [504, 541, 578, 615], "y0": 260, "step": 41.0, "rows": 14},
        "B": {"x": [514, 548, 582, 616, 650, 684], "y0": 883, "step": 43.0, "rows": 3},
    }

    @staticmethod
    def _order_points(pts):
        pts = np.array(pts, dtype="float32")
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1).reshape(-1)
        rect = np.zeros((4, 2), dtype="float32")
        rect[0] = pts[np.argmin(s)]      # top-left
        rect[2] = pts[np.argmax(s)]      # bottom-right
        rect[1] = pts[np.argmin(diff)]   # top-right
        rect[3] = pts[np.argmax(diff)]   # bottom-left
        return rect

    @staticmethod
    def _warp_page(img):
        """Qog'oz konturini topib canonical o'lchamga warp qiladi."""
        h, w = img.shape[:2]
        scale = 1100.0 / max(w, h)
        small = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        # Oq varaqni fon/rangli gilamdan ajratish.
        th1 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        th2 = cv2.inRange(gray, 135, 255)
        mask = cv2.bitwise_or(th1, th2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((19, 19), np.uint8), iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8), iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_area = 0
        img_area = small.shape[0] * small.shape[1]
        for c in contours:
            area = cv2.contourArea(c)
            if area < img_area * 0.25:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.025 * peri, True)
            if len(approx) == 4:
                x, y, bw, bh = cv2.boundingRect(approx)
                ratio = max(bw, bh) / max(1, min(bw, bh))
                if 1.1 <= ratio <= 1.9 and area > best_area:
                    best = approx.reshape(4, 2) / scale
                    best_area = area

        # Agar 4 burchak topilmasa, minAreaRect bilan ham urinib ko'ramiz.
        if best is None and contours:
            c = max(contours, key=cv2.contourArea)
            if cv2.contourArea(c) > img_area * 0.25:
                box = cv2.boxPoints(cv2.minAreaRect(c)) / scale
                best = box

        if best is not None:
            src = OMRProcessor._order_points(best)
            dst = np.array([[0, 0], [OMRProcessor.W - 1, 0], [OMRProcessor.W - 1, OMRProcessor.H - 1], [0, OMRProcessor.H - 1]], dtype="float32")
            M = cv2.getPerspectiveTransform(src, dst)
            warped = cv2.warpPerspective(img, M, (OMRProcessor.W, OMRProcessor.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            return warped, "page_warp"

        # Fallback: width bo'yicha resize va markaziy canvas.
        scale2 = OMRProcessor.W / float(w)
        resized = cv2.resize(img, (OMRProcessor.W, int(h * scale2)), interpolation=cv2.INTER_AREA)
        canvas = np.full((OMRProcessor.H, OMRProcessor.W, 3), 255, dtype=np.uint8)
        rh = resized.shape[0]
        if rh >= OMRProcessor.H:
            y0 = max(0, (rh - OMRProcessor.H) // 2)
            canvas[:] = resized[y0:y0 + OMRProcessor.H]
        else:
            y = (OMRProcessor.H - rh) // 2
            canvas[y:y + rh] = resized
        return canvas, "resize_canvas_fallback"

    @staticmethod
    def _detect_filled_blobs(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Yoritish tenglashtirish: soyalar kamayadi, ruchka dog'i ajraladi.
        bg = cv2.GaussianBlur(gray, (0, 0), 25)
        norm = cv2.subtract(bg, gray)
        dark = cv2.inRange(gray, 0, 118)
        contrast = cv2.inRange(norm, 30, 255)
        mask = cv2.bitwise_or(dark, contrast)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blobs = []
        for c in contours:
            area = cv2.contourArea(c)
            if not (18 <= area <= 650):
                continue
            x, y, w, h = cv2.boundingRect(c)
            if not (3 <= w <= 34 and 3 <= h <= 34):
                continue
            ratio = w / max(1, h)
            if not (0.38 <= ratio <= 2.6):
                continue
            per = cv2.arcLength(c, True)
            circ = 0 if per == 0 else 4 * np.pi * area / (per * per)
            if circ < 0.16:
                continue
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            cx = float(M["m10"] / M["m00"])
            cy = float(M["m01"] / M["m00"])
            # Faqat javob zonalariga yaqin bloblarni qoldiramiz, ism/familiya yozuvini chiqaramiz.
            if cy > 1035:
                continue
            blobs.append({"x": cx, "y": cy, "area": float(area), "circ": float(circ)})
        return blobs, mask

    @staticmethod
    def _detect_circles(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        allc = []
        for p2 in (13, 16, 19, 22):
            cs = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=14, param1=80, param2=p2, minRadius=5, maxRadius=16)
            if cs is None:
                continue
            for x, y, r in np.round(cs[0]).astype(int):
                if 120 <= x <= 730 and 190 <= y <= 1010:
                    allc.append((float(x), float(y), float(r)))
        uniq = []
        for x, y, r in sorted(allc, key=lambda t: (t[1], t[0])):
            if not any((x - ux) ** 2 + (y - uy) ** 2 < 7 ** 2 for ux, uy, _ in uniq):
                uniq.append((x, y, r))
        return uniq

    @staticmethod
    def _near_points(points, x1, x2, y1, y2, kind="circle"):
        if kind == "circle":
            return [(x, y) for x, y, _ in points if x1 <= x <= x2 and y1 <= y <= y2]
        return [(p["x"], p["y"]) for p in points if x1 <= p["x"] <= x2 and y1 <= p["y"] <= y2]

    @staticmethod
    def _median_shift_from_candidates(base_xs, base_ys, candidates, max_dx=18, max_dy=18):
        dxs, dys = [], []
        for bx in base_xs:
            for by in base_ys:
                best = None
                for x, y in candidates:
                    dx, dy = x - bx, y - by
                    if abs(dx) <= max_dx and abs(dy) <= max_dy:
                        d = dx * dx + dy * dy
                        if best is None or d < best[0]:
                            best = (d, dx, dy)
                if best is not None:
                    dxs.append(best[1]); dys.append(best[2])
        if len(dxs) >= 4:
            return float(np.median(dxs)), float(np.median(dys)), len(dxs)
        return 0.0, 0.0, len(dxs)

    @staticmethod
    def _build_grid(circles, blobs):
        grid = {}
        debug = []
        for name, cfg in OMRProcessor.BASE.items():
            xs = np.array(cfg["x"], dtype=float)
            ys = np.array([cfg["y0"] + i * cfg["step"] for i in range(cfg["rows"])], dtype=float)
            margin_x = 35
            margin_y = 25
            candidates = OMRProcessor._near_points(circles, xs.min()-margin_x, xs.max()+margin_x, ys.min()-margin_y, ys.max()+margin_y, "circle")
            candidates += OMRProcessor._near_points(blobs, xs.min()-margin_x, xs.max()+margin_x, ys.min()-margin_y, ys.max()+margin_y, "blob")
            dx, dy, n = OMRProcessor._median_shift_from_candidates(xs, ys, candidates)
            # Juda katta siljish bo'lsa qabul qilmaymiz.
            if abs(dx) > 14 or abs(dy) > 14:
                dx, dy = 0.0, 0.0
            xs = xs + dx
            ys = ys + dy
            debug.append(f"{name}:lock n={n} dx={dx:.1f} dy={dy:.1f}")
            if name == "L":
                for i, y in enumerate(ys):
                    grid[i + 1] = [(OMRProcessor.OPTIONS4[j], float(xs[j]), float(y)) for j in range(4)]
            elif name == "R":
                for i, y in enumerate(ys):
                    grid[i + 19] = [(OMRProcessor.OPTIONS4[j], float(xs[j]), float(y)) for j in range(4)]
            else:
                for i, y in enumerate(ys):
                    grid[i + 33] = [(OMRProcessor.OPTIONS6[j], float(xs[j]), float(y)) for j in range(6)]
        return grid, "layout_lock_v4 " + " ".join(debug)

    @staticmethod
    def _parse_key(answer_key_dict):
        clean = {}
        for k, v in answer_key_dict.items():
            try:
                q = int(k)
            except Exception:
                continue
            ans = str(v).strip().upper()
            if 1 <= q <= 32 and ans in OMRProcessor.OPTIONS4:
                clean[q] = ans
            elif 33 <= q <= 35 and ans in OMRProcessor.OPTIONS6:
                clean[q] = ans
        return clean

    @staticmethod
    def _center_score(img, cx, cy):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bg = cv2.GaussianBlur(gray, (0, 0), 23)
        norm = cv2.subtract(bg, gray)
        x = int(round(cx)); y = int(round(cy)); r = 13
        y1, y2 = max(0, y - r), min(gray.shape[0], y + r + 1)
        x1, x2 = max(0, x - r), min(gray.shape[1], x + r + 1)
        roi = gray[y1:y2, x1:x2]
        nro = norm[y1:y2, x1:x2]
        if roi.size == 0:
            return 0.0
        mask = np.zeros(roi.shape, dtype=np.uint8)
        cv2.circle(mask, (x - x1, y - y1), 8, 255, -1)
        inner = roi[mask > 0]
        inn = nro[mask > 0]
        dark_density = float(np.mean(inner < 120))
        very_dark = float(np.mean(inner < 88))
        contrast_mean = float(np.mean(inn))
        darkest = float(255 - np.percentile(inner, 12))
        return contrast_mean + dark_density * 75 + very_dark * 95 + darkest * 0.20

    @staticmethod
    def _marks_for_question(img, centers, blobs):
        raw = []
        for opt, cx, cy in centers:
            best_blob_score = 0.0
            bx, by = cx, cy
            for b in blobs:
                dx, dy = abs(b["x"] - cx), abs(b["y"] - cy)
                if dx <= 17 and dy <= 17:
                    dist = (dx * dx + dy * dy) ** 0.5
                    score = min(145.0, b["area"] * 1.65) + max(0, 22 - dist) * 3.4
                    if score > best_blob_score:
                        best_blob_score = score
                        bx, by = b["x"], b["y"]
            score = max(best_blob_score, OMRProcessor._center_score(img, cx, cy))
            raw.append({"opt": opt, "x": bx, "y": by, "score": float(score), "cx": cx, "cy": cy})
        order = sorted(raw, key=lambda r: r["score"], reverse=True)
        if not order:
            return [], raw
        scores = np.array([r["score"] for r in order], dtype=float)
        top = float(scores[0])
        second = float(scores[1]) if len(scores) > 1 else 0.0
        # Bo'sh doiralarda score odatda 25-55; bo'yalgan nuqta 80+ bo'ladi.
        # Top kuchsiz bo'lsa bo'sh deb qabul qilamiz.
        if top < 66:
            return [], raw
        marked = [r for r in order if r["score"] >= max(68, top * 0.64)]
        # Ikkilamchi signal past bo'lsa bitta mark.
        if len(marked) > 1 and second < top * 0.58:
            marked = [order[0]]
        # 3+ mark odatda noise bo'lishi mumkin; faqat topga juda yaqinlarini qoldiramiz.
        if len(marked) > 2:
            marked = [r for r in marked if r["score"] >= top * 0.78]
        return marked, raw

    @staticmethod
    def analyze_sheet(image_bytes, answer_key_dict):
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Rasm ochilmadi. Iltimos, JPG/PNG rasm yuboring.")

        work, page_mode = OMRProcessor._warp_page(img)
        blobs, _ = OMRProcessor._detect_filled_blobs(work)
        circles = OMRProcessor._detect_circles(work)
        grid, align = OMRProcessor._build_grid(circles, blobs)
        align_method = page_mode + " + " + align
        key = OMRProcessor._parse_key(answer_key_dict)

        correct = wrong = skipped = invalid = 0
        questions = []
        vis = work.copy()

        for q in range(1, 36):
            centers = grid[q]
            answer = key.get(q, "-")
            marked, all_scores = OMRProcessor._marks_for_question(work, centers, blobs)

            if len(marked) == 0:
                student = "BO'SH"
                status = "skipped"
                skipped += 1
                color = (150, 150, 150)
            elif len(marked) > 1:
                student = ",".join(m["opt"] for m in marked)
                status = "invalid"
                invalid += 1
                wrong += 1
                color = (0, 0, 255)
            else:
                student = marked[0]["opt"]
                if student == answer:
                    status = "correct"
                    correct += 1
                    color = (0, 175, 0)
                else:
                    status = "wrong"
                    wrong += 1
                    color = (0, 0, 255)

            # Vizual: kulrang grid, kalit ko'k, o'quvchi javobi yashil/qizil.
            for opt, cx, cy in centers:
                cv2.circle(vis, (int(round(cx)), int(round(cy))), 10, (210, 210, 210), 1)
            for opt, cx, cy in centers:
                if opt == answer:
                    cv2.circle(vis, (int(round(cx)), int(round(cy))), 14, (255, 170, 0), 2)
            for m in marked:
                cv2.circle(vis, (int(round(m["x"])), int(round(m["y"]))), 17, color, 3)

            first_x, first_y = centers[0][1], centers[0][2]
            cv2.putText(vis, str(q), (int(first_x) - 48, int(first_y) + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)
            questions.append({
                "num": q,
                "key": answer,
                "student": student,
                "status": status,
                "scores": {r["opt"]: round(float(r["score"]), 1) for r in all_scores},
                "align_method": align_method,
            })

        total = 35
        percentage = round(correct / total * 100, 2)
        cv2.rectangle(vis, (18, 14), (min(880, vis.shape[1] - 18), 108), (255, 255, 255), -1)
        cv2.putText(vis, f"Natija: {correct}/{total}  Foiz: {percentage}%", (36, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (0, 0, 0), 2)
        cv2.putText(vis, f"Xato: {wrong} | Bo'sh: {skipped} | 2 ta belgi: {invalid}", (36, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2)
        cv2.putText(vis, f"Align: {align_method[:112]}", (36, 102), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (80, 80, 80), 1)
        ok, encoded = cv2.imencode(".png", vis)
        if not ok:
            raise RuntimeError("Tekshirilgan rasmni yaratib bo'lmadi.")
        return {
            "correct_count": correct,
            "wrong_count": wrong,
            "skipped_count": skipped,
            "invalid_count": invalid,
            "total_score": correct,
            "percentage": percentage,
            "questions": questions,
            "visual_png": encoded.tobytes(),
            "align_method": align_method,
        }
