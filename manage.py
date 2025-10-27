import os
import cv2
import numpy as np
from datetime import datetime
from flask import Flask, render_template, Response, request, redirect, url_for
import threading, time, math
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from playsound import playsound
from pathlib import Path

app = Flask(__name__)

# ==========================
# CONFIGURATION
# ==========================
CONFIDENCE_THRESHOLD = 0.05
NMS_SCORE_THRESHOLD = 0.1
NMS_IOU_THRESHOLD = 0.4

UNATTENDED_SECONDS = 10
MOVEMENT_THRESHOLD_PX = 40
SOUND_FILE = "alert.wav"

SENDER_EMAIL = "sreejakodali12@gmail.com"
SENDER_APP_PASSWORD = "jjpzfpgpgspuxzdq"

CFG = "yolov3.cfg"
WEIGHTS = "yolov3.weights"
NAMES = "coco.names"

# ==========================
# LOAD YOLO
# ==========================
print("🔍 Loading YOLO model...")
net = cv2.dnn.readNetFromDarknet(CFG, WEIGHTS)
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

layer_names = net.getLayerNames()
out_layers_idx = net.getUnconnectedOutLayers()
if isinstance(out_layers_idx, (list, tuple, np.ndarray)):
    out_layers = [layer_names[i - 1] if isinstance(i, (int, np.integer)) else layer_names[i[0] - 1] for i in out_layers_idx]
else:
    out_layers = [layer_names[i[0] - 1] for i in out_layers_idx]

with open(NAMES) as f:
    LABELS = [line.strip() for line in f.readlines()]

colors = np.random.randint(0, 255, size=(len(LABELS), 3), dtype="uint8")
print("✅ YOLO model loaded successfully")

# ==========================
# GLOBALS
# ==========================
REGISTERED_EMAIL = None
email_lock = threading.Lock()
tracked_objects = {}
tracked_lock = threading.Lock()
next_object_id = 1

