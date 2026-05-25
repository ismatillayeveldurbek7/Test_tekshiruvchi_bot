import cv2
import numpy as np


class OMRProcessor:
    """Oddiy va barqaror OMR tekshiruvchi.
    Standart varaq: 2 ustun, A/B/C/D/E doiralar.
    Savollar soni javob kalitidan olinadi, 35 ga majburiy emas.
    """

    @staticmethod
    def order_points(pts):
        pts = np.array(pts, dtype="float32")
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        return np.array([pts[np.argmin(s)], pts[np.argmin(diff)], pts[np.argmax(s)], pts[np.argmax(diff)]], dtype="float32")

    @staticmethod
    def find_sheet_corners(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 50, 180)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:8]
        h, w = image.shape[:2]
        for c in contours:
            area = cv2.contourArea(c)
            if area < w * h * 0.20:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4:
                return OMRProcessor.order_points(approx.reshape(4, 2))
        return np.array([[w*0.03, h*0.03], [w*0.97, h*0.03], [w*0.97, h*0.97], [w*0.03, h*0.97]], dtype="float32")

    @staticmethod
    def warp(image):
        pts = OMRProcessor.find_sheet_corners(image)
        dst = np.array([[0, 0], [699, 0], [699, 999], [0, 999]], dtype="float32")
        matrix = cv2.getPerspectiveTransform(pts, dst)
        return cv2.warpPerspective(image, matrix, (700, 1000))

    @staticmethod
    def _bubble_score(thresh, cx, cy, r=13):
        mask = np.zeros(thresh.shape, dtype="uint8")
        cv2.circle(mask, (int(cx), int(cy)), r, 255, -1)
        selected = cv2.bitwise_and(thresh, thresh, mask=mask)
        return int(cv2.countNonZero(selected))

    @staticmethod
    def analyze_sheet(image_bytes, answer_key_dict):
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Rasm o‘qilmadi. Iltimos, aniqroq rasm yuboring.")

        sheet = OMRProcessor.warp(image)
        gray = cv2.cvtColor(sheet, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

        options = ["A", "B", "C", "D", "E"]
        total_questions = len(answer_key_dict)
        col1_count = (total_questions + 1) // 2
        col2_count = total_questions - col1_count
        visual = sheet.copy()

        # Koordinatalar 700x1000 standart rasmga mos.
        # Agar varaq dizayni o‘zgarsa, faqat shu joydagi koordinatalar moslanadi.
        left_x = 55
        right_x = 385
        opt_start = 105
        opt_gap = 43
        y_top = 135
        y_bottom = 900
        row_gap1 = (y_bottom - y_top) / max(col1_count - 1, 1)
        row_gap2 = (y_bottom - y_top) / max(col2_count - 1, 1) if col2_count else row_gap1

        correct = wrong = skipped = invalid = 0
        questions = []

        for q in range(1, total_questions + 1):
            if q <= col1_count:
                base_x = left_x
                y = int(y_top + (q - 1) * row_gap1)
            else:
                base_x = right_x
                y = int(y_top + (q - col1_count - 1) * row_gap2)

            scores = []
            for i, opt in enumerate(options):
                cx = int(base_x + opt_start + i * opt_gap)
                score = OMRProcessor._bubble_score(thresh, cx, y)
                scores.append((opt, score, cx))

            values = [s for _, s, _ in scores]
            max_score = max(values)
            avg_score = float(np.mean(values))
            # Dinamik threshold: qalam izini emas, haqiqiy bo‘yalgan doirani tanlashga harakat qiladi.
            min_fill = max(85, avg_score * 1.55)
            marked = [(opt, sc, cx) for opt, sc, cx in scores if sc >= min_fill and sc >= max_score * 0.62]

            key = answer_key_dict.get(str(q), "")
            if len(marked) == 0:
                student = "-"
                status = "skipped"
                skipped += 1
                cv2.putText(visual, f"{q}", (base_x + 5, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (120,120,120), 2)
            elif len(marked) > 1:
                student = ",".join(m[0] for m in marked)
                status = "invalid"
                invalid += 1
                wrong += 1
                cv2.rectangle(visual, (base_x, y-20), (base_x+305, y+20), (0,0,255), 2)
                for _, _, cx in marked:
                    cv2.circle(visual, (cx, y), 17, (0,0,255), 2)
            else:
                student, _, cx = marked[0]
                if student == key:
                    status = "correct"
                    correct += 1
                    cv2.circle(visual, (cx, y), 17, (0,180,0), 3)
                else:
                    status = "wrong"
                    wrong += 1
                    cv2.circle(visual, (cx, y), 17, (0,0,255), 3)
                    if key in options:
                        kx = int(base_x + opt_start + options.index(key) * opt_gap)
                        cv2.circle(visual, (kx, y), 17, (255,0,0), 2)

            questions.append({"num": q, "key": key, "student": student, "status": status})

        pct = round((correct / total_questions) * 100, 2) if total_questions else 0
        cv2.rectangle(visual, (25, 15), (675, 75), (30, 30, 30), -1)
        cv2.putText(visual, f"Natija: {correct}/{total_questions}  Foiz: {pct}%", (45, 43), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255,255,255), 2)
        cv2.putText(visual, f"Xato: {wrong} | Bo'sh: {skipped} | 2ta belgi: {invalid}", (45, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255,255,255), 1)
        ok, encoded = cv2.imencode(".png", visual)
        if not ok:
            raise RuntimeError("Tekshirilgan rasmni yaratib bo‘lmadi.")
        return {
            "correct_count": correct,
            "wrong_count": wrong,
            "skipped_count": skipped,
            "invalid_count": invalid,
            "total_score": correct,
            "percentage": pct,
            "questions": questions,
            "visual_png": encoded.tobytes(),
        }
