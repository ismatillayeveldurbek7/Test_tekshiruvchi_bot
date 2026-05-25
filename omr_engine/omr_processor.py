import cv2
import numpy as np


class OMRProcessor:
    """Filled-dot detection + clustering OMR.

    Bu versiya oldingi overlay muammosini tuzatadi: bo'sh doira konturlarini
    yoki soyani javob deb olmaydi. Asosiy tekshiruv faqat qora/ko'k ruchka bilan
    bo'yalgan real nuqtalar (filled blobs) bo'yicha amalga oshiriladi.

    Blank:
    - 1-18 chap blok: A/B/C/D
    - 19-32 o'ng yuqori blok: A/B/C/D
    - 33-35 o'ng pastki blok: A/B/C/D/E/F
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
    def _cluster_1d(values, k):
        vals = np.array(values, dtype=np.float32).reshape(-1, 1)
        if len(vals) < k:
            raise ValueError("not enough values")
        centers = np.percentile(vals.ravel(), np.linspace(3, 97, k)).astype(np.float32)
        for _ in range(60):
            dist = np.abs(vals - centers.reshape(1, -1))
            labels = dist.argmin(axis=1)
            new = centers.copy()
            for i in range(k):
                part = vals.ravel()[labels == i]
                if len(part):
                    new[i] = float(np.median(part))
            if np.max(np.abs(new - centers)) < 0.05:
                break
            centers = new
        return sorted([float(c) for c in centers])

    @staticmethod
    def _merge_close(vals, tol=12):
        vals = sorted([float(v) for v in vals])
        groups = []
        for v in vals:
            if not groups or abs(v - groups[-1][-1]) > tol:
                groups.append([v])
            else:
                groups[-1].append(v)
        return [float(np.median(g)) for g in groups]

    @staticmethod
    def _regular_centers_from_marks(vals, k, fallback_start, fallback_step):
        """Marked y/x lardan regular grid markazlarini chiqaradi."""
        vals = [float(v) for v in vals]
        if len(vals) >= k:
            try:
                c = OMRProcessor._cluster_1d(vals, k)
                # kmeans ba'zan bir joyga tiqilib qolsa, tekshiramiz
                diffs = np.diff(c)
                if len(diffs) and np.median(diffs) > 10:
                    return c, True
            except Exception:
                pass
        merged = OMRProcessor._merge_close(vals, tol=14)
        if len(merged) >= 2:
            diffs = np.diff(merged)
            diffs = [d for d in diffs if 18 <= d <= 60]
            step = float(np.median(diffs)) if diffs else fallback_step
            first = min(merged)
            # Agar birinchi aniqlangan belgi 1-qator bo'lmasa, fallback bilan solishtirib yaqinlashtiramiz.
            # Rasm formati odatda barqaror, shuning uchun fallback_start juda qo'pol emas.
            n_shift = round((first - fallback_start) / step)
            start = first - max(0, n_shift) * step
            return [start + i * step for i in range(k)], False
        return [fallback_start + i * fallback_step for i in range(k)], False

    @staticmethod
    def _detect_filled_blobs(img):
        """Qora/ko'k bo'yalgan javob nuqtalarini topadi."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Faqat real qorong'i siyohni olamiz. Oldingi versiyadagi HSV/saturation
        # maskasi bo'sh jigarrang doira konturlarini ham javob deb olayotgan edi.
        # Shuning uchun asosiy signal: gray < 110.
        mask = cv2.inRange(gray, 0, 110)

        # Shovqinni tozalash
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blobs = []
        for c in contours:
            area = cv2.contourArea(c)
            if not (28 <= area <= 420):
                continue
            per = cv2.arcLength(c, True)
            if per <= 0:
                continue
            circularity = 4 * np.pi * area / (per * per)
            x, y, w, h = cv2.boundingRect(c)
            if not (5 <= w <= 28 and 5 <= h <= 28):
                continue
            if circularity < 0.28:  # handwriting/harflarni chiqarib tashlash
                continue
            # Filled dot ichki qismi zich bo'ladi; bo'sh doira konturi kam zichlikka ega.
            (ex, ey), er = cv2.minEnclosingCircle(c)
            rr = max(4, int(round(er)))
            yy1, yy2 = max(0, int(ey) - rr), min(mask.shape[0], int(ey) + rr + 1)
            xx1, xx2 = max(0, int(ex) - rr), min(mask.shape[1], int(ex) + rr + 1)
            roi = mask[yy1:yy2, xx1:xx2]
            cm = np.zeros(roi.shape, dtype=np.uint8)
            cv2.circle(cm, (int(ex) - xx1, int(ey) - yy1), max(3, rr - 1), 255, -1)
            density = np.count_nonzero(cv2.bitwise_and(roi, roi, mask=cm)) / max(1, np.count_nonzero(cm))
            if density < 0.32:
                continue
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            cx = float(M["m10"] / M["m00"])
            cy = float(M["m01"] / M["m00"])
            blobs.append({"x": cx, "y": cy, "area": float(area), "circ": float(circularity)})
        return blobs, mask

    @staticmethod
    def _detect_hough_circles(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        circles_all = []
        for p2 in (14, 17, 20):
            circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=16,
                                       param1=80, param2=p2, minRadius=5, maxRadius=18)
            if circles is not None:
                for x, y, r in np.round(circles[0]).astype(int):
                    circles_all.append((float(x), float(y), float(r)))
        uniq = []
        for x, y, r in sorted(circles_all, key=lambda t: (t[1], t[0])):
            if not any((x - ux) ** 2 + (y - uy) ** 2 < 9 ** 2 for ux, uy, _ in uniq):
                uniq.append((x, y, r))
        return uniq

    @staticmethod
    def _region_points(items, x1, x2, y1, y2):
        return [p for p in items if x1 <= p["x"] <= x2 and y1 <= p["y"] <= y2]

    @staticmethod
    def _region_circles(items, x1, x2, y1, y2):
        return [p for p in items if x1 <= p[0] <= x2 and y1 <= p[1] <= y2]

    @staticmethod
    def _grid_from_data(blobs, circles, height):
        # Hudud chegaralari width=900 resize uchun.
        left_blobs = OMRProcessor._region_points(blobs, 170, 360, int(height * 0.19), int(height * 0.78))
        right_blobs = OMRProcessor._region_points(blobs, 470, 670, int(height * 0.185), int(height * 0.73))
        bottom_blobs = OMRProcessor._region_points(blobs, 470, 760, int(height * 0.72), int(height * 0.91))

        left_circles = OMRProcessor._region_circles(circles, 170, 360, int(height * 0.19), int(height * 0.78))
        right_circles = OMRProcessor._region_circles(circles, 470, 670, int(height * 0.185), int(height * 0.73))
        bottom_circles = OMRProcessor._region_circles(circles, 470, 760, int(height * 0.72), int(height * 0.91))

        def get_x(bl, hc, k, fallback_start, fallback_step):
            xs = [p["x"] for p in bl] + [p[0] for p in hc]
            try:
                c = OMRProcessor._cluster_1d(xs, k)
                if np.median(np.diff(c)) > 12:
                    return c, True
            except Exception:
                pass
            return [fallback_start + i * fallback_step for i in range(k)], False

        lx, lx_ok = get_x(left_blobs, left_circles, 4, 190, 32)
        rx, rx_ok = get_x(right_blobs, right_circles, 4, 505, 34)
        bx, bx_ok = get_x(bottom_blobs, bottom_circles, 6, 505, 36)

        # Y ni asosan bo'yalgan nuqtalardan olamiz. Hough'dagi matn va raqamlar y ni buzmasin.
        # Shuning uchun Hough doiralarini faqat variant ustunlariga yaqin bo'lganlarini olamiz.
        left_cy = [p[1] for p in left_circles if min(abs(p[0] - x) for x in lx) < 13]
        right_cy = [p[1] for p in right_circles if min(abs(p[0] - x) for x in rx) < 13]
        bottom_cy = [p[1] for p in bottom_circles if min(abs(p[0] - x) for x in bx) < 13]
        ly, ly_ok = OMRProcessor._regular_centers_from_marks([p["y"] for p in left_blobs] + left_cy, 18, int(height * 0.208), 37)
        ry, ry_ok = OMRProcessor._regular_centers_from_marks([p["y"] for p in right_blobs] + right_cy, 14, int(height * 0.198), 37)
        by, by_ok = OMRProcessor._regular_centers_from_marks([p["y"] for p in bottom_blobs] + bottom_cy, 3, int(height * 0.745), 37)

        grid = {}
        for row in range(18):
            grid[row + 1] = [(OMRProcessor.OPTIONS4[i], lx[i], ly[row]) for i in range(4)]
        for row in range(14):
            grid[row + 19] = [(OMRProcessor.OPTIONS4[i], rx[i], ry[row]) for i in range(4)]
        for row in range(3):
            grid[row + 33] = [(OMRProcessor.OPTIONS6[i], bx[i], by[row]) for i in range(6)]

        method = (
            f"filled_blob_cluster "
            f"L:{len(left_blobs)}/C{len(left_circles)}({'ok' if lx_ok and ly_ok else 'partial'}) "
            f"R:{len(right_blobs)}/C{len(right_circles)}({'ok' if rx_ok and ry_ok else 'partial'}) "
            f"B:{len(bottom_blobs)}/C{len(bottom_circles)}({'ok' if bx_ok and by_ok else 'partial'})"
        )
        return grid, method

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
    def _assign_marks_to_question(q, centers, blobs):
        # Tolerances: kamera biroz qiyshayganda ham shu radius ichidagi mark olinadi.
        row_tol = 17
        col_tol = 18
        marked = []
        for opt, cx, cy in centers:
            candidates = []
            for b in blobs:
                dx = abs(b["x"] - cx)
                dy = abs(b["y"] - cy)
                if dx <= col_tol and dy <= row_tol:
                    dist = (dx * dx + dy * dy) ** 0.5
                    candidates.append((dist, b))
            if candidates:
                candidates.sort(key=lambda t: t[0])
                best = candidates[0][1]
                marked.append((opt, best["x"], best["y"], best["area"]))
        # Bir xil blob 2 ta optionga tushib qolmasin: eng yaqinini qoldirish.
        unique = []
        used = []
        for item in marked:
            opt, x, y, area = item
            key = (round(x), round(y))
            if key not in used:
                used.append(key)
                unique.append(item)
        return unique

    @staticmethod
    def analyze_sheet(image_bytes, answer_key_dict):
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Rasm ochilmadi. Iltimos, JPG/PNG rasm yuboring.")

        work = OMRProcessor._resize_keep_aspect(img)
        blobs, mask = OMRProcessor._detect_filled_blobs(work)
        circles = OMRProcessor._detect_hough_circles(work)
        grid, align_method = OMRProcessor._grid_from_data(blobs, circles, work.shape[0])
        key = OMRProcessor._parse_key(answer_key_dict)

        correct = wrong = skipped = invalid = 0
        questions = []
        vis = work.copy()

        for q in range(1, 36):
            centers = grid[q]
            answer = key.get(q, "-")
            marked = OMRProcessor._assign_marks_to_question(q, centers, blobs)

            if len(marked) == 0:
                student = "BO'SH"
                status = "skipped"
                skipped += 1
                color = (150, 150, 150)
            elif len(marked) > 1:
                student = ",".join(m[0] for m in marked)
                status = "invalid"
                invalid += 1
                wrong += 1
                color = (0, 0, 255)
            else:
                student = marked[0][0]
                if student == answer:
                    status = "correct"
                    correct += 1
                    color = (0, 175, 0)
                else:
                    status = "wrong"
                    wrong += 1
                    color = (0, 0, 255)

            # Vizual: kulrang grid, ko'k kalit, yashil/qizil belgilangan javob.
            for opt, cx, cy in centers:
                cv2.circle(vis, (int(round(cx)), int(round(cy))), 11, (190, 190, 190), 1)
            for opt, cx, cy in centers:
                if opt == answer:
                    cv2.circle(vis, (int(round(cx)), int(round(cy))), 15, (255, 170, 0), 2)
            for opt, x, y, area in marked:
                cv2.circle(vis, (int(round(x)), int(round(y))), 18, color, 3)

            first_x, first_y = centers[0][1], centers[0][2]
            cv2.putText(vis, str(q), (int(first_x) - 52, int(first_y) + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 2)

            questions.append({
                "num": q,
                "key": answer,
                "student": student,
                "status": status,
                "scores": {m[0]: round(float(m[3]), 1) for m in marked},
                "align_method": align_method,
            })

        total = 35
        percentage = round(correct / total * 100, 2)
        total_score = correct

        cv2.rectangle(vis, (18, 14), (min(880, vis.shape[1] - 18), 104), (255, 255, 255), -1)
        cv2.putText(vis, f"Natija: {correct}/{total}  Foiz: {percentage}%", (36, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (0, 0, 0), 2)
        cv2.putText(vis, f"Xato: {wrong} | Bo'sh: {skipped} | 2 ta belgi: {invalid}", (36, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2)
        cv2.putText(vis, f"Align: {align_method}", (36, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (80, 80, 80), 1)

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
