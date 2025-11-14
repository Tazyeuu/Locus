import cv2
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("Error: Kamera tidak dapat dibuka.")
    exit()
while True:
    ret, frame = cap.read()
    if not ret:
        print("Error: Gagal membaca frame.")
        break
    cv2.imshow('Test Kamera', frame)
    if cv2.waitKey(1) == ord('q'):
        break
cap.release()
cv2.destroyAllWindows()