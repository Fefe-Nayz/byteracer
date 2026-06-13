"""Isolated YOLO/NCNN worker process for circuit-mode inference.

The robot controller must never execute NCNN in its own process: on the Pi the
model can hold the GIL long enough to starve the control loop. This worker owns
Ultralytics/NCNN and exchanges only latest-frame/latest-detection messages.
"""

import os
import queue
import time
import traceback


def _configure_process(cores):
    """Keep model work off the reserved control core and avoid thread sprawl."""
    thread_count = max(1, len(cores or []) or 1)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "MKL_NUM_THREADS",
    ):
        os.environ.setdefault(name, str(thread_count))

    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except (OSError, ValueError):
            pass

    try:
        if hasattr(os, "nice"):
            os.nice(10)
    except (PermissionError, OSError):
        pass


def _replace_queue_item(target_queue, item):
    """Store only the newest state in a bounded multiprocessing queue."""
    try:
        while True:
            target_queue.get_nowait()
    except queue.Empty:
        pass

    try:
        target_queue.put_nowait(item)
    except queue.Full:
        pass


def _latest_frame(frame_queue, first_item):
    """Drop stale frames so inference always works on the newest one."""
    item = first_item
    try:
        while True:
            item = frame_queue.get_nowait()
    except queue.Empty:
        return item


def _class_name(labels, class_index):
    if isinstance(labels, dict):
        return labels.get(class_index) or labels.get(str(class_index)) or str(class_index)
    try:
        return labels[class_index]
    except Exception:
        return str(class_index)


def _process_frame(model, labels, frame, model_input_size, min_confidence):
    import cv2

    if frame is None:
        return None

    if len(frame.shape) == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

    model_width, model_height = model_input_size
    target_aspect = model_width / model_height
    current_aspect = frame.shape[1] / frame.shape[0]
    offset_x = 0
    offset_y = 0
    original_width = int(frame.shape[1])
    original_height = int(frame.shape[0])

    if current_aspect > target_aspect:
        new_width = int(original_height * target_aspect)
        offset_x = (original_width - new_width) // 2
        cropped = frame[:, offset_x : offset_x + new_width]
        cropped_width = new_width
        cropped_height = original_height
    else:
        new_height = int(original_width / target_aspect)
        offset_y = (original_height - new_height) // 2
        cropped = frame[offset_y : offset_y + new_height, :]
        cropped_width = original_width
        cropped_height = new_height

    resized_frame = cv2.resize(cropped, model_input_size)
    results = model(resized_frame, verbose=False)
    boxes = results[0].boxes
    detections = []

    for i in range(len(boxes)):
        xyxy = boxes[i].xyxy.cpu().numpy().squeeze()
        xmin, ymin, xmax, ymax = xyxy.astype(int)
        class_index = int(boxes[i].cls.item())
        confidence = float(boxes[i].conf.item())

        if confidence < min_confidence:
            continue

        cropped_xmin = int(xmin * (cropped_width / model_width))
        cropped_ymin = int(ymin * (cropped_height / model_height))
        cropped_xmax = int(xmax * (cropped_width / model_width))
        cropped_ymax = int(ymax * (cropped_height / model_height))

        orig_xmin = max(0, min(cropped_xmin + offset_x, original_width - 1))
        orig_ymin = max(0, min(cropped_ymin + offset_y, original_height - 1))
        orig_xmax = max(0, min(cropped_xmax + offset_x, original_width - 1))
        orig_ymax = max(0, min(cropped_ymax + offset_y, original_height - 1))

        detections.append(
            {
                "class": _class_name(labels, class_index),
                "class_index": class_index,
                "confidence": confidence,
                "x": int((orig_xmin + orig_xmax) // 2),
                "y": int((orig_ymin + orig_ymax) // 2),
                "width": int(orig_xmax - orig_xmin),
                "height": int(orig_ymax - orig_ymin),
                "xmin": int(orig_xmin),
                "ymin": int(orig_ymin),
                "xmax": int(orig_xmax),
                "ymax": int(orig_ymax),
            }
        )

    return detections


def run_yolo_worker(model_path, frame_queue, result_queue, stop_event, cores=None):
    """Worker entry point. All heavy inference imports stay in this process."""
    _configure_process(cores)

    try:
        from ultralytics import YOLO

        model = YOLO(model_path, task="detect")
        labels = model.names
        _replace_queue_item(
            result_queue,
            {
                "type": "ready",
                "labels": labels,
                "pid": os.getpid(),
                "cores": sorted(cores) if cores else None,
                "timestamp": time.time(),
            },
        )
    except Exception:
        _replace_queue_item(
            result_queue,
            {
                "type": "fatal",
                "error": traceback.format_exc(),
                "timestamp": time.time(),
            },
        )
        return

    while not stop_event.is_set():
        try:
            item = frame_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        item = _latest_frame(frame_queue, item)
        if not isinstance(item, dict):
            continue

        seq = item.get("seq", 0)
        frame = item.get("frame")
        model_input_size = tuple(item.get("model_input_size") or (640, 640))
        min_confidence = float(item.get("min_confidence", 0.5))

        try:
            t0 = time.perf_counter()
            detections = _process_frame(
                model, labels, frame, model_input_size, min_confidence
            )
            inference_ms = (time.perf_counter() - t0) * 1000.0
            _replace_queue_item(
                result_queue,
                {
                    "type": "result",
                    "seq": seq,
                    "detections": detections or [],
                    "object_count": len(detections or []),
                    "inference_ms": inference_ms,
                    "timestamp": time.time(),
                },
            )
        except Exception:
            _replace_queue_item(
                result_queue,
                {
                    "type": "error",
                    "seq": seq,
                    "error": traceback.format_exc(),
                    "timestamp": time.time(),
                },
            )
