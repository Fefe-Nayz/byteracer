import cv2
import numpy as np

'''The range of H, S, V in HSV space for colors'''
# You can run ../examples/hsv_threshold_analyzer.py to analyze and adjust these values
color_dict = {
    'red':    [[0,   8],  [80, 255], [0,   255]],
    'orange': [[12, 18],  [80, 255], [80, 255]],
    'yellow': [[20, 60],  [60, 255], [120, 255]],
    'green':  [[45, 85],  [120,255], [80,  255]],
    'blue':   [[92, 120], [120,255], [80,  255]],
    'purple': [[115,155], [30,  255], [60,  255]],
    'magenta':[[160,180], [30,  255], [60,  255]],
}

'''We'll keep track of detection results for each color separately.'''
# Example structure:
# color_obj_parameter = {
#     'red':    {'x': ..., 'y': ..., 'w': ..., 'h': ..., 'n': ...},
#     'blue':   {...},
#     ...
# }
color_obj_parameter = {}

# Initialize each color's detection parameters
def init_color_parameter_if_needed(color_name):
    if color_name not in color_obj_parameter:
        color_obj_parameter[color_name] = {
            'x': 0,
            'y': 0,
            'w': 0,
            'h': 0,
            'n': 0
        }

def color_detect_one_color(img, width, height, color_name, rectangle_color=(0, 0, 255)):
    """
    Performs detection on a *single* color, returns annotated image and
    updates `color_obj_parameter[color_name]` with the largest bounding box.
    """
    init_color_parameter_if_needed(color_name)

    # Reduce image for faster recognition
    zoom = 4  # reduction ratio
    width_zoom = int(width / zoom)
    height_zoom = int(height / zoom)
    resize_img = cv2.resize(img, (width_zoom, height_zoom), interpolation=cv2.INTER_LINEAR)
    
    # Convert BGR to HSV
    hsv = cv2.cvtColor(resize_img, cv2.COLOR_BGR2HSV)

    # Lower & upper HSV thresholds
    lower_bound = np.array([
        min(color_dict[color_name][0]),
        min(color_dict[color_name][1]),
        min(color_dict[color_name][2])
    ])
    upper_bound = np.array([
        max(color_dict[color_name][0]),
        max(color_dict[color_name][1]),
        max(color_dict[color_name][2])
    ])

    # Special handling for 'red': it often needs two ranges in HSV
    mask = cv2.inRange(hsv, lower_bound, upper_bound)
    if color_name == 'red':
        # Combine with upper hue range for red
        mask_2 = cv2.inRange(hsv, (167, 0, 0), (180, 255, 255))
        mask = cv2.bitwise_or(mask, mask_2)

    # Noise removal
    kernel_5 = np.ones((5,5), np.uint8)
    open_img = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_5, iterations=1)

    # Find contours
    _tuple = cv2.findContours(open_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if len(_tuple) == 3:
        _, contours, hierarchy = _tuple
    else:
        contours, hierarchy = _tuple

    num_contours = len(contours)
    color_obj_parameter[color_name]['n'] = num_contours
    if num_contours < 1:
        # No block detected, reset
        color_obj_parameter[color_name]['x'] = width//2
        color_obj_parameter[color_name]['y'] = height//2
        color_obj_parameter[color_name]['w'] = 0
        color_obj_parameter[color_name]['h'] = 0
        color_obj_parameter[color_name]['n'] = 0
        return img

    # Track the largest bounding box
    max_area = 0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w >= 8 and h >= 8:
            # Scale back up
            x *= zoom
            y *= zoom
            w *= zoom
            h *= zoom
            # Draw rectangle
            cv2.rectangle(
                img,
                (x, y),
                (x+w, y+h),
                rectangle_color,
                2
            )
            # Draw text
            cv2.putText(
                img,
                color_name,
                (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                rectangle_color,
                1,
                cv2.LINE_AA
            )

            area = w * h
            if area > max_area:
                max_area = area
                color_obj_parameter[color_name]['x'] = int(x + w/2)
                color_obj_parameter[color_name]['y'] = int(y + h/2)
                color_obj_parameter[color_name]['w'] = w
                color_obj_parameter[color_name]['h'] = h

    return img

def color_detect_work(img, width, height, color_list):
    """
    Detect multiple colors in `color_list` and annotate `img`.

    `color_list` can be:
      - a single string (e.g. "red")
      - a list of color names (e.g. ["red", "blue", "green"])
    """
    # If user passed a single string, make it a list for uniform handling
    if isinstance(color_list, str):
        color_list = [color_list]

    # Optionally pick bounding-box colors for each color name
    # (B, G, R) format:
    color_bgr_dict = {
        'red':    (0, 0, 255),
        'green':  (0, 255, 0),
        'blue':   (255, 0, 0),
        'orange': (0, 128, 255),
        'yellow': (0, 255, 255),
        'purple': (255, 0, 255),
        'magenta':(255, 0, 255)
    }

    # For each color in the list, run detection & annotate
    for c in color_list:
        rect_color = color_bgr_dict.get(c, (255, 255, 255))  # fallback is white
        img = color_detect_one_color(img, width, height, c, rectangle_color=rect_color)

    return img


# Test example for local usage
def test(colors):
    """
    Simple test for color detection, using your default camera.
    :param colors: single color or list of colors
    """
    print("color detection(s):", colors)
    cap = cv2.VideoCapture(0)
    cap.set(3, 640)
    cap.set(4, 480)
    
    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            print("Ignoring empty camera frame.")
            continue

        out_img = color_detect_work(frame, 640, 480, colors)
        cv2.imshow('Color detecting ...', out_img)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        if cv2.waitKey(1) & 0xff == 27:
            break
        if cv2.getWindowProperty('Color detecting ...', 1) < 0:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    # Example usage: detect both red and blue
    test(['red', 'blue'])
