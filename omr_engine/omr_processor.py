import os
import cv2
import numpy as np


class OMRProcessor:
    """Akbarali Boymirzayev blankasi uchun kuchaytirilgan OMR.

    Asosiy yangiliklar:
    - blank_template.png orqali ORB homography bilan align qilishga urinadi;
    - topilmasa, eski full-photo resize fallback ishlaydi;
    - har bir bubble atrofida lokal qidiruv qiladi (rasm siljisa ham markazni topadi);
    - markaziy qorayish foizi bilan tekshiradi (kontur/soya emas, bo'yalgan markaz);
    - 1-32 A/B/C/D, 33-35 A/B/C/D/E/F.
    """

    W, H = 900, 1600
    OPTIONS4 = ["A", "B", "C", "D"]
    OPTIONS6 = ["A", "B", "C", "D", "E", "F"]

    # Fallback normalized coordinates for the user's photo layout.
    LEFT_X = [0.193, 0.229, 0.266, 0.301]
    RIGHT_X = [0.558, 0.593, 0.628, 0.665]
    RIGHT6_X = [0.565, 0.602, 0.639, 0.676, 0.713, 0.749]
    Y_TOP = 0.207
    Y_STEP = 0.0252
    Y_33 = 0.579
    Y_33_STEP = 0.0257

    @staticmethod
    def _template_path():
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(os.path.dirname(here), "assets", "blank_template.png")

    @staticmethod
    def _order_points(pts):
        pts = np.array(pts, dtype="float32")
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        return np.array([
            pts[np.argmin(s)], pts[np.argmin(diff)], pts[np.argmax(s)], pts[np.argmax(diff)]
        ], dtype="float32")

    @staticmethod
    def _find_paper_by_edges(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 35, 120)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        img_area = image.shape[0] * image.shape[1]
        for c in contours[:20]:
            area = cv2.contourArea(c)
            if area < img_area * 0.18:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4:
                return OMRProcessor._order_points(approx.reshape(4, 2))
        return None

    @staticmethod
    def _align_with_template(image):
        """Align uploaded photo to blank_template if possible."""
        template_path = OMRProcessor._template_path()
        if not os.path.exists(template_path):
            return None, "no_template"

        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return None, "bad_template"

        # Resize target template to processor canvas for stable coordinates.
        template = cv2.resize(template, (OMRProcessor.W, OMRProcessor.H))
        img_small = cv2.resize(image, (OMRProcessor.W, OMRProcessor.H))

        g1 = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        orb = cv2.ORB_create(nfeatures=5000, scaleFactor=1.2, nlevels=8)
        kp1, des1 = orb.detectAndCompute(g1, None)
        kp2, des2 = orb.detectAndCompute(g2, None)
        if des1 is None or des2 is None or len(kp1) < 40 or len(kp2) < 40:
            return None, "few_features"

        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = matcher.match(des1, des2)
        matches = sorted(matches, key=lambda m: m.distance)[:350]
        if len(matches) < 35:
            return None, "few_matches"

        src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        Hm, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        if Hm is None or mask is None or int(mask.sum()) < 25:
            return None, "bad_homography"

        aligned = cv2.warpPerspective(img_small, Hm, (OMRProcessor.W, OMRProcessor.H), flags=cv2.INTER_LINEAR)
        return aligned, f"template_inliers:{int(mask.sum())}"

    @staticmethod
    def _fallback_warp(image):
        pts = OMRProcessor._find_paper_by_edges(image)
        if pts is not None:
            dst = np.array([[0, 0], [OMRProcessor.W - 1, 0], [OMRProcessor.W - 1, OMRProcessor.H - 1], [0, OMRProcessor.H - 1]], dtype="float32")
            m = cv2.getPerspectiveTransform(pts, dst)
            return cv2.warpPerspective(image, m, (OMRProcessor.W, OMRProcessor.H)), "paper_warp"
        return cv2.resize(image, (OMRProcessor.W, OMRProcessor.H)), "resize_fallback"

    @staticmethod
    def _prepare_image(image):
        aligned, method = OMRProcessor._align_with_template(image)
        if aligned is not None:
            return aligned, method
        return OMRProcessor._fallback_warp(image)

    @staticmethod
    def _bubble_centers(q):
        if 1 <= q <= 18:
            xs = OMRProcessor.LEFT_X
            y = OMRProcessor.Y_TOP + (q - 1) * OMRProcessor.Y_STEP
            opts = OMRProcessor.OPTIONS4
        elif 19 <= q <= 32:
            xs = OMRProcessor.RIGHT_X
            y = OMRProcessor.Y_TOP + (q - 19) * OMRProcessor.Y_STEP
            opts = OMRProcessor.OPTIONS4
        else:
            xs = OMRProcessor.RIGHT6_X
            y = OMRProcessor.Y_33 + (q - 33) * OMRProcessor.Y_33_STEP
            opts = OMRProcessor.OPTIONS6
        return [(opts[i], int(xs[i] * OMRProcessor.W), int(y * OMRProcessor.H)) for i in range(len(opts))]

    @staticmethod
    def _dark_mask(gray):
        # Adaptive + absolute dark mask. Blue/black penni ushlaydi, qizil/och konturlarni kamaytiradi.
        abs_dark = cv2.inRange(gray, 0, 125)
        adap = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY_INV, 31, 12)
        return cv2.bitwise_or(abs_dark, adap)

    @staticmethod
    def _ratio_at(dark, cx, cy, radius=10):
        h, w = dark.shape
        x1, x2 = max(0, cx - radius), min(w, cx + radius + 1)
        y1, y2 = max(0, cy - radius), min(h, cy + radius + 1)
        roi = dark[y1:y2, x1:x2]
        if roi.size == 0:
            return 0.0
        mask = np.zeros(roi.shape, dtype=np.uint8)
        ccx = cx - x1
        ccy = cy - y1
        cv2.circle(mask, (ccx, ccy), max(4, radius - 2), 255, -1)
        return float(np.count_nonzero(cv2.bitwise_and(roi, roi, mask=mask))) / max(1, np.count_nonzero(mask))

    @staticmethod
    def _best_local_score(dark, cx, cy):
        # Markaz biroz siljigan bo'lsa, atrofidan eng qoraygan markazni topadi.
        best_score = -1.0
        best_xy = (cx, cy)
        for dy in range(-14, 15, 2):
            for dx in range(-14, 15, 2):
                score = OMRProcessor._ratio_at(dark, cx + dx, cy + dy, radius=9)
                if score > best_score:
                    best_score = score
                    best_xy = (cx + dx, cy + dy)
        return best_score, best_xy

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
    def analyze_sheet(image_bytes, answer_key_dict):
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Rasm ochilmadi. Iltimos, JPG/PNG rasm yuboring.")

        aligned, align_method = OMRProcessor._prepare_image(img)
        gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        dark = OMRProcessor._dark_mask(gray)
        key = OMRProcessor._parse_key(answer_key_dict)

        correct = wrong = skipped = invalid = 0
        questions = []
        vis = aligned.copy()

        for q in range(1, 36):
            centers = OMRProcessor._bubble_centers(q)
            scores = []
            for opt, cx, cy in centers:
                score, (bx, by) = OMRProcessor._best_local_score(dark, cx, cy)
                scores.append((opt, bx, by, score))

            scores_sorted = sorted(scores, key=lambda t: t[3], reverse=True)
            max_score = scores_sorted[0][3]
            second_score = scores_sorted[1][3] if len(scores_sorted) > 1 else 0.0

            # Threshold dinamik: bo'yalgan markaz odatda 0.45+, bo'sh doira 0.05-0.20.
            # Juda yomon rasmda ham 0.30 dan pastini belgilangan deb olmaymiz.
            min_mark = 0.30
            close_ratio = 0.62
            answer = key.get(q, "-")

            if max_score < min_mark:
                student = "BO'SH"
                status = "skipped"
                skipped += 1
                color = (140, 140, 140)
                marked = []
            else:
                marked = [scores_sorted[0]]
                # 2 ta variant belgilangan: ikkinchi ham yetarlicha qoraygan va birinchiga yaqin.
                if second_score >= min_mark and second_score >= max_score * close_ratio:
                    marked.append(scores_sorted[1])
                    # Ba'zan 3+ belgi ham bo'lishi mumkin.
                    for extra in scores_sorted[2:]:
                        if extra[3] >= min_mark and extra[3] >= max_score * close_ratio:
                            marked.append(extra)

                if len(marked) > 1:
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
                        color = (0, 170, 0)
                    else:
                        status = "wrong"
                        wrong += 1
                        color = (0, 0, 255)

            for opt, cx, cy in [(o, x, y) for o, x, y in centers]:
                cv2.circle(vis, (cx, cy), 12, (190, 190, 190), 1)
            for opt, bx, by, score in scores:
                if opt == answer:
                    cv2.circle(vis, (bx, by), 16, (255, 160, 0), 2)
            for opt, bx, by, score in marked:
                cv2.circle(vis, (bx, by), 19, color, 3)

            first_x, first_y = centers[0][1], centers[0][2]
            cv2.putText(vis, str(q), (first_x - 60, first_y + 7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            questions.append({
                "num": q,
                "key": answer,
                "student": student,
                "status": status,
                "scores": {o: round(float(s), 3) for o, _, _, s in scores},
                "align_method": align_method,
            })

        total = 35
        percentage = round(correct / total * 100, 2)
        total_score = correct

        cv2.rectangle(vis, (22, 16), (878, 104), (255, 255, 255), -1)
        cv2.putText(vis, f"Natija: {correct}/{total}  Foiz: {percentage}%", (38, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (0, 0, 0), 2)
        cv2.putText(vis, f"Xato: {wrong} | Bo'sh: {skipped} | 2 ta belgi: {invalid}", (38, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2)
        cv2.putText(vis, f"Align: {align_method}", (38, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (80, 80, 80), 1)

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
