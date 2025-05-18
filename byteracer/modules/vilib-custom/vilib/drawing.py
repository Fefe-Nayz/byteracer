"""
This file extends vilib with a drawing capability for rectangles and text.
It's designed to be used by external modules like AICameraCameraManager to display
YOLO detections or other overlays on the camera feed.
"""

import cv2
import numpy as np
import threading

# Storage for drawing requests from external modules
drawing_requests = []
drawing_lock = threading.Lock()

def reset_drawings():
    """Clear all drawing requests."""
    with drawing_lock:
        drawing_requests.clear()

def add_rectangle(x, y, width, height, color=(0, 255, 0), thickness=2, label=None, label_color=None, font_scale=0.5, label_thickness=1, label_position='top'):
    """
    Add a rectangle to be drawn on the camera feed.
    
    Args:
        x (int): Top-left x coordinate
        y (int): Top-left y coordinate
        width (int): Width of rectangle
        height (int): Height of rectangle
        color (tuple): BGR color tuple, e.g. (0, 255, 0) for green
        thickness (int): Line thickness
        label (str, optional): Text label to draw with the rectangle
        label_color (tuple, optional): BGR color tuple for the label text, if None uses same as rectangle
        font_scale (float, optional): Font scale for the label
        label_thickness (int, optional): Text thickness for the label
        label_position (str, optional): Position of label, either 'top' (above rectangle) or 'inside' (on top border)
    """
    with drawing_lock:
        request = {
            'type': 'rectangle',
            'x': x,
            'y': y,
            'width': width,
            'height': height,
            'color': color,
            'thickness': thickness
        }
        
        # Add label information if provided
        if label is not None:
            request['label'] = label
            request['label_color'] = label_color if label_color is not None else color
            request['font_scale'] = font_scale
            request['label_thickness'] = label_thickness
            request['label_position'] = label_position
            
        drawing_requests.append(request)

def add_text(text, x, y, color=(0, 255, 0), font_scale=0.5, thickness=1):
    """
    Add text to be drawn on the camera feed.
    
    Args:
        text (str): Text to display
        x (int): Bottom-left x coordinate of text
        y (int): Bottom-left y coordinate of text
        color (tuple): BGR color tuple
        font_scale (float): Font scale
        thickness (int): Text thickness
    """
    with drawing_lock:
        drawing_requests.append({
            'type': 'text',
            'text': text,
            'x': x,
            'y': y,
            'color': color,
            'font_scale': font_scale,
            'thickness': thickness
        })

def draw_overlay(image):
    """
    Process all drawing requests and apply them to the image.
    
    Args:
        image (numpy.ndarray): Image to draw on
    
    Returns:
        numpy.ndarray: Image with drawings applied
    """
    if not drawing_requests:
        return image
        
    # Make a copy to avoid modifying the original image
    output_image = image.copy()
    
    with drawing_lock:
        for request in drawing_requests:
            if request['type'] == 'rectangle':
                # Draw rectangle: (x, y, width, height) -> (x1, y1, x2, y2)
                x1 = request['x']
                y1 = request['y']
                x2 = x1 + request['width']
                y2 = y1 + request['height']
                cv2.rectangle(
                    output_image, 
                    (x1, y1), 
                    (x2, y2), 
                    request['color'], 
                    request['thickness']
                )
                
                # Add label if it exists
                if 'label' in request:
                    label = request['label']
                    font_scale = request['font_scale']
                    label_color = request['label_color']
                    label_thickness = request['label_thickness']
                    
                    # Get text size to properly position
                    (text_width, text_height), baseline = cv2.getTextSize(
                        label, 
                        cv2.FONT_HERSHEY_SIMPLEX, 
                        font_scale, 
                        label_thickness
                    )
                    
                    # Position text based on preference
                    if request['label_position'] == 'top':
                        # Position above the rectangle
                        text_x = x1
                        text_y = y1 - baseline - 5  # 5 pixels padding
                    else:  # 'inside'
                        # Position at the top of the rectangle
                        text_x = x1
                        text_y = y1 + text_height + 5  # 5 pixels padding
                    
                    # Optional: Draw a background for better text visibility
                    cv2.rectangle(
                        output_image,
                        (text_x, text_y - text_height - baseline),
                        (text_x + text_width, text_y + baseline),
                        label_color,
                        -1  # Filled rectangle
                    )
                    
                    # Draw the text
                    cv2.putText(
                        output_image,
                        label,
                        (text_x, text_y - baseline),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale,
                        (0, 0, 0),  # Black text for contrast
                        label_thickness,
                        cv2.LINE_AA
                    )
                    
            elif request['type'] == 'text':
                # Draw text
                cv2.putText(
                    output_image,
                    request['text'],
                    (request['x'], request['y']),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    request['font_scale'],
                    request['color'],
                    request['thickness'],
                    cv2.LINE_AA
                )
    
    return output_image
