import cv2
import json
import time
import threading
import hashlib
from functools import wraps
from ultralytics import YOLO
import paho.mqtt.client as mqtt
from flask import Flask, Response, request, abort, redirect, url_for, session

# ===== Configuration =====
THINGSBOARD_HOST = "smart.agb.com.mm"
ACCESS_TOKEN = "KEteHlV0FhZqdGNkQ3nK"  # Replace with your token
MODEL = "yolov8x.pt"
CAMERA_SOURCE = 0  # 0 for webcam or RTSP URL
SECRET_KEY = "297e47d152790ef0266bf693058fcf0e"  # Change this!
ADMIN_USER = "admin"
ADMIN_PASS = hashlib.sha256("AGB@12345".encode()).hexdigest()  # Hashed password

# ===== Flask Setup =====
app = Flask(__name__)
app.secret_key = SECRET_KEY

# ===== Security Decorator =====
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ===== Authentication Routes =====
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        if username == ADMIN_USER and password == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(url_for('video_feed'))
        else:
            return "Invalid credentials", 401
    return '''
        <form method="post">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
    '''

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# ===== MQTT Setup =====
def setup_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(ACCESS_TOKEN)
    client.connect(THINGSBOARD_HOST, 1883, 60)
    client.loop_start()
    return client

mqtt_client = setup_mqtt()

# ===== Video Streaming =====
latest_frame = None
frame_lock = threading.Lock()

def generate_frames():
    global latest_frame
    while True:
        with frame_lock:
            if latest_frame is None:
                continue
            ret, buffer = cv2.imencode('.jpg', latest_frame)
            frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video')
@login_required
def video_feed():
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

# ===== Detection Loop =====
def detection_loop():
    global latest_frame
    
    cap = cv2.VideoCapture(CAMERA_SOURCE)
    model = YOLO(MODEL)
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        results = model(frame, conf=0.5, verbose=False)
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)
        
        with frame_lock:
            latest_frame = frame
        
        if cv2.waitKey(1) == ord('q'):
            break
    
    cap.release()

# ===== Telemetry Thread =====
def send_telemetry():
    while True:
        if mqtt_client:
            telemetry = {"active": True, "timestamp": int(time.time())}
            mqtt_client.publish('v1/devices/me/telemetry', json.dumps(telemetry))
        time.sleep(5)

# ===== Main Execution =====
if __name__ == "__main__":
    # Start threads
    threading.Thread(target=detection_loop, daemon=True).start()
    threading.Thread(target=send_telemetry, daemon=True).start()
    
    # Start Flask with HTTPS (for production)
    app.run(host='0.0.0.0', port=5000, ssl_context='adhoc')  # Remove ssl_context for development
