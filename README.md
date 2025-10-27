# Real-Time-Object-Video-Detection-for-Smart-Security-Surveillance
📌 Project Overview
This project is a real-time smart surveillance system built using YOLOv3 (You Only Look Once) and Flask, designed to automatically detect unattended or abandoned objects such as bags, bottles, laptops, and other suspicious items in a live video feed.
It enhances traditional CCTV systems by adding intelligent object monitoring and instant alert mechanisms including:

📧 Email notifications with snapshot images
🔊 Audio alerts using a custom alert sound

🧠 Features
✅ Real-Time Object Detection using YOLOv3
✅ Unattended Object Tracking — detects stationary objects left for a specific duration
✅ Smart Filtering — ignores objects if a person is nearby (e.g., bag being held)
✅ Audio & Email Alerts when unattended objects are detected
✅ Web Interface using Flask for live monitoring
✅ Manual Alert Button for emergency notifications
✅ Automatic Image Saving with timestamped filenames in /static/ folder

🖥️ Tech Stack
Component	Technology
Language	Python 3
Framework	Flask
Deep Learning Model	YOLOv3
Libraries Used	OpenCV, NumPy, smtplib, threading, playsound
Frontend	HTML, CSS (in templates folder)
