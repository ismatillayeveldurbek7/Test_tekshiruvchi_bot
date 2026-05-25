import cv2
import numpy as np
from PIL import Image
import io

class OMRProcessor:
    @staticmethod
    def get_perspective_transform(image, corners):
        """Applies perspective transformation to obtain a flat top-down OMR sheet."""
        # corners order: [top_left, top_right, bottom_right, bottom_left]
        pts = np.array(corners, dtype="float32")
        (tl, tr, br, bl) = pts
        
        # Calculate width & height of new image
        width_a = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        width_b = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        max_width = max(int(width_a), int(width_b))
        
        height_a = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        height_b = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        max_height = max(int(height_a), int(height_b))
        
        dst = np.array([
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1]
        ], dtype="float32")
        
        M = cv2.getPerspectiveTransform(pts, dst)
        warped = cv2.warpPerspective(image, M, (max_width, max_height))
        return warped

    @staticmethod
    def find_sheet_corners(image):
        """Detect the sheet's outer borders to extract perspective reference coordinates."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 50, 200)
        
        # Find contours
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        for c in contours:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            
            # If the contour has 4 points, we assume it's the sheet
            if len(approx) == 4:
                return approx.reshape(4, 2)
                
        # Return fallback grid corners based on image size if border contours aren't detected
        h, w = image.shape[:2]
        return np.array([[w*0.05, h*0.05], [w*0.95, h*0.05], [w*0.95, h*0.95], [w*0.05, h*0.95]])

    @staticmethod
    def analyze_sheet(image_bytes, answer_key_dict):
        """
        Main engine to detect bubbles, count scores and generate feedback layer.
        Supports up to 35 questions. 
        """
        # Load image via OpenCV
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Invalid image file uploaded.")
            
        h, w = img.shape[:2]
        
        # 1. Perspective alignment
        corners = OMRProcessor.find_sheet_corners(img)
        warped = OMRProcessor.get_perspective_transform(img, corners)
        
        # Resize warped image to standard size (e.g., 600 width, 1000 height)
        warped_std = cv2.resize(warped, (600, 1000))
        gray = cv2.cvtColor(warped_std, cv2.COLOR_BGR2GRAY)
        
        # 2. Adaptive thresholding to resolve camera shadow issues
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        
        # Predefined grid mapping for a typical 35-question grid
        # Options: A, B, C, D, E
        options = ["A", "B", "C", "D", "E"]
        num_questions = 35
        
        results_student = {}
        visualization_sheet = warped_std.copy()
        
        # Rows and options coordinates configuration (Adaptive coordinate grids)
        # 35 questions grid: structured in 2 columns to save height on OMR paper.
        # Col 1: Questions 1 to 18
        # Col 2: Questions 19 to 35
        # The coordinates below are mapped across standardized size (600px width x 1000px height)
        row_height = 42
        y_start_col1 = 120
        y_start_col2 = 120
        
        score_correct = 0
        score_wrong = 0
        score_skipped = 0
        score_invalid = 0
        
        q_results = []
        
        for q_idx in range(1, num_questions + 1):
            is_col2 = q_idx > 18
            col_x_offset = 320 if is_col2 else 40
            relative_num = q_idx - 18 if is_col2 else q_idx
            
            y_coord = (y_start_col1 if not is_col2 else y_start_col2) + (relative_num - 1) * row_height
            
            # Map of options columns relative positions
            option_spacing = 38
            bubble_radius = 12
            
            filled_bubbles = []
            
            # Calculate mean intensity of filled pixels in each bubble
            for opt_idx, opt in enumerate(options):
                cx = col_x_offset + 85 + (opt_idx * option_spacing)
                cy = y_coord + 20
                
                # Extract Bubble Region of interest
                mask = np.zeros(thresh.shape, dtype="uint8")
                cv2.circle(mask, (cx, cy), bubble_radius, 255, -1)
                mask = cv2.bitwise_and(thresh, thresh, mask=mask)
                total_pixels = np.sum(mask == 255)
                
                # Check pixel density
                if total_pixels > 210: # Threshold for filled bubble density
                    filled_bubbles.append((opt, (cx, cy)))
            
            # Validation rules comparison
            answer_key = answer_key_dict.get(str(q_idx), "EMPTY")
            
            if len(filled_bubbles) == 0:
                # Skipped
                student_ans = "EMPTY"
                status = "skipped"
                score_skipped += 1
                # Draw empty highlight in gray
                cv2.line(visualization_sheet, (col_x_offset + 50, y_coord + 20), (col_x_offset + 250, y_coord + 20), (120, 120, 120), 1)
            elif len(filled_bubbles) > 1:
                # Invalid multi-answers
                student_ans = ",".join([f[0] for f in filled_bubbles])
                status = "invalid"
                score_invalid += 1
                score_wrong += 1
                # Highlight in RED rectangle row alert
                cv2.rectangle(visualization_sheet, (col_x_offset + 10, y_coord + 3), (col_x_offset + 265, y_coord + 35), (0, 0, 255), 2)
                for f in filled_bubbles:
                    cv2.circle(visualization_sheet, f[1], bubble_radius + 4, (0, 0, 255), 2)
            else:
                # Single filled bubble
                student_ans = filled_bubbles[0][0]
                bx, by = filled_bubbles[0][1]
                
                if student_ans == answer_key:
                    status = "correct"
                    score_correct += 1
                    cv2.circle(visualization_sheet, (bx, by), bubble_radius + 4, (0, 255, 0), 2) # Highlight in Green
                else:
                    status = "wrong"
                    score_wrong += 1
                    cv2.circle(visualization_sheet, (bx, by), bubble_radius + 4, (0, 0, 255), 2) # Highlight Student selection in Red
                    # Point out actual correct layout if existing
                    if answer_key in options:
                        corr_opt_idx = options.index(answer_key)
                        ccx = col_x_offset + 85 + (corr_opt_idx * option_spacing)
                        ccy = y_coord + 20
                        cv2.circle(visualization_sheet, (ccx, ccy), bubble_radius + 4, (255, 0, 0), 1) # Yellow/Blue helper tip contour
            
            # Print row question markings on visualization
            text_color = (0, 255, 0) if status == "correct" else (0, 0, 255) if status == "invalid" else (0, 0, 250) if status == "wrong" else (150, 150, 150)
            cv2.putText(visualization_sheet, f"{q_idx:02d}.", (col_x_offset + 10, y_coord + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 2)
            
            q_results.append({
                "num": q_idx,
                "key": answer_key,
                "student": student_ans,
                "status": status
            })
            
        # Draw metadata header inside standard visual sheet
        cv2.rectangle(visualization_sheet, (30, 15), (570, 75), (20, 20, 20), -1)
        cv2.putText(visualization_sheet, f"OMR DETECTED SCORE: {score_correct}/{num_questions}", (50, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(visualization_sheet, f"ACCURACY: {int((score_correct/num_questions)*100)}% | SKIPPED: {score_skipped} | INVALID: {score_invalid}", (50, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
        
        # Convert processed visualization back to bytes
        success, encoded_img = cv2.imencode('.png', visualization_sheet)
        if not success:
            raise RuntimeError("Error generating visual processed PNG layer.")
            
        return {
            "correct_count": score_correct,
            "wrong_count": score_wrong,
            "skipped_count": score_skipped,
            "invalid_count": score_invalid,
            "total_score": score_correct * 4, # Weight is 4 points per correct answer
            "percentage": round((score_correct / num_questions) * 100, 2),
            "questions": q_results,
            "visual_png": encoded_img.tobytes()
        }
