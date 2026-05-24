#!/usr/bin/env python3

# whether print welcome message
import os
import logging

from .version import __version__
if 'VILIB_WELCOME' not in os.environ or os.environ['VILIB_WELCOME'] not in [
        'False', '0'
]:
    from pkg_resources import require
    picamera2_version = require('picamera2')[0].version
    print(f'vilib {__version__} launching ...')
    print(f'picamera2 {picamera2_version}')

# set libcamera2 log level
os.environ['LIBCAMERA_LOG_LEVELS'] = '*:ERROR'
from picamera2 import Picamera2
import libcamera

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from flask import Flask, render_template, Response

import time
import datetime
import threading
from multiprocessing import Process, Manager

from .utils import *
from .drawing import reset_drawings, add_rectangle, add_text, draw_overlay

# user and user home directory
# =================================================================
user = os.popen("echo ${SUDO_USER:-$(who -m | awk '{ print $1 }')}").readline().strip()
user_home = os.popen(f'getent passwd {user} | cut -d: -f 6').readline().strip()
# print(f"user: {user}")
# print(f"user_home: {user_home}")

# Default path for pictures and videos
DEFAULLT_PICTURES_PATH = '%s/Pictures/vilib/'%user_home
DEFAULLT_VIDEOS_PATH = '%s/Videos/vilib/'%user_home

# utils
# =================================================================
def findContours(img):
    _tuple = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)      
    # compatible with opencv3.x and opencv4.x
    if len(_tuple) == 3:
        _, contours, hierarchy = _tuple
    else:
        contours, hierarchy = _tuple
    return contours, hierarchy

# flask
# =================================================================
os.environ['FLASK_DEBUG'] = 'development'
app = Flask(__name__)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def index():
    """Video streaming home page."""
    return render_template('index.html')

def get_frame():
    return cv2.imencode('.jpg', Vilib.flask_img)[1].tobytes()

def get_qrcode_pictrue():
    return cv2.imencode('.jpg', Vilib.flask_img)[1].tobytes()

def get_png_frame():
    return cv2.imencode('.png', Vilib.flask_img)[1].tobytes()

def get_qrcode():
    while Vilib.qrcode_img_encode is None:
         time.sleep(0.2)
    return Vilib.qrcode_img_encode

def gen():
    """Video streaming generator function."""
    while True:
        frame = get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.03)

