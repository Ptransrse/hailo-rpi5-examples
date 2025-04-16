import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import os
import numpy as np
import cv2
import hailo
import csv
from datetime import datetime

from hailo_apps_infra.hailo_rpi_common import (
    get_caps_from_pad,
    get_numpy_from_buffer,
    app_callback_class,
)
from hailo_apps_infra.detection_pipeline import GStreamerDetectionApp

# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        self.new_variable = 42  # New variable example
        self.detected_people = {}  # Track detected people (by track ID)
        self.csv_file_path = "temp.csv"
        
        # Supprimer le fichier CSV existant s'il y en a un
        if os.path.exists(self.csv_file_path):
            os.remove(self.csv_file_path)
        
        # Créer le fichier CSV et écrire les en-têtes
        with open(self.csv_file_path, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Track ID", "Start Time", "End Time"])

    def new_function(self):
        return "The meaning of life is: "

    def add_detection(self, track_id, start_time):
        self.detected_people[track_id] = {
            "start_time": start_time,
            "end_time": None
        }

    def update_detection_end_time(self, track_id, end_time):
        if track_id in self.detected_people:
            self.detected_people[track_id]["end_time"] = end_time
            # Sauvegarder la détection dans le fichier CSV
            with open(self.csv_file_path, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([track_id, self.detected_people[track_id]["start_time"], end_time])

    def get_detected_people(self):
        return self.detected_people

    def remove_inactive_people(self, active_ids):
        """ Remove people from the dictionary who are no longer detected. """
        ids_to_remove = [track_id for track_id in self.detected_people if track_id not in active_ids]
        for track_id in ids_to_remove:
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Date and time format
            self.update_detection_end_time(track_id, end_time)
            del self.detected_people[track_id]


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------
def app_callback(pad, info, user_data):
    # Get the GstBuffer from the probe info
    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK

    # Using the user_data to count the number of frames
    user_data.increment()
    string_to_print = f"Frame count: {user_data.get_count()}\n"

    # Get the caps from the pad
    format, width, height = get_caps_from_pad(pad)

    # If the user_data.use_frame is set to True, we can get the video frame from the buffer
    frame = None
    if user_data.use_frame and format is not None and width is not None and height is not None:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    # Get the detections from the buffer
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # List to track active ids in the current frame
    active_ids = []
    
    # Parse the detections
    detection_count = 0
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Current date and time
    for detection in detections:
        label = detection.get_label()
        bbox = detection.get_bbox()
        confidence = detection.get_confidence()
        
        if label == "person":
            track_id = 0
            track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if len(track) == 1:
                track_id = track[0].get_id()

            string_to_print += (f"Detection: ID: {track_id} Label: {label} Confidence: {confidence:.2f}\n")
            detection_count += 1

            # If the person is detected for the first time, record the start time
            if track_id not in user_data.get_detected_people():
                user_data.add_detection(track_id, current_time)

            # Keep track of active ids
            active_ids.append(track_id)
    
    # Update the end times for people who are no longer detected
    user_data.remove_inactive_people(active_ids)

    if user_data.use_frame:
        cv2.putText(frame, f"Detections: {detection_count}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"{user_data.new_function()} {user_data.new_variable}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    print(string_to_print)
    return Gst.PadProbeReturn.OK


if __name__ == "__main__":
    user_data = user_app_callback_class()
    app = GStreamerDetectionApp(app_callback, user_data)
    app.run()
