import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import os
import numpy as np
import cv2
import hailo
import csv
import configparser
import shutil
import time
import threading
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

        # Lire les paramètres depuis le fichier config.ini
        config = configparser.ConfigParser()
        config.read("config.ini")

        # Lire le nom de base du fichier et ajouter la date et l'heure du démarrage
        base_filename = config.get("CSV", "filename", fallback="detection.csv")
        name, ext = os.path.splitext(base_filename)

        # Ajouter la date et l'heure au nom du fichier
        start_time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.csv_filename = f"{name}_{start_time_str}{ext}"

        # Lire les chemins pour le fichier principal et de sauvegarde
        self.usb_dir = config.get("CSV", "path", fallback="/media/ptrans/USB DISK/csv")
        self.backup_dir = config.get("CSV", "backup_path", fallback=None)

        # Initialiser les chemins de fichiers
        self.csv_file_path = "temp.csv"  # Fichier temporaire
        self.default_detection_path = self.csv_filename
        self.detection_file_path = self.get_detection_file_path()

        self.detected_people = {}

        # Supprimer le fichier temporaire existant
        if os.path.exists(self.csv_file_path):
            os.remove(self.csv_file_path)

        # Créer le fichier temporaire
        with open(self.csv_file_path, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Track ID", "Start Time", "End Time"])

        # Supprimer l’ancien fichier final s’il existe
        if os.path.exists(self.detection_file_path):
            os.remove(self.detection_file_path)

        # Créer le fichier final
        with open(self.detection_file_path, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Track ID", "Start Time", "End Time"])

        # Démarrer le thread de copie périodique
        self.copy_thread = threading.Thread(target=self.copy_csv_periodically)
        self.copy_thread.daemon = True
        self.copy_thread.start()

    def get_detection_file_path(self):
        """Retourne le chemin de sauvegarde principal ou secondaire"""
        if os.path.isdir(self.usb_dir):
            os.makedirs(self.usb_dir, exist_ok=True)
            return os.path.join(self.usb_dir, self.csv_filename)
        elif self.backup_dir and os.path.isdir(self.backup_dir):
            # Si le répertoire USB n'existe pas, on sauvegarde dans le répertoire de sauvegarde
            return os.path.join(self.backup_dir, self.csv_filename)
        else:
            # Sinon, retourne le fichier dans le répertoire courant
            return self.csv_filename

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
            with open(self.csv_file_path, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    track_id,
                    self.detected_people[track_id]["start_time"],
                    end_time
                ])

    def get_detected_people(self):
        return self.detected_people

    def remove_inactive_people(self, active_ids):
        ids_to_remove = [tid for tid in self.detected_people if tid not in active_ids]
        for tid in ids_to_remove:
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.update_detection_end_time(tid, end_time)
            del self.detected_people[tid]

    def copy_csv_periodically(self):
        while True:
            time.sleep(60)
            if os.path.exists(self.csv_file_path):
                try:
                    # Copie vers le chemin principal
                    self.detection_file_path = self.get_detection_file_path()
                    shutil.copy(self.csv_file_path, self.detection_file_path)
                    print(f"Copied to main path: {self.detection_file_path}")

                    # Copie vers le chemin de sauvegarde s’il est défini
                    if self.backup_dir and os.path.isdir(self.backup_dir):
                        backup_path = os.path.join(self.backup_dir, self.csv_filename)
                        shutil.copy(self.csv_file_path, backup_path)
                        print(f"Copied to backup path: {backup_path}")

                except Exception as e:
                    print(f"Failed to copy CSV: {e}")

# -----------------------------------------------------------------------------------------------
# Callback function
# -----------------------------------------------------------------------------------------------
def app_callback(pad, info, user_data):
    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK

    user_data.increment()
    string_to_print = f"Frame count: {user_data.get_count()}\n"

    format, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and format is not None and width and height:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    active_ids = []
    detection_count = 0
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for detection in detections:
        label = detection.get_label()
        confidence = detection.get_confidence()
        track_id = 0

        if label == "person":
            track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if len(track) == 1:
                track_id = track[0].get_id()

            string_to_print += f"Detection: ID: {track_id} Label: {label} Confidence: {confidence:.2f}\n"
            detection_count += 1

            if track_id not in user_data.get_detected_people():
                user_data.add_detection(track_id, current_time)

            active_ids.append(track_id)

    user_data.remove_inactive_people(active_ids)

    if user_data.use_frame:
        cv2.putText(frame, f"Detections: {detection_count}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"{user_data.new_function()} {user_data.new_variable}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    print(string_to_print)
    return Gst.PadProbeReturn.OK

# -----------------------------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------------------------
if __name__ == "__main__":
    user_data = user_app_callback_class()
    app = GStreamerDetectionApp(app_callback, user_data)
    app.run()