@app.route('/mjpg')  # video
def video_feed():
    """Video streaming route. Put this in the src attribute of an <img> tag."""
    if Vilib.web_display_flag:
        response = Response(
            gen(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
    else:
        tip = '''
    Please enable web display first:
        Vilib.display(web=True)
'''
        html = f"<html><style>p{{white-space: pre-wrap;}}</style><body><p>{tip}</p></body></html>"
        return Response(html, mimetype='text/html')

@app.route('/mjpg.jpg')  # single JPEG
def video_feed_jpg():
    """JPEG snapshot route."""
    response = Response(get_frame(), mimetype="image/jpeg")
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

@app.route('/mjpg.png')  # single PNG
def video_feed_png():
    """PNG snapshot route."""
    response = Response(get_png_frame(), mimetype="image/png")
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

@app.route("/qrcode")
def qrcode_feed():
    qrcode_html = '''
<!DOCTYPE html>
<html>
<head>
    <title>QRcode</title>
    <script>
        function refreshQRCode() {
            var imgElement = document.getElementById('qrcode-img');
            imgElement.src = '/qrcode.png?' + new Date().getTime();  // Add timestamp to avoid caching
        }
        var refreshInterval = 500;

        window.onload = function() {
            refreshQRCode(); 
            setInterval(refreshQRCode, refreshInterval);
        };
    </script>
</head>
<body>
    <img id="qrcode-img" src="/qrcode.png" alt="QR Code" />
</body>
</html>
'''
    return Response(qrcode_html, mimetype='text/html')

@app.route("/qrcode.png")
def qrcode_feed_png():
    """QR Code snapshot route."""
    if Vilib.web_qrcode_flag:
        response = Response(get_qrcode(), mimetype="image/png")
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
    else:
        tip = '''
    Please enable web display first:
        Vilib.display_qrcode(web=True)
'''
        html = f"<html><style>p{{white-space: pre-wrap;}}</style><body><p>{tip}</p></body></html>"
        return Response(html, mimetype='text/html')

def web_camera_start():
    try:
        Vilib.flask_start = True
        app.run(host='0.0.0.0', port=9000, threaded=True, debug=False)
    except Exception as e:
        print(e)

# Vilib
# =================================================================
class Vilib(object):

    picam2 = Picamera2()

    camera_size = (640, 480)
    camera_width = 640
    camera_height = 480
    camera_vflip = False
    camera_hflip = False
    camera_run = False

    flask_thread = None
    camera_thread = None
    flask_start = False

    qrcode_display_thread = None
    qrcode_making_completed = False
    qrcode_img = Manager().list(range(1))
    qrcode_img_encode = None
    qrcode_win_name = 'qrcode'

    img = Manager().list(range(1))
    flask_img = Manager().list(range(1))

    Windows_Name = "picamera"
    imshow_flag = False
    web_display_flag = False
    imshow_qrcode_flag = False
    web_qrcode_flag = False

    draw_fps = False
    fps_origin = (camera_width - 105, 20)
    fps_size = 0.6
    fps_color = (255, 255, 255)

    detect_obj_parameter = {}
    
    # === MULTI-COLOR DETECTION: replaced color_detect_color with color_detect_list ===
    color_detect_list = None

    face_detect_sw = False
    hands_detect_sw = False
    pose_detect_sw = False
    image_classify_sw = False
    image_classification_model = None
    image_classification_labels = None
    objects_detect_sw = False
    objects_detection_model = None
    objects_detection_labels = None
    qrcode_detect_sw = False
    traffic_detect_sw = False

    # Custom drawing functions
    # =================================================================
    drawing_enabled = False

    @staticmethod
    def enable_drawing():
        """Enable custom overlays on the camera feed."""
        Vilib.drawing_enabled = True

    @staticmethod
    def disable_drawing():
        """Disable custom overlays on the camera feed."""
        Vilib.drawing_enabled = False
        reset_drawings()

    @staticmethod
    def draw_rectangle(x, y, width, height, color=(0, 255, 0), thickness=2, label=None, label_color=None, font_scale=0.5, label_thickness=1, label_position='top'):
        """Queue a rectangle overlay on the camera feed."""
        add_rectangle(x, y, width, height, color, thickness, label, label_color, font_scale, label_thickness, label_position)

    @staticmethod
    def draw_text(text, x, y, color=(0, 255, 0), font_scale=0.5, thickness=1):
        """Queue a text overlay on the camera feed."""
        add_text(text, x, y, color, font_scale, thickness)

    @staticmethod
    def clear_drawings():
        """Clear queued overlay requests."""
        reset_drawings()

    @staticmethod
    def get_instance():
        return Vilib.picam2

    @staticmethod
    def set_controls(controls):
        Vilib.picam2.set_controls(controls)

    @staticmethod
    def get_controls():
        return Vilib.picam2.capture_metadata()

    @staticmethod
    def camera():
        Vilib.camera_width, Vilib.camera_height = Vilib.camera_size

        picam2 = Vilib.picam2
        preview_config = picam2.preview_configuration

        # Adjust camera config
        preview_config.size = Vilib.camera_size
        preview_config.format = 'RGB888'
        preview_config.transform = libcamera.Transform(
            hflip=Vilib.camera_hflip,
            vflip=Vilib.camera_vflip
        )
        preview_config.colour_space = libcamera.ColorSpace.Sycc()
        preview_config.buffer_count = 4
        preview_config.queue = True
        preview_config.controls = {'FrameRate': 60}

        try:
            picam2.start()
        except Exception as e:
            print(f"\033[38;5;1mError:\033[0m\n{e}")
            print("\nPlease check whether the camera is connected well.\n"
                  "You can use the \"libcamera-hello\" command to test the camera.")
            exit(1)
        Vilib.camera_run = True

        Vilib.fps_origin = (Vilib.camera_width - 105, 20)
        fps = 0
        start_time = time.time()
        framecount = 0

        try:
            while True:
                Vilib.img = picam2.capture_array()

                # --- Run detection pipelines ---
                Vilib.img = Vilib.color_detect_func(Vilib.img)
                Vilib.img = Vilib.face_detect_func(Vilib.img)
                Vilib.img = Vilib.traffic_detect_fuc(Vilib.img)
                Vilib.img = Vilib.qrcode_detect_func(Vilib.img)
                Vilib.img = Vilib.image_classify_fuc(Vilib.img)
                Vilib.img = Vilib.object_detect_fuc(Vilib.img)
                Vilib.img = Vilib.hands_detect_fuc(Vilib.img)
                Vilib.img = Vilib.pose_detect_fuc(Vilib.img)

                if Vilib.drawing_enabled:
                    Vilib.img = draw_overlay(Vilib.img)

                # --- Calculate FPS ---
                framecount += 1
                elapsed_time = float(time.time() - start_time)
                if elapsed_time > 1:
                    fps = round(framecount / elapsed_time, 1)
                    framecount = 0
                    start_time = time.time()

                # --- Draw FPS if needed ---
                if Vilib.draw_fps:
                    cv2.putText(
                        Vilib.img,
                        f"FPS: {fps}",
                        Vilib.fps_origin,
                        cv2.FONT_HERSHEY_SIMPLEX,
                        Vilib.fps_size,
                        Vilib.fps_color,
                        1,
                        cv2.LINE_AA
                    )

                # --- Copy for Flask streaming ---
                Vilib.flask_img = Vilib.img

                # --- Local display ---
                if Vilib.imshow_flag:
                    try:
                        try:
                            prop = cv2.getWindowProperty(Vilib.Windows_Name, cv2.WND_PROP_VISIBLE)
                            qrcode_prop = cv2.getWindowProperty(Vilib.qrcode_win_name, cv2.WND_PROP_VISIBLE)
                            if prop < 1 or qrcode_prop < 1:
                                break
                        except:
                            pass

                        cv2.imshow(Vilib.Windows_Name, Vilib.img)
                        # Also display a QR code window if needed
                        if Vilib.imshow_qrcode_flag and Vilib.qrcode_making_completed:
                            Vilib.qrcode_making_completed = False
                            cv2.imshow(Vilib.qrcode_win_name, Vilib.qrcode_img)

                        cv2.waitKey(1)

                    except Exception as e:
                        Vilib.imshow_flag = False
                        print(f"imshow failed:\n  {e}")
                        break

                # --- Exit if camera_run = False ---
                if not Vilib.camera_run:
                    break

        except KeyboardInterrupt as e:
            print(e)
        finally:
            picam2.close()
            cv2.destroyAllWindows()

    @staticmethod
    def camera_start(vflip=False, hflip=False, size=None):
        if size is not None:
            Vilib.camera_size = size
        Vilib.camera_hflip = hflip
        Vilib.camera_vflip = vflip
        Vilib.camera_thread = threading.Thread(target=Vilib.camera, name="vilib")
        Vilib.camera_thread.daemon = False
        Vilib.camera_thread.start()
        while not Vilib.camera_run:
            time.sleep(0.1)

    @staticmethod
    def camera_close():
        if Vilib.camera_thread is not None:
            Vilib.camera_run = False
            time.sleep(0.1)

    @staticmethod
    def display(local=True, web=True):
        """Enable local and/or web display for camera frames."""
        # Check if camera is running
        if (Vilib.camera_thread is not None) and Vilib.camera_thread.is_alive():
            # Local (desktop) display
            if local:
                if 'DISPLAY' in os.environ.keys():
                    Vilib.imshow_flag = True
                    print("Imgshow start ...")
                else:
                    Vilib.imshow_flag = False
                    print("Local display failed, because there is no GUI environment.")
            # Web display
            if web:
                Vilib.web_display_flag = True
                print("\nWeb display on:")
                wlan0, eth0 = getIP()
                if wlan0 is not None:
                    print(f"      http://{wlan0}:9000/mjpg")
                if eth0 is not None:
                    print(f"      http://{eth0}:9000/mjpg")
                print()
                if (Vilib.flask_thread is None) or (not Vilib.flask_thread.is_alive()):
                    print('Starting web streaming ...')
                    Vilib.flask_thread = threading.Thread(
                        name='flask_thread',
                        target=web_camera_start
                    )
                    Vilib.flask_thread.daemon = True
                    Vilib.flask_thread.start()
        else:
            print('Error: Please execute < camera_start() > first.')

    @staticmethod
    def show_fps(color=None, fps_size=None, fps_origin=None):
        if color is not None:
            Vilib.fps_color = color
        if fps_size is not None:
            Vilib.fps_size = fps_size
        if fps_origin is not None:
            Vilib.fps_origin = fps_origin
        Vilib.draw_fps = True

    @staticmethod
    def hide_fps():
        Vilib.draw_fps = False

    # Take photo
    # =================================================================
    @staticmethod
    def take_photo(photo_name, path=DEFAULLT_PICTURES_PATH):
        # Check & create path
        if not os.path.exists(path):
            os.makedirs(name=path, mode=0o751, exist_ok=True)
            time.sleep(0.01)
        # Save photo
        status = False
        for _ in range(5):
            if Vilib.img is not None:
                status = cv2.imwrite(path + '/' + photo_name + '.jpg', Vilib.img)
                break
            else:
                time.sleep(0.01)
        return status

    # Record video
    # =================================================================
    rec_video_set = {
        "fourcc": cv2.VideoWriter_fourcc(*'XVID'), 
        "fps": 30.0,
        "framesize": (640, 480),
        "isColor": True,
        "name": "default",
        "path": DEFAULLT_VIDEOS_PATH,
        "start_flag": False,
        "stop_flag": False
    }
    rec_thread = None

    @staticmethod
    def rec_video_work():
        # Ensure path
        if not os.path.exists(Vilib.rec_video_set["path"]):
            os.makedirs(name=Vilib.rec_video_set["path"], mode=0o751, exist_ok=True)
            time.sleep(0.01)

        # Create writer
        filename = Vilib.rec_video_set["path"] + '/' + Vilib.rec_video_set["name"] + '.avi'
        video_out = cv2.VideoWriter(
            filename,
            Vilib.rec_video_set["fourcc"],
            Vilib.rec_video_set["fps"],
            Vilib.rec_video_set["framesize"],
            Vilib.rec_video_set["isColor"]
        )
    
        while True:
            if Vilib.rec_video_set["start_flag"]:
                video_out.write(Vilib.img)
            if Vilib.rec_video_set["stop_flag"]:
                video_out.release()
                Vilib.rec_video_set["start_flag"] = False
                break

    @staticmethod
    def rec_video_run():
        if Vilib.rec_thread is not None:
            Vilib.rec_video_stop()
        Vilib.rec_video_set["stop_flag"] = False
        Vilib.rec_thread = threading.Thread(name='rec_video', target=Vilib.rec_video_work)
        Vilib.rec_thread.daemon = True
        Vilib.rec_thread.start()

    @staticmethod
    def rec_video_start():
        Vilib.rec_video_set["start_flag"] = True
        Vilib.rec_video_set["stop_flag"] = False

    @staticmethod
    def rec_video_pause():
        Vilib.rec_video_set["start_flag"] = False

    @staticmethod
    def rec_video_stop():
        Vilib.rec_video_set["start_flag"] = False
        Vilib.rec_video_set["stop_flag"] = True
        if Vilib.rec_thread is not None:
            Vilib.rec_thread.join(3)
            Vilib.rec_thread = None

    # =================================================================
    # MULTI-COLOR DETECTION
    # =================================================================
    @staticmethod
    def color_detect(colors=None):
        """
        Enable color detection on one or multiple colors.
        
        :param colors: string (e.g. "red") or list of strings (e.g. ["red","blue"]).
                       If None or empty, detection is disabled.
        """
        from .color_detection import color_detect_work, color_obj_parameter

        if not colors:
            # No color or empty => disable detection
            Vilib.color_detect_list = None
            return

        # If only a single color string is provided, turn it into a list
        if isinstance(colors, str):
            Vilib.color_detect_list = [colors]
        else:
            # Assume it's already a list
            Vilib.color_detect_list = colors

        # We'll store the reference to the detection function
        Vilib.color_detect_work = color_detect_work
        # color_obj_parameter is a dict { "red":{x:..., y:..., w:..., h:..., n:...}, "blue":{...}, ... }
        Vilib.color_obj_parameter = color_obj_parameter

        # Also ensure we have placeholders in detect_obj_parameter for each color
        for c in Vilib.color_detect_list:
            if c not in color_obj_parameter:
                color_obj_parameter[c] = {'x': 0, 'y': 0, 'w': 0, 'h': 0, 'n': 0}
            Vilib.detect_obj_parameter[f'{c}_x'] = 0
            Vilib.detect_obj_parameter[f'{c}_y'] = 0
            Vilib.detect_obj_parameter[f'{c}_w'] = 0
            Vilib.detect_obj_parameter[f'{c}_h'] = 0
            Vilib.detect_obj_parameter[f'{c}_n'] = 0

    @staticmethod
    def color_detect_func(img):
        """
        Called inside the main camera loop to detect one or more colors.
        """
        if Vilib.color_detect_list and hasattr(Vilib, "color_detect_work"):
            # color_detect_work can handle a list of colors
            img = Vilib.color_detect_work(
                img,
                Vilib.camera_width,
                Vilib.camera_height,
                Vilib.color_detect_list
            )
            # For each color, copy updated results into detect_obj_parameter
            for c in Vilib.color_detect_list:
                param = Vilib.color_obj_parameter[c]
                Vilib.detect_obj_parameter[f'{c}_x'] = param['x']
                Vilib.detect_obj_parameter[f'{c}_y'] = param['y']
                Vilib.detect_obj_parameter[f'{c}_w'] = param['w']
                Vilib.detect_obj_parameter[f'{c}_h'] = param['h']
                Vilib.detect_obj_parameter[f'{c}_n'] = param['n']
        return img

    @staticmethod
    def close_color_detection():
        Vilib.color_detect_list = None

    # =================================================================
    # Face Detection
    # =================================================================
    @staticmethod
    def face_detect_switch(flag=False):
        Vilib.face_detect_sw = flag
        if Vilib.face_detect_sw:
            from .face_detection import face_detect, set_face_detection_model, face_obj_parameter
            Vilib.face_detect_work = face_detect
            Vilib.set_face_detection_model = set_face_detection_model
            Vilib.face_obj_parameter = face_obj_parameter
            Vilib.detect_obj_parameter['human_x'] = Vilib.face_obj_parameter['x']
            Vilib.detect_obj_parameter['human_y'] = Vilib.face_obj_parameter['y']
            Vilib.detect_obj_parameter['human_w'] = Vilib.face_obj_parameter['w']
            Vilib.detect_obj_parameter['human_h'] = Vilib.face_obj_parameter['h']
            Vilib.detect_obj_parameter['human_n'] = Vilib.face_obj_parameter['n']

    @staticmethod
    def face_detect_func(img):
        if Vilib.face_detect_sw and hasattr(Vilib, "face_detect_work"):
            img = Vilib.face_detect_work(img, Vilib.camera_width, Vilib.camera_height)
            Vilib.detect_obj_parameter['human_x'] = Vilib.face_obj_parameter['x']
            Vilib.detect_obj_parameter['human_y'] = Vilib.face_obj_parameter['y']
            Vilib.detect_obj_parameter['human_w'] = Vilib.face_obj_parameter['w']
            Vilib.detect_obj_parameter['human_h'] = Vilib.face_obj_parameter['h']
            Vilib.detect_obj_parameter['human_n'] = Vilib.face_obj_parameter['n']
        return img

    # =================================================================
    # Traffic Sign Detection
    # =================================================================
    @staticmethod
    def traffic_detect_switch(flag=False):
        Vilib.traffic_detect_sw = flag
        if Vilib.traffic_detect_sw:
            from .traffic_sign_detection import traffic_sign_detect, traffic_sign_obj_parameter
            Vilib.traffic_detect_work = traffic_sign_detect
            Vilib.traffic_sign_obj_parameter = traffic_sign_obj_parameter
            Vilib.detect_obj_parameter['traffic_sign_x'] = Vilib.traffic_sign_obj_parameter['x']
            Vilib.detect_obj_parameter['traffic_sign_y'] = Vilib.traffic_sign_obj_parameter['y']
            Vilib.detect_obj_parameter['traffic_sign_w'] = Vilib.traffic_sign_obj_parameter['w']
            Vilib.detect_obj_parameter['traffic_sign_h'] = Vilib.traffic_sign_obj_parameter['h']
            Vilib.detect_obj_parameter['traffic_sign_t'] = Vilib.traffic_sign_obj_parameter['t']
            Vilib.detect_obj_parameter['traffic_sign_acc'] = Vilib.traffic_sign_obj_parameter['acc']

    @staticmethod
    def traffic_detect_fuc(img):
        if Vilib.traffic_detect_sw and hasattr(Vilib, "traffic_detect_work"):
            img = Vilib.traffic_detect_work(img, border_rgb=(255, 0, 0))
            Vilib.detect_obj_parameter['traffic_sign_x'] = Vilib.traffic_sign_obj_parameter['x']
            Vilib.detect_obj_parameter['traffic_sign_y'] = Vilib.traffic_sign_obj_parameter['y']
            Vilib.detect_obj_parameter['traffic_sign_w'] = Vilib.traffic_sign_obj_parameter['w']
            Vilib.detect_obj_parameter['traffic_sign_h'] = Vilib.traffic_sign_obj_parameter['h']
            Vilib.detect_obj_parameter['traffic_sign_t'] = Vilib.traffic_sign_obj_parameter['t']
            Vilib.detect_obj_parameter['traffic_sign_acc'] = Vilib.traffic_sign_obj_parameter['acc']
        return img

    # =================================================================
    # QRCode Recognition
    # =================================================================
    @staticmethod
    def qrcode_detect_switch(flag=False):
        Vilib.qrcode_detect_sw = flag
        if Vilib.qrcode_detect_sw:
            from .qrcode_recognition import qrcode_recognize, qrcode_obj_parameter
            Vilib.qrcode_recognize = qrcode_recognize
            Vilib.qrcode_obj_parameter = qrcode_obj_parameter
            Vilib.detect_obj_parameter['qr_x'] = Vilib.qrcode_obj_parameter['x']
            Vilib.detect_obj_parameter['qr_y'] = Vilib.qrcode_obj_parameter['y']
            Vilib.detect_obj_parameter['qr_w'] = Vilib.qrcode_obj_parameter['w']
            Vilib.detect_obj_parameter['qr_h'] = Vilib.qrcode_obj_parameter['h']
            Vilib.detect_obj_parameter['qr_data'] = Vilib.qrcode_obj_parameter['data']
            Vilib.detect_obj_parameter['qr_list'] = Vilib.qrcode_obj_parameter['list']

    @staticmethod
    def qrcode_detect_func(img):
        if Vilib.qrcode_detect_sw and hasattr(Vilib, "qrcode_recognize"):
            img = Vilib.qrcode_recognize(img, border_rgb=(255, 0, 0))
            Vilib.detect_obj_parameter['qr_x'] = Vilib.qrcode_obj_parameter['x']
            Vilib.detect_obj_parameter['qr_y'] = Vilib.qrcode_obj_parameter['y']
            Vilib.detect_obj_parameter['qr_w'] = Vilib.qrcode_obj_parameter['w']
            Vilib.detect_obj_parameter['qr_h'] = Vilib.qrcode_obj_parameter['h']
            Vilib.detect_obj_parameter['qr_data'] = Vilib.qrcode_obj_parameter['data']
        return img

    # =================================================================
    # QRCode Making (Render new QR code)
    # =================================================================
    @staticmethod
    def make_qrcode(
        data,
        path=None,
        version=1,
        box_size=10,
        border=4,
        fill_color=(132, 112, 255),
        back_color=(255, 255, 255)
    ):
        import qrcode
        qr = qrcode.QRCode(
            version=version,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=box_size,
            border=border,
        )
        qr.add_data(data)
        qr.make(fit=True)
        qr_pil = qr.make_image(fill_color=fill_color, back_color=back_color)

        if path is not None:
            qr_pil.save(path)

        Vilib.qrcode_img = cv2.cvtColor(np.array(qr_pil), cv2.COLOR_RGB2BGR)
        Vilib.qrcode_making_completed = True

        if Vilib.web_qrcode_flag:
            Vilib.qrcode_img_encode = cv2.imencode('.jpg', Vilib.qrcode_img)[1].tobytes()

    @staticmethod
    def display_qrcode_work():
        while True:
            if Vilib.imshow_flag:
                time.sleep(0.1)
                continue

            if Vilib.imshow_qrcode_flag and Vilib.qrcode_making_completed:
                Vilib.qrcode_making_completed = False
                try:
                    if len(Vilib.qrcode_img) > 10:
                        cv2.imshow(Vilib.qrcode_win_name, Vilib.qrcode_img)
                        cv2.waitKey(1)
                        if cv2.getWindowProperty(Vilib.qrcode_win_name, cv2.WND_PROP_VISIBLE) == 0:
                            cv2.destroyWindow(Vilib.qrcode_win_name)
                except Exception as e:
                    Vilib.imshow_qrcode_flag = False
                    print(f"imshow qrcode failed:\n  {e}")
                    break
            time.sleep(0.1)

    @staticmethod
    def display_qrcode(local=True, web=True):
        if local:
            if 'DISPLAY' in os.environ.keys():
                Vilib.imshow_qrcode_flag = True
                print("Imgshow qrcode start ...")
            else:
                Vilib.imshow_qrcode_flag = False
                print("Local display failed, because there is no GUI environment.")
        if web:
            Vilib.web_qrcode_flag = True
            print(f'QRcode display on:')
            wlan0, eth0 = getIP()
            if wlan0 is not None:
                print(f"      http://{wlan0}:9000/qrcode")
            if eth0 is not None:
                print(f"      http://{eth0}:9000/qrcode")
            print()
            if (Vilib.flask_thread is None) or (not Vilib.flask_thread.is_alive()):
                print('Starting web streaming ...')
                Vilib.flask_thread = threading.Thread(name='flask_thread', target=web_camera_start)
                Vilib.flask_thread.daemon = True
                Vilib.flask_thread.start()

        if (Vilib.qrcode_display_thread is None) or (not Vilib.qrcode_display_thread.is_alive()):
            Vilib.qrcode_display_thread = threading.Thread(
                name='qrcode_display',
                target=Vilib.display_qrcode_work
            )
            Vilib.qrcode_display_thread.daemon = True
            Vilib.qrcode_display_thread.start()

    # =================================================================
    # Image Classification
    # =================================================================
    @staticmethod
    def image_classify_switch(flag=False):
        from .image_classification import image_classification_obj_parameter
        Vilib.image_classify_sw = flag
        Vilib.image_classification_obj_parameter = image_classification_obj_parameter

    @staticmethod
    def image_classify_set_model(path):
        if not os.path.exists(path):
            raise ValueError('incorrect model path')
        Vilib.image_classification_model = path

    @staticmethod
    def image_classify_set_labels(path):
        if not os.path.exists(path):
            raise ValueError('incorrect labels path')
        Vilib.image_classification_labels = path

    @staticmethod
    def image_classify_fuc(img):
        if Vilib.image_classify_sw:
            from .image_classification import classify_image
            img = classify_image(
                image=img,
                model=Vilib.image_classification_model,
                labels=Vilib.image_classification_labels
            )
        return img

    # =================================================================
    # Objects Detection
    # =================================================================
    @staticmethod
    def object_detect_switch(flag=False):
        Vilib.objects_detect_sw = flag
        if Vilib.objects_detect_sw == True:
            from .objects_detection import object_detection_list_parameter
            Vilib.object_detection_list_parameter = object_detection_list_parameter

    @staticmethod
    def object_detect_set_model(path):
        if not os.path.exists(path):
            raise ValueError('incorrect model path')
        Vilib.objects_detection_model = path

    @staticmethod
    def object_detect_set_labels(path):
        if not os.path.exists(path):
            raise ValueError('incorrect labels path')
        Vilib.objects_detection_labels = path

    @staticmethod
    def object_detect_fuc(img):
        if Vilib.objects_detect_sw:
            from .objects_detection import detect_objects
            img = detect_objects(
                image=img,
                model=Vilib.objects_detection_model,
                labels=Vilib.objects_detection_labels
            )
        return img

    # =================================================================
    # Hands Detection
    # =================================================================
    @staticmethod
    def hands_detect_switch(flag=False):
        from .hands_detection import DetectHands
        Vilib.detect_hands = DetectHands()
        Vilib.hands_detect_sw = flag

    @staticmethod
    def hands_detect_fuc(img):
        if Vilib.hands_detect_sw:
            img, Vilib.detect_obj_parameter['hands_joints'] = Vilib.detect_hands.work(image=img)
        return img

    # =================================================================
    # Pose Detection
    # =================================================================
    @staticmethod
    def pose_detect_switch(flag=False):
        from .pose_detection import DetectPose
        Vilib.pose_detect = DetectPose()
        Vilib.pose_detect_sw = flag

    @staticmethod
    def pose_detect_fuc(img):
        if Vilib.pose_detect_sw and hasattr(Vilib, "pose_detect"):
            img, Vilib.detect_obj_parameter['body_joints'] = Vilib.pose_detect.work(image=img)
        return img
