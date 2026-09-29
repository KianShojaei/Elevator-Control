# Gesture-Based Elevator Control System for Real-Time Floor Selection

A real-time, touchless elevator floor-selection system based on hand landmarks, lightweight geometric heuristics, temporal smoothing, and a finite-state interaction model.

The implementation accompanies the paper **“Gesture-Based Elevator Control System for Real-Time Floor Selection”**, presented at the **10th International Congress on Fuzzy and Intelligent Systems (CFIS 2025)**.

**Paper DOI:** [10.1109/CFIS68949.2025.11652063](https://doi.org/10.1109/CFIS68949.2025.11652063)  
**Author:** Kian Shojaei  
**Supervisor / Co-author:** Elham Shabaninia

---

## Research Overview

The system provides a contactless method for selecting positive and negative elevator floors through hand gestures. It is designed around a lightweight, interpretable pipeline rather than a large end-to-end neural classifier.

The implementation combines:

- **MediaPipe Hands** for real-time 21-point hand landmark extraction
- **Handedness- and palm-orientation-aware thumb detection**
- **Hybrid finger-state heuristics** for the remaining fingers
- **Single- and two-hand gesture aggregation**
- **Short-term temporal smoothing** using a history buffer
- **Hold-time confirmation** to reduce transient detections
- **A finite-state machine** for positive/negative floor entry and command finalization
- A simulation layer that prints the selected floor instead of controlling physical elevator hardware

The complete system was evaluated in the accompanying paper on a custom dataset of **70 annotated videos recorded across four elevator environments**.

---

## System Pipeline

The runtime flow is:

`Camera → RGB conversion → MediaPipe Hands → Landmark analysis → Finger-state estimation → Gesture interpretation → Temporal smoothing → State machine → Floor selection`

![Processing pipeline](images/Pipeline_Sequence_Diagram.jpg)

The pipeline deliberately separates perception from interaction logic. This makes the system easier to inspect, tune, and extend toward a hardware interface.

---

## State Machine

The interaction is organized around three primary states:

- **IDLE** — waiting for a mode-selection gesture
- **POSITIVE_LISTEN** — collecting digits for a positive floor
- **NEGATIVE_LISTEN** — collecting digits for a negative floor

A sustained **both-open** gesture starts or finalizes positive-floor entry, while a sustained **both-fist** gesture starts or finalizes negative-floor entry.

![State machine](images/state_machine.png)

The implementation also uses neutral/debounce periods and gesture-specific hold times to reduce repeated registration of the same gesture.

---

## Gesture Vocabulary

The system supports:

| Gesture | Meaning |
|---|---|
| `both_open` | Start/finalize positive-floor input |
| `both_fist` | Start/finalize negative-floor input |
| `single_0` … `single_5` | Single-hand digits 0–5 |
| `both_6` … `both_9` | Two-hand digit encodings 6–9 |
| `undefined` | Ambiguous or unsupported configuration |
| `no_hand` | No hand detected |

Digits 6–9 are formed by aggregating the visible fingers across both detected hands. The implementation applies the same temporal confirmation logic to these gestures.

### Representative Gesture Frames

All gesture figures originally included with the project are retained and used below.

**Both hands open**

![Both hands open](images/both_open.png)

**Both hands in a fist**

![Both hands fist](images/both_fist.png)

**Undefined / ambiguous gesture**

![Undefined gesture](images/undefined.png)

**Digit 3**

![Digit 3](images/3.png)

**Digit 9**

![Digit 9](images/9.png)

---

## Implementation Details

### Hand Landmark Processing

For each detected hand, the implementation uses MediaPipe landmarks to estimate finger states.

The four non-thumb fingers are evaluated using a wrist-relative distance comparison:

`d(tip, wrist) > d(PIP, wrist)`

The thumb is handled separately because its motion is more sensitive to handedness and whether the palm or back of the hand faces the camera.

The implementation therefore combines:

1. MediaPipe handedness
2. Palm/back-of-hand orientation
3. Thumb tip and IP-joint relationships
4. Wrist-relative distances for the other fingers
5. A secondary fist heuristic based on closed fingers and thumb position

This keeps the recognition logic deterministic and directly inspectable.

### Temporal Filtering

The raw gesture prediction is stored in a short history buffer:

`deque(maxlen=5)`

Once enough observations are available, the most frequent gesture in the recent history is used as the current gesture token.

A candidate gesture must then remain stable for its corresponding hold interval before it is committed.

This two-stage filtering strategy separates:

- **frame-level recognition**, from
- **interaction-level confirmation**.

---

## Configuration

The current values in `main.py` are:

| Parameter | Value | Purpose |
|---|---:|---|
| `CAM_ID` | `0` | Default camera index |
| `UNDEFINED_HOLD_TIME` | `2.0` s | Confirmation period for undefined gestures |
| `HOLD_TIME` | `0.48` s | Default gesture confirmation time |
| `HOLD_TIME_ZERO` | `1.0` s | Longer confirmation for digit 0 |
| `NEUTRAL_HOLD_TIME` | `0.1` s | Neutral/debounce interval |
| `max_num_hands` | `2` | Maximum simultaneous hands |
| `min_detection_confidence` | `0.7` | MediaPipe detection threshold |
| `min_tracking_confidence` | `0.5` | MediaPipe tracking threshold |

These values are implementation parameters and can be adjusted for different camera positions, lighting conditions, and interaction requirements.

---

## Installation

Clone the repository and install the required Python packages:

```bash
pip install -r requirements.txt
```

The main dependencies are:

- Python
- OpenCV
- MediaPipe
- NumPy

---

## Running the System

Start the real-time webcam application with:

```bash
python main.py
```

The application:

1. Opens the configured camera.
2. Detects up to two hands.
3. Draws MediaPipe landmarks.
4. Estimates the current gesture.
5. Applies temporal smoothing.
6. Updates the interaction state.
7. Displays the current state, mode, registered digits, and gesture.

Press **Esc** to exit.

### Hardware Interface

The current `simulate_move()` function is intentionally a simulation layer. It reports the requested floor to the console and **does not send commands to a physical elevator**.

Any real hardware integration would require an independently engineered control interface, authentication, safety interlocks, fault handling, logging, and validation before deployment.

---

## Dataset

The project includes a small sample and documentation for the complete dataset.

- **70 videos** in the evaluation dataset
- **4 elevator environments**
- Positive and negative floor requests
- Single-, two-, and three-digit selections
- Gloved-hand samples
- Variation in elevator geometry and illumination

See [DataSet/README.md](DataSet/README.md) for sample-data access and the full-dataset information.

---

## Reported Evaluation

The following results are **reported in the accompanying paper** and are not presented as a new benchmark in this repository.

### Overall and condition-wise results

| Evaluation condition | Reported accuracy |
|---|---:|
| Positive-floor samples | 94.44% |
| Negative-floor samples | 88.23% |
| Glove samples | 85.71% |
| Overall | **91.42%** |

### By floor-number length

| Floor-number length | Reported accuracy |
|---|---:|
| Single digit | 96.00% |
| Two digits | 95.65% |
| Three digits | 81.81% |

The paper reports **64 successful selections out of 70 trials**, corresponding to an overall empirical success rate of 91.42%.

---

## Limitations

The reported experiments and the current implementation identify several limitations:

- **0 ↔ 1 ambiguity:** a closed fist and a thumb-up pose can be difficult to distinguish in some orientations.
- **Motion blur and landmark dropout:** fast motion, occlusion, and difficult lighting can reduce landmark quality.
- **Multi-digit error propagation:** one incorrectly recognized digit can affect the final floor sequence.
- **Limited evaluation set:** the reported dataset contains 70 videos across four elevator environments.
- **No physical elevator interface:** `simulate_move()` is a software stub rather than a hardware control implementation.
- **Person-to-hand association:** additional work is needed for more complex multi-person scenes.

These limitations are part of the research context and should be considered before interpreting the reported accuracy as general deployment performance.

---

## Future Work

The paper discusses several directions for further development:

- More robust thumb/fist discrimination
- Adaptive thresholds based on palm size
- Larger and more diverse validation datasets
- Additional low-light, occlusion, and glove samples
- More extensive temporal modeling
- Improved person-to-hand association
- Secure integration with an elevator control API
- Systematic logging and automated testing

---

## Repository Structure

```text
Elevator-Control/
├── main.py
├── requirements.txt
├── Gesture-Based Elevator Control System for Real-Time Floor Selection.pdf
├── LICENSE
├── DataSet/
│   └── README.md
└── images/
    ├── Pipeline_Sequence_Diagram.jpg
    ├── state_machine.png
    ├── both_open.png
    ├── both_fist.png
    ├── undefined.png
    ├── 3.png
    └── 9.png
```

---

## Paper

The complete paper is intended to be kept with the implementation:

[Gesture-Based Elevator Control System for Real-Time Floor Selection.pdf](./Gesture-Based%20Elevator%20Control%20System%20for%20Real-Time%20Floor%20Selection.pdf)

**Citation**

> K. Shojaei and E. Shabaninia, “Gesture-Based Elevator Control System for Real-Time Floor Selection,” in *2025 10th International Congress on Fuzzy and Intelligent Systems (CFIS)*, 2025, doi: 10.1109/CFIS68949.2025.11652063.

---

## License

This project is released under the [MIT License](LICENSE).
