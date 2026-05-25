import cv2
import numpy as np


class OMRProcessor:
    """OMR V3: Hough/KMeans grid + filled-blob verification.

    Eski versiyadagi asosiy xato: grid savol raqamlari yoki yozuvlarga siljib ketardi.
    Bu versiyada:
    - har blok uchun x/y grid alohida RANSAC-like regular fit bilan topiladi;
    - o'ng blokda savol raqamlari x-range dan chiqarib tashlandi;
    - javob tanlash faqat real siyoh blob yoki markazdagi qorayish score bilan qilinadi;
    - 1-32 A/B/C/D, 33-35 A/B/C/D/E/F.
    """

    TARGET_W = 900
    OPTIONS4 = ["A", "B", "C", "D"]
    OPTIONS6 = ["A", "B", "C", "D", "E", "F"]

    @staticmethod
    def _resize_keep_aspect(img):
        h, w = img.shape[:2]
        scale = OMRProcessor.TARGET_W / float(w)
        return cv2.resize(img, (OMRProcessor.TARGET_W, int(h * scale)), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _detect_hough_circles(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        circles_all = []
        for p2 in (12, 14, 16, 18, 20):
            circles = cv2.HoughCircles(
                gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=12,
                param1=70, param2=p2, minRadius=5, maxRadius=15
            )
            if circles is not None:
                for x, y, r in np.round(circles[0]).astype(int):
                    circles_all.append((float(x), float(y), float(r)))
        uniq = []
        for x, y, r in sorted(circles_all, key=lambda t: (t[1], t[0])):
            if not any((x - ux) ** 2 + (y - uy) ** 2 < 7 ** 2 for ux, uy, _ in uniq):
                uniq.append((x, y, r))
        return uniq

    @staticmethod
    def _detect_filled_blobs(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Qorong'i ruchka/siyoh. Jigarrang bo'sh konturlar asosan 120+ bo'ladi.
        mask1 = cv2.inRange(gray, 0, 115)
        # Local contrast: soyali joyda ham siyohni ushlash uchun.
        bg = cv2.GaussianBlur(gray, (0, 0), 19)
        diff = cv2.subtract(bg, gray)
        mask2 = cv2.inRange(diff, 32, 255)
        mask = cv2.bitwise_or(mask1, mask2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blobs = []
        for c in contours:
            area = cv2.contourArea(c)
            if not (24 <= area <= 520):
                continue
            per = cv2.arcLength(c, True)
            if per <= 0:
                continue
            circ = 4 * np.pi * area / (per * per)
            x, y, w, h = cv2.boundingRect(c)
            if not (4 <= w <= 30 and 4 <= h <= 30):
                continue
            ratio = w / max(1, h)
            if ratio < 0.45 or ratio > 2.2:
                continue
            if circ < 0.22:
                continue
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            cx = float(M["m10"] / M["m00"])
            cy = float(M["m01"] / M["m00"])
            blobs.append({"x": cx, "y": cy, "area": float(area), "circ": float(circ)})
        return blobs, mask

    @staticmethod
    def _fit_regular_grid(vals, k, step_min, step_max, fallback_start, fallback_step, tol=11):
        vals = np.array(sorted([float(v) for v in vals]), dtype=float)
        if len(vals) == 0:
            return [fallback_start + i * fallback_step for i in range(k)], False

        best = None
        # Savol raqamlari / yozuvlar aralashib ketsa ham, eng ko'p real doira tushadigan
        # regular grid tanlanadi.
        for step in np.linspace(step_min, step_max, 121):
            starts = []
            for v in vals:
                for i in range(k):
                    starts.append(v - i * step)
            stride = max(1, len(starts) // 350)
            for st in starts[::stride]:
                if abs(st - fallback_start) > max(85, step * 2.5):
                    continue
                grid = st + np.arange(k) * step
                dg = np.min(np.abs(vals[None, :] - grid[:, None]), axis=1)
                matched = int((dg < tol).sum())
                # Grid nuqtalarining hammasi imkon qadar Hough doiraga yaqin bo'lsin.
                err = float(np.mean(np.clip(dg, 0, tol + 8)))
                score = (matched, -err, -abs(step - fallback_step), -abs(st - fallback_start))
                if best is None or score > best[0]:
                    best = (score, float(st), float(step))
        if best is not None and best[0][0] >= max(2, k // 2):
            _, st, step = best
            return [st + i * step for i in range(k)], True
        return [fallback_start + i * fallback_step for i in range(k)], False

    @staticmethod
    def _region(items, x1, x2, y1, y2, circle=False):
        if circle:
            return [p for p in items if x1 <= p[0] <= x2 and y1 <= p[1] <= y2]
        return [p for p in items if x1 <= p["x"] <= x2 and y1 <= p["y"] <= y2]

    @staticmethod
    def _grid_from_circles_and_blobs(circles, blobs, height):
        # 900px widthga moslangan form layout. O'ng blokda x1=490 qilindi,
        # chunki 430-480 oralig'ida savol raqamlari Hough circle sifatida chiqib ketadi.
        configs = {
            "L": dict(x1=145, x2=335, y1=int(height * 0.16), y2=int(height * 0.78), kx=4, ky=18,
                      fx=[185, 221, 257, 293], fy=250, fstep=37.5),
            "R": dict(x1=490, x2=650, y1=int(height * 0.15), y2=int(height * 0.68), kx=4, ky=14,
                      fx=[501, 535, 569, 603], fy=238, fstep=39.5),
            "B": dict(x1=490, x2=760, y1=int(height * 0.68), y2=int(height * 0.88), kx=6, ky=3,
                      fx=[515, 546, 577, 608, 639, 670], fy=855, fstep=40.0),
        }
        grids = {}
        debug = []
        for name, c in configs.items():
            hc = OMRProcessor._region(circles, c["x1"], c["x2"], c["y1"], c["y2"], circle=True)
            bl = OMRProcessor._region(blobs, c["x1"], c["x2"], c["y1"], c["y2"], circle=False)
            xs = [p[0] for p in hc] + [p["x"] for p in bl]
            ys = [p[1] for p in hc] + [p["y"] for p in bl]
            fallback_step_x = c["fx"][1] - c["fx"][0]
            xcent, okx = OMRProcessor._fit_regular_grid(xs, c["kx"], max(24, fallback_step_x - 9), fallback_step_x + 9,
                                                         c["fx"][0], fallback_step_x, tol=12)
            ycent, oky = OMRProcessor._fit_regular_grid(ys, c["ky"], max(28, c["fstep"] - 8), c["fstep"] + 8,
                                                         c["fy"], c["fstep"], tol=12)
            grids[name] = (xcent, ycent)
            debug.append(f"{name}:H{len(hc)}/B{len(bl)}:{'ok' if okx and oky else 'partial'}")

        grid = {}
        lx, ly = grids["L"]
        for row in range(18):
            grid[row + 1] = [(OMRProcessor.OPTIONS4[i], lx[i], ly[row]) for i in range(4)]
        rx, ry = grids["R"]
        for row in range(14):
            grid[row + 19] = [(OMRProcessor.OPTIONS4[i], rx[i], ry[row]) for i in range(4)]
        bx, by = grids["B"]
        for row in range(3):
            grid[row + 33] = [(OMRProcessor.OPTIONS6[i], bx[i], by[row]) for i in range(6)]
        return grid, "hough_kmeans_blob_v3 " + " ".join(debug)

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
        bg = cv2.GaussianBlur(gray, (0, 0), 21)
        norm = cv2.subtract(bg, gray)
        x = int(round(cx)); y = int(round(cy)); r = 12
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
        # Centerdan ozroq siljigan nuqta ham ushlsin: eng qorong'i 30% ni ham qo'shamiz.
        dark_density = float(np.mean(inner < 118))
        very_dark = float(np.mean(inner < 90))
        local_contrast = float(np.mean(inn))
        darkest = float(255 - np.percentile(inner, 15))
        return local_contrast + dark_density * 70 + very_dark * 90 + darkest * 0.18

    @staticmethod
    def _marks_for_question(img, centers, blobs):
        raw = []
        for opt, cx, cy in centers:
            # 1) Real filled blob markazga yaqinmi?
            near = []
            for b in blobs:
                dx = abs(b["x"] - cx)
                dy = abs(b["y"] - cy)
                if dx <= 18 and dy <= 18:
                    dist = (dx * dx + dy * dy) ** 0.5
                    # blob katta bo'lsa ishonch ko'proq
                    near.append((dist, b))
            blob_score = 0.0
            bx, by = cx, cy
            if near:
                near.sort(key=lambda t: t[0])
                best = near[0][1]
                bx, by = best["x"], best["y"]
                blob_score = min(130.0, best["area"] * 1.5) + max(0, 22 - near[0][0]) * 3
            # 2) Markazdagi qora foiz ham tekshiriladi.
            score = max(blob_score, OMRProcessor._center_score(img, cx, cy))
            raw.append({"opt": opt, "x": bx, "y": by, "score": float(score), "cx": cx, "cy": cy})

        scores = [r["score"] for r in raw]
        if not scores:
            return [], raw
        order = sorted(raw, key=lambda r: r["score"], reverse=True)
        top = order[0]["score"]
        second = order[1]["score"] if len(order) > 1 else 0

        # Dinamik threshold: bo'sh doiralardan yuqori, ruchka nuqtadan past.
        marked = []
        for r in order:
            if r["score"] >= 54 and r["score"] >= top * 0.62:
                marked.append(r)
        # Agar eng kuchli signal aniq, ikkinchi signal juda past bo'lsa bitta deb qabul qilamiz.
        if top >= 48 and (not marked):
            marked = [order[0]]
        if len(marked) > 1 and second < top * 0.55:
            marked = [order[0]]
        return marked, raw

    @staticmethod
    def analyze_sheet(image_bytes, answer_key_dict):
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Rasm ochilmadi. Iltimos, JPG/PNG rasm yuboring.")

        work = OMRProcessor._resize_keep_aspect(img)
        blobs, _ = OMRProcessor._detect_filled_blobs(work)
        circles = OMRProcessor._detect_hough_circles(work)
        grid, align_method = OMRProcessor._grid_from_circles_and_blobs(circles, blobs, work.shape[0])
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

            # Vizual: grid kulrang, kalit ko'k, o'quvchi javobi yashil/qizil.
            for opt, cx, cy in centers:
                cv2.circle(vis, (int(round(cx)), int(round(cy))), 10, (210, 210, 210), 1)
            for opt, cx, cy in centers:
                if opt == answer:
                    cv2.circle(vis, (int(round(cx)), int(round(cy))), 14, (255, 170, 0), 2)
            for m in marked:
                cv2.circle(vis, (int(round(m["x"])), int(round(m["y"]))), 17, color, 3)

            first_x, first_y = centers[0][1], centers[0][2]
            cv2.putText(vis, str(q), (int(first_x) - 44, int(first_y) + 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)

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
        total_score = correct

        cv2.rectangle(vis, (18, 14), (min(880, vis.shape[1] - 18), 104), (255, 255, 255), -1)
        cv2.putText(vis, f"Natija: {correct}/{total}  Foiz: {percentage}%", (36, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.78, (0, 0, 0), 2)
        cv2.putText(vis, f"Xato: {wrong} | Bo'sh: {skipped} | 2 ta belgi: {invalid}", (36, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2)
        cv2.putText(vis, f"Align: {align_method[:95]}", (36, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.33, (80, 80, 80), 1)

        ok, encoded = cv2.imencode(".png", vis)
        if not ok:
            raise RuntimeError("Tekshirilgan rasmni yaratib bo'lmadi.")

        return {
            "correct_count": correct,
            "wrong_count": wrong,
            "skipped_count": skipped,
            "invalid_count": invalid,
            "total_score": total_score,
            "percentage": percentage,
            "questions": questions,
            "visual_png": encoded.tobytes(),
            "align_method": align_method,
        }