def euclidean(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

# ==========================
# EMAIL + SOUND HELPERS
# ==========================
def send_email_with_image(to_email, subject, body, image_path=None):
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                msg.attach(MIMEImage(f.read(), name=os.path.basename(image_path)))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            smtp.send_message(msg)
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ Email failed to {to_email}: {e}")

def play_sound():
    try:
        playsound(SOUND_FILE)
    except Exception as e:
        print("⚠️ Sound play failed:", e)

# ==========================
# ALERT TRIGGER
# ==========================
def trigger_alert(label, frame):
    global REGISTERED_EMAIL
    timestamp = int(time.time())
    fname = f"abandoned_{timestamp}.jpg"
    outpath = os.path.join("static", fname)
    cv2.imwrite(outpath, frame)  # full frame

    threading.Thread(target=play_sound, daemon=True).start()

    with email_lock:
        recipient = REGISTERED_EMAIL
    if recipient:
        subject = f"Abandoned Object Detected: {label}"
        body = f"Detected unattended {label} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
        threading.Thread(target=send_email_with_image, args=(recipient, subject, body, outpath), daemon=True).start()
    else:
        print("ℹ️ No email registered; skipping email.")

# ==========================
# FRAME GENERATOR
# ==========================
def generate_frames():
    global next_object_id, tracked_objects
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Camera not available.")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        now = datetime.now()
        (H, W) = frame.shape[:2]

        blob = cv2.dnn.blobFromImage(frame, 1/255.0, (416,416), swapRB=True, crop=False)
        net.setInput(blob)
        outputs = net.forward(out_layers)

        boxes, confidences, class_ids = [], [], []
        for output in outputs:
            for detection in output:
                scores = detection[5:]
                if len(scores) == 0:
                    continue
                class_id = int(np.argmax(scores))
                confidence = float(scores[class_id])

                # 🟢 Boost backpack confidence slightly
                if LABELS[class_id] == "backpack":
                    confidence += 0.3

                if confidence < CONFIDENCE_THRESHOLD:
                    continue

                box = detection[0:4] * np.array([W, H, W, H])
                (centerX, centerY, width, height) = box.astype("int")
                x = int(centerX - width / 2)
                y = int(centerY - height / 2)

                boxes.append([x, y, int(width), int(height)])
                confidences.append(confidence)
                class_ids.append(class_id)

        idxs = cv2.dnn.NMSBoxes(boxes, confidences, NMS_SCORE_THRESHOLD, NMS_IOU_THRESHOLD)
        detections = []

        if len(idxs) > 0:
            for i in idxs.flatten():
                label = LABELS[class_ids[i]]
                box = boxes[i]
                cx, cy = box[0] + box[2]//2, box[1] + box[3]//2
                detections.append((label, box, (cx, cy), confidences[i]))

        persons = [d for d in detections if d[0] == "person"]

        with tracked_lock:
            MONITORED_CLASSES = {
                "backpack", "handbag", "suitcase", "bottle", "cup",
                "cell phone", "laptop", "mouse", "book"
            }

            for label, box, center, conf in detections:
                if label == "person" or label not in MONITORED_CLASSES:
                    continue

                near_person = any(euclidean(center, p[2]) < 120 for p in persons)
                if near_person:
                    continue

                found = None
                for oid, data in tracked_objects.items():
                    if data["class"] == label and euclidean(center, data["last_center"]) < MOVEMENT_THRESHOLD_PX:
                        found = oid
                        break

                if found:
                    obj = tracked_objects[found]
                    obj["last_seen"] = now
                    obj["last_center"] = center
                    obj["last_box"] = box
                    if obj["stationary_since"] is None:
                        obj["stationary_since"] = now
                else:
                    tracked_objects[next_object_id] = {
                        "class": label,
                        "first_seen": now,
                        "last_seen": now,
                        "last_center": center,
                        "last_box": box,
                        "stationary_since": now,
                        "alert_sent": False
                    }
                    next_object_id += 1

            stale = [oid for oid, d in tracked_objects.items() if (now - d["last_seen"]).total_seconds() > 5]
            for s in stale:
                del tracked_objects[s]

            for oid, d in list(tracked_objects.items()):
                box = d["last_box"]
                x, y, w, h = box
                stationary_since = d["stationary_since"]
                if stationary_since:
                    stationary_seconds = int((now - stationary_since).total_seconds())
                    text = f"⏳ {d['class']} {stationary_seconds}s / {UNATTENDED_SECONDS}s"
                    cv2.putText(frame, text, (20, 40 + 25*oid), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)
                    if not d["alert_sent"] and stationary_seconds >= UNATTENDED_SECONDS:
                        d["alert_sent"] = True
                        print(f"🎒 Unattended alert for {d['class']}")
                        frame_copy = frame.copy()
                        threading.Thread(target=trigger_alert, args=(d["class"], frame_copy), daemon=True).start()

        for label, box, center, conf in detections:
            color = (0,255,0)
            x,y,w,h = box
            cv2.rectangle(frame, (x,y), (x+w,y+h), color, 2)
            cv2.putText(frame, f"{label}: {conf:.2f}", (x, max(20,y-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        ret, buffer = cv2.imencode(".jpg", frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# ==========================
# FLASK ROUTES
# ==========================
@app.route("/")
def index():
    imgs = sorted(Path("static").glob("*.jpg"), key=os.path.getmtime, reverse=True)
    imgs = ["/static/"+i.name for i in imgs if i.name.startswith("abandoned_")]
    return render_template("index.html",
        image1=imgs[0] if len(imgs)>0 else None,
        image2=imgs[1] if len(imgs)>1 else None,
        image3=imgs[2] if len(imgs)>2 else None)

@app.route("/detail/<int:id>")
def detail(id):
    return render_template("detail.html", id=id)

@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/submit", methods=["POST"])
def submit():
    global REGISTERED_EMAIL
    email = request.form.get("email")
    if email:
        with email_lock:
            REGISTERED_EMAIL = email.strip()
        print(f"📧 Email registered for alerts: {REGISTERED_EMAIL}")
    return redirect(url_for("index"))

@app.route("/manual-alert")
def manual_alert():
    print("🚨 Manual alert triggered!")
    threading.Thread(target=play_sound, daemon=True).start()
    with email_lock:
        recipient = REGISTERED_EMAIL
    if recipient:
        subject = "Manual Alert Triggered"
        body = f"A manual alert was triggered at {datetime.now()}."
        threading.Thread(target=send_email_with_image, args=(recipient, subject, body, None), daemon=True).start()
    return redirect(url_for("index"))

# ==========================
# RUN APP
# ==========================
if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    print("✅ Server running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
