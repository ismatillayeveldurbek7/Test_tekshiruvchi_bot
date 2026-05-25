import cv2
import numpy as np

class OMRProcessor:
    @staticmethod
    def _order_points(pts):
        pts = np.array(pts, dtype="float32")
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    @staticmethod
    def get_perspective_transform(image, corners):
        pts = OMRProcessor._order_points(corners)
        (tl, tr, br, bl) = pts
        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_width = max(int(width_a), int(width_b), 600)
        max_height = max(int(height_a), int(height_b), 1000)
        dst = np.array([[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]], dtype="float32")
        M = cv2.getPerspectiveTransform(pts, dst)
        return cv2.warpPerspective(image, M, (max_width, max_height))

    @staticmethod
    def find_sheet_corners(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 50, 180)
        contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        img_area = image.shape[0] * image.shape[1]
        for c in contours[:10]:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            area = cv2.contourArea(approx)
            if len(approx) == 4 and area > img_area * 0.20:
                return approx.reshape(4, 2)
        h, w = image.shape[:2]
        return np.array([[w*0.04, h*0.04], [w*0.96, h*0.04], [w*0.96, h*0.96], [w*0.04, h*0.96]], dtype="float32")

    @staticmethod
    def analyze_sheet(image_bytes, answer_key_dict):
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Rasm fayli ochilmadi.")

        corners = OMRProcessor.find_sheet_corners(img)
        warped = OMRProcessor.get_perspective_transform(img, corners)
        warped_std = cv2.resize(warped, (600, 1000))
        gray = cv2.cvtColor(warped_std, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]

        options = ["A", "B", "C", "D", "E"]
        total_questions = len(answer_key_dict) if answer_key_dict else 35
        total_questions = min(max(total_questions, 1), 35)
        visualization_sheet = warped_std.copy()

        # Standart 35 talik blank: 1-18 chap ustun, 19-35 o‘ng ustun.
        row_height = 42
        y_start = 120
        option_spacing = 38
        bubble_radius = 8  # ichki qism; eski 12 radius bo‘sh doira chizig‘ini ham to‘ldirilgan deb olardi

        score_correct = score_wrong = score_skipped = score_invalid = 0
        q_results = []

        for q_idx in range(1, total_questions + 1):
            is_col2 = q_idx > 18
            col_x_offset = 320 if is_col2 else 40
            relative_num = q_idx - 18 if is_col2 else q_idx
            y_coord = y_start + (relative_num - 1) * row_height

            bubble_scores = []
            for opt_idx, opt in enumerate(options):
                cx = col_x_offset + 85 + (opt_idx * option_spacing)
                cy = y_coord + 20
                mask = np.zeros(thresh.shape, dtype="uint8")
                cv2.circle(mask, (cx, cy), bubble_radius, 255, -1)
                pixels = cv2.countNonZero(cv2.bitwise_and(thresh, thresh, mask=mask))
                bubble_scores.append((opt, (cx, cy), pixels))

            max_score = max(s for _, _, s in bubble_scores)
            # Adaptiv chegara: varaqadagi doira chizig‘i emas, haqiqiy bo‘yalgan joy tanlanadi.
            fill_threshold = max(45, max_score * 0.55)
            filled = [(opt, pos, score) for opt, pos, score in bubble_scores if score >= fill_threshold]
            # Juda sust belgilarni bo‘sh deb olish
            if max_score < 55:
                filled = []

            answer_key = answer_key_dict.get(str(q_idx), "EMPTY")
            if len(filled) == 0:
                student_ans = "BO‘SH"
                status = "skipped"
                score_skipped += 1
                cv2.line(visualization_sheet, (col_x_offset + 50, y_coord + 20), (col_x_offset + 250, y_coord + 20), (120, 120, 120), 1)
            elif len(filled) > 1:
                student_ans = ",".join([f[0] for f in filled])
                status = "invalid"
                score_invalid += 1
                score_wrong += 1
                cv2.rectangle(visualization_sheet, (col_x_offset + 10, y_coord + 3), (col_x_offset + 265, y_coord + 35), (0, 0, 255), 2)
                for _, pos, _ in filled:
                    cv2.circle(visualization_sheet, pos, 14, (0, 0, 255), 2)
            else:
                student_ans = filled[0][0]
                bx, by = filled[0][1]
                if student_ans == answer_key:
                    status = "correct"
                    score_correct += 1
                    cv2.circle(visualization_sheet, (bx, by), 14, (0, 255, 0), 2)
                else:
                    status = "wrong"
                    score_wrong += 1
                    cv2.circle(visualization_sheet, (bx, by), 14, (0, 0, 255), 2)
                    if answer_key in options:
                        corr_opt_idx = options.index(answer_key)
                        ccx = col_x_offset + 85 + (corr_opt_idx * option_spacing)
                        ccy = y_coord + 20
                        cv2.circle(visualization_sheet, (ccx, ccy), 14, (255, 0, 0), 2)

            text_color = (0, 180, 0) if status == "correct" else (0, 0, 255) if status in {"wrong", "invalid"} else (130, 130, 130)
            cv2.putText(visualization_sheet, f"{q_idx:02d}.", (col_x_offset + 10, y_coord + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 2)
            q_results.append({"num": q_idx, "key": answer_key, "student": student_ans, "status": status})

        cv2.rectangle(visualization_sheet, (25, 15), (575, 78), (25, 25, 25), -1)
        cv2.putText(visualization_sheet, f"NATIJA: {score_correct}/{total_questions}", (45, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.putText(visualization_sheet, f"XATO: {score_wrong} | BOSH: {score_skipped} | 2TA+: {score_invalid}", (45, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)

        success, encoded_img = cv2.imencode('.png', visualization_sheet)
        if not success:
            raise RuntimeError("Natija rasmini yaratib bo‘lmadi.")
        percentage = round((score_correct / total_questions) * 100, 2)
        return {
            "correct_count": score_correct,
            "wrong_count": score_wrong,
            "skipped_count": score_skipped,
            "invalid_count": score_invalid,
            "total_score": score_correct,
            "percentage": percentage,
            "total_questions": total_questions,
            "questions": q_results,
            "visual_png": encoded_img.tobytes(),
        }
