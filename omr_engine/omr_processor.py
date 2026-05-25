import cv2
import numpy as np


class OMRProcessor:
    """Akbarali Boymirzayev namunasi: 1-32 A/B/C/D, 33-35 A/B/C/D/E/F."""

    W, H = 900, 1600
    OPTIONS4 = ["A", "B", "C", "D"]
    OPTIONS6 = ["A", "B", "C", "D", "E", "F"]

    # Normalized coordinates based on this exact blank layout.
    LEFT_X = [0.193, 0.229, 0.266, 0.301]
    RIGHT_X = [0.558, 0.593, 0.628, 0.665]
    RIGHT6_X = [0.565, 0.602, 0.639, 0.676, 0.713, 0.749]
    Y_TOP = 0.207
    Y_STEP = 0.0252
    Y_33 = 0.579
    Y_33_STEP = 0.0257

    @staticmethod
    def _order_points(pts):
        pts = np.array(pts, dtype="float32")
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        return np.array([
            pts[np.argmin(s)],       # top-left
            pts[np.argmin(diff)],    # top-right
            pts[np.argmax(s)],       # bottom-right
            pts[np.argmax(diff)]     # bottom-left
        ], dtype="float32")

    @staticmethod
    def _find_paper(image):
        """Try to find paper border. If it fails, use whole image with safe margins."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 40, 140)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        img_area = image.shape[0] * image.shape[1]

        for c in contours[:10]:
            area = cv2.contourArea(c)
            if area < img_area * 0.20:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.025 * peri, True)
            if len(approx) == 4:
                return OMRProcessor._order_points(approx.reshape(4, 2))

        h, w = image.shape[:2]
        return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")

    @staticmethod
    def _warp(image):
        pts = OMRProcessor._find_paper(image)
        dst = np.array([[0, 0], [OMRProcessor.W - 1, 0], [OMRProcessor.W - 1, OMRProcessor.H - 1], [0, OMRProcessor.H - 1]], dtype="float32")
        m = cv2.getPerspectiveTransform(pts, dst)
        return cv2.warpPerspective(image, m, (OMRProcessor.W, OMRProcessor.H))

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
    def _fill_ratio(gray, cx, cy, radius=14):
        h, w = gray.shape
        x1, x2 = max(0, cx - radius), min(w, cx + radius + 1)
        y1, y2 = max(0, cy - radius), min(h, cy + radius + 1)
        roi = gray[y1:y2, x1:x2]
        if roi.size == 0:
            return 0.0

        # Circle mask: only inner bubble area is checked, not outside text/line.
        mask = np.zeros(roi.shape, dtype=np.uint8)
        cv2.circle(mask, (min(radius, roi.shape[1] - 1), min(radius, roi.shape[0] - 1)), max(3, radius - 2), 255, -1)

        # Filled dark ink is counted. Empty printed circles stay very low.
        dark = cv2.inRange(roi, 0, 105)
        dark = cv2.bitwise_and(dark, dark, mask=mask)
        return float(np.count_nonzero(dark)) / max(1, np.count_nonzero(mask))

    @staticmethod
    def _parse_key(answer_key_dict):
        clean = {}
        for k, v in answer_key_dict.items():
            try:
                q = int(k)
            except Exception:
                continue
            ans = str(v).strip().upper()
            if q <= 32 and ans in OMRProcessor.OPTIONS4:
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

        warped = OMRProcessor._warp(img)
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        key = OMRProcessor._parse_key(answer_key_dict)

        correct = wrong = skipped = invalid = 0
        questions = []
        vis = warped.copy()

        FILL_THRESHOLD = 0.07       # black ballpoint fill on your sample is about 0.17-0.25
        DOUBLE_MARGIN = 0.06        # prevents empty circle outlines from being counted

        for q in range(1, 36):
            centers = OMRProcessor._bubble_centers(q)
            ratios = []
            for opt, cx, cy in centers:
                ratio = OMRProcessor._fill_ratio(gray, cx, cy)
                ratios.append((opt, cx, cy, ratio))

            marked = [(o, x, y, r) for o, x, y, r in ratios if r >= FILL_THRESHOLD]
            # Extra safety: if one is clearly highest and others are only weak shadows, keep one.
            if len(marked) > 1:
                marked_sorted = sorted(marked, key=lambda t: t[3], reverse=True)
                if marked_sorted[0][3] - marked_sorted[1][3] >= DOUBLE_MARGIN:
                    marked = [marked_sorted[0]]

            answer = key.get(q, "-")
            if not marked:
                student = "BO'SH"
                status = "skipped"
                skipped += 1
                color = (160, 160, 160)
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
                    color = (0, 180, 0)
                else:
                    status = "wrong"
                    wrong += 1
                    color = (0, 0, 255)

            # draw all bubbles lightly + selected ones strongly
            for opt, cx, cy, ratio in ratios:
                cv2.circle(vis, (cx, cy), 15, (180, 180, 180), 1)
                if opt == answer:
                    cv2.circle(vis, (cx, cy), 18, (255, 170, 0), 2)  # correct answer hint
            for opt, cx, cy, ratio in marked:
                cv2.circle(vis, (cx, cy), 20, color, 3)

            # mark row status near first bubble
            first_x, first_y = centers[0][1], centers[0][2]
            cv2.putText(vis, f"{q}", (first_x - 55, first_y + 7), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            questions.append({
                "num": q,
                "key": answer,
                "student": student,
                "status": status,
                "ratios": {o: round(r, 3) for o, _, _, r in ratios}
            })

        total = 35
        percentage = round(correct / total * 100, 2)
        total_score = correct  # one correct = 1 point. Change here if needed.

        cv2.rectangle(vis, (30, 18), (870, 90), (255, 255, 255), -1)
        cv2.putText(vis, f"Natija: {correct}/{total}  Foiz: {percentage}%", (45, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        cv2.putText(vis, f"Xato: {wrong} | Bo'sh: {skipped} | 2 ta belgi: {invalid}", (45, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

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
            "visual_png": encoded.tobytes()
        }
