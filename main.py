import cv2
import mediapipe as mp
import time
from collections import deque
import numpy as np  # Used for array and numerical operations where needed.

# ---------- Configuration ----------
UNDEFINED_HOLD_TIME = 2.0
HOLD_TIME = 0.48
HOLD_TIME_ZERO = 1
NEUTRAL_HOLD_TIME = 0.1
CAM_ID = 0

mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_styles = mp.solutions.drawing_styles

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.5
)

# ---------- Hand and Finger-State Estimation ----------

# MediaPipe landmark indices for fingertip points.
TIP_IDS = [4, 8, 12, 16, 20]
# PIP-joint indices for index, middle, ring, and pinky fingers.
PIP_IDS = [6, 10, 14, 18]  # Index, Middle, Ring, Pinky.
# Landmark index for the thumb IP joint.
THUMB_IP_ID = 3

# MCP landmarks used to estimate palm orientation.
THUMB_MCP_ID = 2
PINKY_MCP_ID = 17


def get_distance(p1, p2):
    """Return the Euclidean distance between two hand landmarks."""
    return ((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2 + (p1.z - p2.z) ** 2) ** 0.5


def is_palm_facing_camera_robust(hand_landmarks, handedness_str):
    """Estimate whether the visible hand surface is palm-facing the camera.

    The estimate uses the relative x-positions of the thumb and pinky MCP
    landmarks together with MediaPipe's handedness label.
    """
    if not handedness_str:  # Fall back to palm-facing when handedness is unavailable.
        return True

    landmarks = hand_landmarks.landmark
    thumb_mcp_x = landmarks[THUMB_MCP_ID].x
    pinky_mcp_x = landmarks[PINKY_MCP_ID].x

    if handedness_str == "Right":
        return thumb_mcp_x < pinky_mcp_x  # Right hand: thumb is left of the pinky MCP in the palm view.
    elif handedness_str == "Left":
        return thumb_mcp_x > pinky_mcp_x  # Left hand: thumb is right of the pinky MCP in the palm view.

    return True  # Conservative fallback for an unexpected handedness label.


def fingers_up_final_hybrid(hand_landmarks, handedness_str):
    """Estimate the number of raised fingers using complementary heuristics.

    The four non-thumb fingers are evaluated by their distance from the wrist,
    while the thumb uses handedness and palm orientation to choose the
    appropriate x-coordinate comparison.
    """
    landmarks = hand_landmarks.landmark
    fingers = []

    # Estimate palm orientation before evaluating the thumb.
    palm_facing = is_palm_facing_camera_robust(hand_landmarks, handedness_str)

    # The thumb requires a handedness- and orientation-aware comparison.
    thumb_tip = landmarks[TIP_IDS[0]]  # Landmark 4: thumb tip.
    thumb_ip = landmarks[THUMB_IP_ID]  # Landmark 3: thumb IP joint.
    thumb_is_open = False

    if handedness_str == "Right":
        if palm_facing:
            thumb_is_open = thumb_tip.x < thumb_ip.x
        else:  # Back of the hand: reverse the comparison.
            thumb_is_open = thumb_tip.x > thumb_ip.x
    elif handedness_str == "Left":
        if palm_facing:
            thumb_is_open = thumb_tip.x > thumb_ip.x
        else:  # Back of the hand: reverse the comparison.
            thumb_is_open = thumb_tip.x < thumb_ip.x
    else:
        # If handedness is unavailable, use a simple vertical thumb heuristic.
        thumb_is_open = thumb_tip.y < landmarks[2].y

    fingers.append(1 if thumb_is_open else 0)

    # Evaluate the remaining four fingers using wrist-relative distances.
    # Comparing distances reduces sensitivity to in-plane hand rotation.
    wrist = landmarks[0]
    for tip_id, pip_id in zip(TIP_IDS[1:], PIP_IDS):
        tip = landmarks[tip_id]
        pip = landmarks[pip_id]

        dist_tip_wrist = get_distance(tip, wrist)
        dist_pip_wrist = get_distance(pip, wrist)

        is_open = dist_tip_wrist > dist_pip_wrist
        fingers.append(1 if is_open else 0)

    return sum(fingers), fingers


def is_hand_fist(count):
    return count == 0


def is_hand_open(count):
    return count == 5


# ---------- Interaction State Machine ----------
STATE_IDLE = "IDLE"
STATE_POSITIVE = "POSITIVE_LISTEN"
STATE_NEGATIVE = "NEGATIVE_LISTEN"

state = STATE_IDLE
current_digits = []
current_mode = None
last_gesture = None
gesture_start_time = None
neutral_start_time = None
need_reset = False
ignore_gesture = None
gesture_history = deque(maxlen=5)


# Reset the interaction state and temporal gesture history.
def reset_all(reason=""):
    global state, current_digits, current_mode, last_gesture, gesture_start_time
    print(f"[RESET] علت: {reason}")
    state = STATE_IDLE
    current_digits = []
    current_mode = None
    last_gesture = None
    gesture_start_time = None
    gesture_history.clear()


# ---------- Frame-Level Gesture Interpretation ----------
def interpret_gesture(results, frame_w, frame_h):
    """Map detected hand landmarks to the gesture vocabulary used by the state machine."""
    if not results.multi_hand_landmarks:
        return "no_hand", {}

    hands_lm = results.multi_hand_landmarks
    handedness_labels = []
    if results.multi_handedness:
        for hd in results.multi_handedness:
            handedness_labels.append(hd.classification[0].label)  # MediaPipe handedness label.

    per_hand_counts = []
    fist_votes = []
    for i, hl in enumerate(hands_lm):
        label = handedness_labels[i] if i < len(handedness_labels) else None

        # Estimate the finger count with the hybrid landmark heuristic.
        cnt, fingers_list = fingers_up_final_hybrid(hl, handedness_str=label)
        per_hand_counts.append(cnt)

        # Additional heuristic for cases where a closed hand is not cleanly classified.
        # Keep the geometric checks as a secondary fist cue.
        is_fist = (cnt == 0)

        if not is_fist:
            closed_cnt = sum(1 for f in fingers_list[1:] if f == 0)  # Avoid another y-coordinate threshold.

            wrist = hl.landmark[0]
            thumb_tip = hl.landmark[TIP_IDS[0]]
            index_mcp = hl.landmark[5]
            palm_size = ((wrist.x - index_mcp.x) ** 2 + (wrist.y - index_mcp.y) ** 2) ** 0.5 + 1e-6
            thumb_dist = ((thumb_tip.x - wrist.x) ** 2 + (thumb_tip.y - wrist.y) ** 2) ** 0.5
            thumb_tucked = (thumb_dist < 0.7 * palm_size)

            is_fist = (cnt == 0) or (closed_cnt >= 4 and thumb_tucked) or thumb_tucked

        fist_votes.append(is_fist)
        # End of the secondary fist heuristic.

    total = sum(per_hand_counts)

    if len(hands_lm) == 2:
        if (per_hand_counts[0] == 5 and per_hand_counts[1] == 5):
            return "both_open", {"per": per_hand_counts, "total": total}
        if (fist_votes[0] and fist_votes[1]):
            return "both_fist", {"per": per_hand_counts, "total": 0}
        if (per_hand_counts[0] == 0 and per_hand_counts[1] == 0):
            return "both_fist", {"per": per_hand_counts, "total": 0}
        if 6 <= total <= 9:
            return f"both_{total}", {"per": per_hand_counts, "total": total}
        if total == 10:
            return "both_open", {"per": per_hand_counts, "total": total}
        return "undefined", {"per": per_hand_counts, "total": total}

    elif len(hands_lm) == 1:
        cnt = per_hand_counts[0]
        if fist_votes[0]:
            return "single_0", {"per": per_hand_counts, "total": 0}
        if 0 <= cnt <= 5:
            return f"single_{cnt}", {"per": per_hand_counts, "total": cnt}
        else:
            return "undefined", {"per": per_hand_counts, "total": cnt}
    else:
        return "undefined", {}


# ---------- State Transitions and Hold-Time Processing ----------
def update_state_with_gesture(gesture, details, now_t):
    """Update the interaction state after temporal gesture filtering."""
    global state, current_mode, last_gesture, gesture_start_time, current_digits, neutral_start_time, need_reset, ignore_gesture

    if need_reset:
        if gesture == ignore_gesture:
            return
        elif gesture in (
                "no_hand", "undefined", "both_open", "both_fist", "single_0", "single_1", "single_2", "single_3",
                "single_4",
                "single_5", "both_6", "both_7", "both_8", "both_9", "no_hand"):
            if neutral_start_time is None:
                neutral_start_time = now_t
            elif now_t - neutral_start_time >= NEUTRAL_HOLD_TIME:
                need_reset = False
                ignore_gesture = None
                neutral_start_time = None
            return
        else:
            neutral_start_time = None

    if gesture == "undefined":
        if last_gesture != "undefined":
            last_gesture = "undefined"
            gesture_start_time = now_t
        elif now_t - gesture_start_time >= UNDEFINED_HOLD_TIME:
            reset_all("Undefined gesture detected")
        return

    if gesture == "no_hand":
        last_gesture = None
        gesture_start_time = None
        return

    if state == STATE_IDLE:
        if gesture == "both_open":
            if last_gesture != "both_open":
                last_gesture = "both_open"
                gesture_start_time = now_t
            elif now_t - gesture_start_time >= HOLD_TIME:
                state = STATE_POSITIVE
                current_mode = "positive"
                current_digits = []
                last_gesture = None
                gesture_start_time = None
                need_reset = True
                ignore_gesture = "both_open"
                print("[MODE] Entered POSITIVE listening mode.")
            return

        if gesture == "both_fist":
            if last_gesture != "both_fist":
                last_gesture = "both_fist"
                gesture_start_time = now_t
            elif now_t - gesture_start_time >= HOLD_TIME:
                state = STATE_NEGATIVE
                current_mode = "negative"
                current_digits = []
                last_gesture = None
                gesture_start_time = None
                need_reset = True
                ignore_gesture = "both_fist"
                print("[MODE] Entered NEGATIVE listening mode.")
            return
        return

    if state in (STATE_POSITIVE, STATE_NEGATIVE):
        if current_mode == "positive" and gesture == "both_open":
            if last_gesture != "both_open":
                last_gesture = "both_open"
                gesture_start_time = now_t
            elif now_t - gesture_start_time >= HOLD_TIME:
                final_floor_str = "".join(current_digits) if current_digits else "0"
                simulate_move(final_floor_str, sign=1)
                need_reset = True
                ignore_gesture = "both_open"
                reset_all("Finished positive floor")
            return

        if current_mode == "negative" and gesture == "both_fist":
            if last_gesture != "both_fist":
                last_gesture = "both_fist"
                gesture_start_time = now_t
            elif now_t - gesture_start_time >= HOLD_TIME:
                final_floor_str = "".join(current_digits) if current_digits else "0"
                simulate_move(final_floor_str, sign=-1)
                need_reset = True
                ignore_gesture = "both_fist"
                reset_all("Finished negative floor")
            return

        if gesture.startswith("single_"):
            digit = gesture.split("_")[1]
            hold_duration = HOLD_TIME_ZERO if digit == '0' else HOLD_TIME
            if last_gesture != gesture:
                last_gesture = gesture
                gesture_start_time = now_t
            elif now_t - gesture_start_time >= hold_duration:
                current_digits.append(digit)
                print(f"[DIGIT] Registered digit: {digit}   (digits so far: {''.join(current_digits)})")
                last_gesture = None
                gesture_start_time = None
                need_reset = True
                ignore_gesture = gesture
            return

        if gesture.startswith("both_"):
            try:
                total = int(gesture.split("_")[1])
            except:
                total = details.get("total", None)
            if total is not None and 6 <= total <= 9:
                if last_gesture != gesture:
                    last_gesture = gesture
                    gesture_start_time = now_t
                elif now_t - gesture_start_time >= HOLD_TIME:
                    current_digits.append(str(total))
                    print(
                        f"[DIGIT] Registered digit (both hands): {total}   (digits so far: {''.join(current_digits)})")
                    last_gesture = None
                    gesture_start_time = None
                    need_reset = True
                    ignore_gesture = gesture
                return

        invalid_hold = HOLD_TIME
        if state == STATE_POSITIVE and gesture == "both_fist":
            invalid_hold = 2.0
        if state == STATE_NEGATIVE and gesture == "both_open":
            invalid_hold = 2.0

        if last_gesture != gesture:
            last_gesture = gesture
            gesture_start_time = now_t
        elif now_t - gesture_start_time >= invalid_hold:
            reset_all("Gesture not allowed in listening mode")
        return


# ---------- Elevator Movement Simulation ----------
def simulate_move(floor_str, sign=1):
    """Print the requested floor; no physical elevator interface is used here."""
    try:
        floor_num = int(floor_str)
    except:
        print("[ERROR] Invalid floor string to simulate_move:", floor_str)
        return
    if sign < 0:
        print(f"=> Elevator will move to floor -{floor_num} (NEGATIVE).")
    else:
        print(f"=> Elevator will move to floor {floor_num} (POSITIVE).")


# ---------- Main Camera and Visualization Loop ----------
def main():
    """Run the webcam loop, gesture filtering, state updates, and visualization."""
    global gesture_history
    cap = cv2.VideoCapture(CAM_ID)
    if not cap.isOpened():
        print("Cannot open camera")
        return

    cv2.namedWindow("Elevator Gesture Control", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Elevator Gesture Control", 645, 454)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame.")
            break

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(frame_rgb)

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

        gesture, details = interpret_gesture(results, w, h)
        gesture_history.append(gesture)

        most_common = None
        if len(gesture_history) >= 3:
            freq = {}
            for g in gesture_history:
                freq[g] = freq.get(g, 0) + 1
            most_common = max(freq.items(), key=lambda x: x[1])[0]
        else:
            most_common = gesture

        now = time.time()
        update_state_with_gesture(most_common, details, now)

        mode_text = f"STATE: {state}"
        mode_text2 = f"MODE: {current_mode if current_mode else '-'}"
        digits_text = f"DIGITS: {''.join(current_digits) if current_digits else '(none)'}"
        gesture_text = f"GESTURE: {most_common}"
        info_lines = [mode_text, mode_text2, digits_text, gesture_text]
        y0 = 30
        for i, line in enumerate(info_lines):
            cv2.putText(frame, line, (10, y0 + i * 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.imshow("Elevator Gesture Control", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC exits the application.
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    print("Starting Elevator Gesture Control. Press ESC to exit.")
    main()