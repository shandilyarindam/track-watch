RECOVERY_MODE = False
RECOVERY_FREEZE = 4
recovery_counter = 0

import warnings
warnings.filterwarnings("ignore")
import joblib
import numpy as np
from collections import deque
import time

bundle = joblib.load("trained_model.pkl")
iforest = bundle["iforest"]
lof = bundle["lof"]
scaler = bundle["scaler"]
features_list = bundle.get("features", None)
print("LOADED FEATURES LIST:", features_list)

WINDOW_SIZE = 10
MIN_WARMUP = 3
COOLDOWN_COUNT = 6
window = deque(maxlen=WINDOW_SIZE)
last_state = "NORMAL"
normal_counter = 0


def extract_features(win):
    arr = np.array(win)
    distance = arr[:, 0]
    flex = arr[:, 1]
    temperature = arr[:, 2]
    pir = arr[:, 3]
    feat = np.array([[
        flex.mean(),
        flex.std(),
        flex[-1] - flex[0],
        distance.mean(),
        np.abs(np.diff(distance)).mean() if len(distance) > 1 else 0,
        pir.mean(),
        temperature[-1] - temperature[0]
    ]])
    return feat

def classify_window_and_debug():
    feat = extract_features(window)
    try:
        feat_scaled = scaler.transform(feat)
    except Exception as e:
        print("Scaler transform error:", e)
        feat_scaled = feat.copy()

    iso_score = float(iforest.decision_function(feat_scaled)[0])
    lof_score = float(lof.decision_function(feat_scaled)[0])

    try:
        if_pred = int(iforest.predict(feat_scaled)[0])
    except Exception:
        if_pred = None
    try:
        lof_pred = int(lof.predict(feat_scaled)[0])
    except Exception:
        lof_pred = None

    combined = 0.6 * iso_score + 0.4 * lof_score

    if combined < -0.45:
        state = "HIGH"
    elif combined < -0.25:
        state = "MEDIUM"
    elif combined < -0.10:
        state = "LOW"
    else:
        state = "NORMAL"

    return state, iso_score, lof_score, combined, if_pred, lof_pred, feat.flatten(), feat_scaled.flatten()

def detect_and_print(distance, flex, temperature, pir, step):
    global last_state, normal_counter, RECOVERY_MODE, recovery_counter
    window.append([distance, flex, temperature, pir])

    if len(window) < MIN_WARMUP:
        print(f"{step:02d} | WARMING_UP  | window_len={len(window)}")
        return

    state, iso_score, lof_score, combined, if_pred, lof_pred, feat, feat_scaled = classify_window_and_debug()

    if last_state == "HIGH":
        if state == "NORMAL" and not RECOVERY_MODE:
            RECOVERY_MODE = True
            recovery_counter = 0

        if RECOVERY_MODE:
            recovery_counter += 1
            display_state = "HIGH"
            if recovery_counter >= RECOVERY_FREEZE:
                RECOVERY_MODE = False
                normal_counter = 1
                display_state = "NORMAL"
        else:
            display_state = "HIGH"
    else:
        display_state = state
        if state == "HIGH":
            normal_counter = 0
            RECOVERY_MODE = False

    last_state = display_state

    print(f"{step:02d} | {display_state:6} | combined={combined: .3f} | iso={iso_score: .3f} lof={lof_score: .3f} | if_pred={if_pred} lof_pred={lof_pred}")
    print(f"     RAW_FEAT   : {np.round(feat,3)}")
    print(f"     SCALED_FEAT: {np.round(feat_scaled,3)}")
    print(f"     WINDOW_LAST(3): {list(window)[-3:]}")


if __name__ == "__main__":
    print("\nDEBUG RUN: 0..24 NORMAL, 25..54 TAMPER, 55..84 RECOVER\n")
    for i in range(85):
        if i < 25:
            flex = 606 + np.random.normal(0, 0.5)
            pir = 0
            distance = 42 + np.random.normal(0,0.2)
            temp = 31 + np.random.normal(0,0.2)
        elif i < 55:
            flex = 630 + np.random.normal(0, 1.0)
            pir = 1
            distance = 35 + np.random.normal(0,0.5)
            temp = 33 + np.random.normal(0,0.3)
        else:
            flex = 606 + np.random.normal(0, 0.5)
            pir = 0
            distance = 42 + np.random.normal(0,0.2)
            temp = 31 + np.random.normal(0,0.2)

        detect_and_print(distance=distance, flex=flex, temperature=temp, pir=pir, step=i)
        time.sleep(0.05)

    print("\nDEBUG RUN END\n")
