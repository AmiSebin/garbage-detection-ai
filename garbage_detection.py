# 실행 전 라이브러리 설치 필요
# pip install ultralytics opencv-python torch torchvision requests

# 다음 명령어로 실행
# source venv/bin/activate && python garbage_detection.py

from collections import defaultdict, deque
import cv2
import torch
import requests
import json
import base64
import time
from datetime import datetime
from ultralytics import YOLO

class GarbageDetector:
    def __init__(self, model_path='yolo11s.pt', server_url="http://localhost:8000"):

        self.model = YOLO(model_path)
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Using device: {self.device}")
        
        # 서버 연결 설정
        self.server_url = server_url
        self.server_connected = False
        self.test_server_connection()
        
        self.taco_classes = {
            0: 'Aluminium foil',
            1: 'Battery',
            2: 'Aluminium blister pack',
            3: 'Carded blister pack',
            4: 'Other plastic bottle',
            5: 'Clear plastic bottle',
            6: 'Glass bottle',
            7: 'Plastic bottle cap',
            8: 'Metal bottle cap',
            9: 'Broken glass',
            10: 'Food Can',
            11: 'Aerosol',
            12: 'Drink can',
            13: 'Toilet tube',
            14: 'Other carton',
            15: 'Egg carton',
            16: 'Drink carton',
            17: 'Corrugated carton',
            18: 'Meal carton',
            19: 'Pizza box',
            20: 'Paper cup',
            21: 'Disposable plastic cup',
            22: 'Foam cup',
            23: 'Glass cup',
            24: 'Other plastic cup',
            25: 'Food waste',
            26: 'Glass jar',
            27: 'Plastic lid',
            28: 'Metal lid',
            29: 'Other plastic',
            30: 'Magazine paper',
            31: 'Tissues',
            32: 'Wrapping paper',
            33: 'Normal paper',
            34: 'Paper bag',
            35: 'Plastified paper bag',
            36: 'Plastic film',
            37: 'Six pack rings',
            38: 'Garbage bag',
            39: 'Other plastic wrapper',
            40: 'Single-use carrier bag',
            41: 'Polypropylene bag',
            42: 'Crisp packet',
            43: 'Spread tub',
            44: 'Tupperware',
            45: 'Disposable food container',
            46: 'Foam food container',
            47: 'Other plastic container',
            48: 'Plastic glooves',
            49: 'Plastic utensils',
            50: 'Pop tab',
            51: 'Rope & strings',
            52: 'Scrap metal',
            53: 'Shoe',
            54: 'Squeezable tube',
            55: 'Plastic straw',
            56: 'Paper straw',
            57: 'Styrofoam piece',
            58: 'Unlabeled litter',
            59: 'Cigarette'
        }
        
        self.category_mapping = {
            'plastic': [4, 5, 7, 21, 24, 27, 29, 36, 37, 39, 40, 41, 44, 47, 48, 49, 55],  # 플라스틱류
            'metal': [0, 8, 10, 11, 12, 28, 50, 52],  # 금속류
            'glass': [6, 9, 23, 26],  # 유리류
            'paper': [13, 14, 15, 16, 17, 18, 19, 20, 30, 31, 32, 33, 34, 35, 56],  # 종이류
            'food_container': [22, 25, 42, 43, 45, 46, 53, 54, 57],  # 식품용기류
            'other': [1, 2, 3, 38, 51, 58, 59]  # 기타
        }
        
        self.confidence_threshold = 0.25
        self.detection_history = defaultdict(lambda: deque(maxlen=5))
        self.stable_detections = {}
        self.min_detection_frames = 2
        self.max_missing_frames = 3
        self.frame_skip = 0
        self.process_every_n_frames = 2
        self.last_stable_detections = []
        
        self.category_colors = {
            'plastic': (0, 165, 255),
            'metal': (0, 255, 255),
            'glass': (255, 0, 255),
            'paper': (0, 255, 0),
            'food_container': (255, 0, 0),
            'other': (128, 128, 128)
        }
    
    def test_server_connection(self):
        """FastAPI 서버 연결 테스트"""
        try:
            response = requests.get(f"{self.server_url}/health", timeout=3)
            if response.status_code == 200:
                self.server_connected = True
                print(f"✅ 서버 연결 성공: {self.server_url}")
                print(f"📊 대시보드: {self.server_url}")
            else:
                print(f"❌ 서버 응답 오류: {response.status_code}")
                self.server_connected = False
        except Exception as e:
            print(f"❌ 서버 연결 실패: {e}")
            print(f"💡 서버를 먼저 실행하세요: python backend/app.py")
            self.server_connected = False
    
    def send_detection_to_server(self, detection_data):
        """감지 데이터를 FastAPI 서버로 전송"""
        if not self.server_connected:
            return False
            
        try:
            response = requests.post(
                f"{self.server_url}/detect",
                json=detection_data,
                timeout=2
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('significant_change', False):
                    print(f"🚨 위험도 변화: {result.get('risk_score', 0):.1f}% ({result.get('risk_level', 'safe')})")
                return result
            else:
                return False
                
        except requests.exceptions.Timeout:
            return False
        except Exception as e:
            print(f"❌ 서버 전송 오류: {e}")
            self.test_server_connection()
            return False
    
    def send_frame_to_server(self, frame):
        """현재 프레임을 서버로 전송 (비디오 스트리밍용)"""
        if not self.server_connected:
            return False
            
        try:
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ret:
                return False
            
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            
            response = requests.post(
                f"{self.server_url}/update_frame",
                json={"frame": frame_base64},
                timeout=0.5
            )
            
            return response.status_code == 200
            
        except:
            return False
    
    
    def update_tracking(self, current_detections):
        for detection in current_detections:
            if len(detection) == 7:
                box, confidence, class_id, class_name, label, category, color = detection
            else:
                box, confidence, class_id, class_name, label = detection
            best_match_id = None
            
            for track_id, track_info in list(self.stable_detections.items())[:10]:
                if track_info['class_id'] == class_id:
                    center1 = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                    center2 = ((track_info['box'][0] + track_info['box'][2]) / 2, 
                              (track_info['box'][1] + track_info['box'][3]) / 2)
                    distance = ((center1[0] - center2[0])**2 + (center1[1] - center2[1])**2)**0.5
                    
                    if distance < 100:
                        best_match_id = track_id
                        break
            
            if best_match_id:
                detection_data = {'box': box, 'confidence': confidence, 'missing_frames': 0}
                if len(detection) >= 7:
                    detection_data.update({'category': detection[5], 'color': detection[6]})
                self.stable_detections[best_match_id].update(detection_data)
                self.detection_history[best_match_id].append(True)
            else:
                new_id = len(self.stable_detections)
                detection_data = {
                    'box': box, 'confidence': confidence, 'class_id': class_id,
                    'class_name': class_name, 'label': label, 'missing_frames': 0
                }
                if len(detection) >= 7:
                    detection_data.update({'category': detection[5], 'color': detection[6]})
                
                self.stable_detections[new_id] = detection_data
                self.detection_history[new_id].append(True)
        
        to_remove = [track_id for track_id, track_info in self.stable_detections.items()
                    if track_info['missing_frames'] > self.max_missing_frames]
        
        for track_id in to_remove:
            del self.stable_detections[track_id]
            del self.detection_history[track_id]
        
        for track_id in self.stable_detections:
            if track_id not in [idx for idx, _ in enumerate(current_detections)]:
                self.stable_detections[track_id]['missing_frames'] += 1
                self.detection_history[track_id].append(False)
        
        stable_results = []
        for track_id, track_info in self.stable_detections.items():
            if sum(self.detection_history[track_id]) >= self.min_detection_frames:
                result = (track_info['box'], track_info['confidence'], track_info['class_id'],
                         track_info['class_name'], track_info['label'])
                if 'category' in track_info and 'color' in track_info:
                    result = result + (track_info['category'], track_info['color'])
                stable_results.append(result)
        return stable_results
    
    def get_category_for_class(self, class_id):
        for category, class_ids in self.category_mapping.items():
            if class_id in class_ids:
                return category
        return 'other'
    
    def get_class_info(self, class_id):
        class_name = self.taco_classes.get(class_id, f'Unknown_{class_id}')
        category = self.get_category_for_class(class_id)
        color = self.category_colors.get(category, (128, 128, 128))
        return class_name, category, color
    
    def detect_garbage(self, frame):
        results = self.model(frame, device=self.device, conf=0.2, verbose=False)
        
        self.frame_skip += 1
        if self.frame_skip % self.process_every_n_frames != 0:
            if hasattr(self, 'last_stable_detections'):
                stable_detections = self.last_stable_detections
            else:
                stable_detections = []
        else:
            current_detections = []
            
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                        confidence = float(box.conf[0].cpu().numpy())
                        class_id = int(box.cls[0].cpu().numpy())
                        class_name = self.model.names[class_id]
                        
                        if class_id in self.taco_classes:
                            class_name, category, color = self.get_class_info(class_id)
                            label = f"{category.upper()}: {class_name} ({confidence:.2f})"
                            current_detections.append(([x1, y1, x2, y2], confidence, class_id, class_name, label, category, color))
                            
                            # 서버로 감지 데이터 전송
                            area = (x2 - x1) * (y2 - y1)
                            detection_data = {
                                "timestamp": datetime.now().isoformat(),
                                "garbage_type": f"{category}_{class_name}",
                                "confidence": float(confidence),
                                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                                "area": float(area),
                                "location": "main_pipe"
                            }
                            self.send_detection_to_server(detection_data)
                        else:
                            model_class_name = self.model.names.get(class_id, f'Unknown_{class_id}')
                            label = f"OTHER: {model_class_name} ({confidence:.2f})"
                            current_detections.append(([x1, y1, x2, y2], confidence, class_id, model_class_name, label, 'other', (128, 128, 128)))
                            
                            # 서버로 감지 데이터 전송
                            area = (x2 - x1) * (y2 - y1)
                            detection_data = {
                                "timestamp": datetime.now().isoformat(),
                                "garbage_type": f"other_{model_class_name}",
                                "confidence": float(confidence),
                                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                                "area": float(area),
                                "location": "main_pipe"
                            }
                            self.send_detection_to_server(detection_data)
            
            stable_detections = self.update_tracking(current_detections)
            self.last_stable_detections = stable_detections
        
        return self._draw_detections(frame, stable_detections)
    
    def _draw_detections(self, frame, detections):
        annotated_frame = frame.copy()
        
        for detection in detections:
            if len(detection) == 7:
                box, confidence, class_id, class_name, label, category, box_color = detection
            else:
                box, confidence, class_id, class_name, label = detection
                box_color = (0, 0, 255)
            
            x1, y1, x2, y2 = box
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), box_color, 2)
            
            (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv2.rectangle(annotated_frame, (x1, y1 - text_height - 10), (x1 + text_width, y1), box_color, -1)
            cv2.putText(annotated_frame, str(label), (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        
        return annotated_frame
    
    def run(self):
        print("쓰레기 탐지를 시작합니다. ESC 키를 눌러 종료하세요.")
        print(f"모델: {self.model.ckpt_path}")
        print("📋 사용법:")
        print("   - ESC: 프로그램 종료")
        print("   - R: 서버 재연결")
        print("   - S: 서버 상태 확인")
        
        frame_count = 0
        last_status_check = time.time()
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                print("웹캠에서 프레임을 읽을 수 없습니다.")
                break
            
            annotated_frame = self.detect_garbage(frame)
            
            # 서버로 현재 프레임 전송 (웹 대시보드용)
            if frame_count % 3 == 0:  # 3프레임마다 전송 (성능 최적화)
                self.send_frame_to_server(annotated_frame)
            
            # 주기적 서버 상태 확인
            if time.time() - last_status_check > 30:  # 30초마다
                self.test_server_connection()
                last_status_check = time.time()
            
            # 상태 정보 표시
            status_text = f"Server: {'Connected' if self.server_connected else 'Disconnected'}"
            cv2.putText(annotated_frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(annotated_frame, "Press ESC to exit", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            cv2.imshow('Garbage Detection', annotated_frame)
            
            # 키 입력 처리
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC 키
                break
            elif key == ord('r') or key == ord('R'):  # R 키
                print("🔄 서버 재연결 시도...")
                self.test_server_connection()
            elif key == ord('s') or key == ord('S'):  # S 키
                print("📊 서버 상태 확인...")
                self.test_server_connection()
            
            frame_count += 1
        
        self.cap.release()
        cv2.destroyAllWindows()
        print("프로그램이 종료되었습니다.")

def main():
    print("🚰 하수도 막힘 감지 AI 시스템")
    print("=" * 50)
    
    # 모델 선택
    model_path = 'yolo11m.pt'  # 기본 모델
    
    # 커스텀 모델이 있다면 사용
    import os
    if os.path.exists('best.pt'):
        model_path = 'best.pt'
        print("🎯 커스텀 모델을 사용합니다: best.pt")
    else:
        print("🔧 기본 YOLO 모델을 사용합니다: yolo11m.pt")
    
    # 감지기 초기화 및 실행
    detector = GarbageDetector(model_path)
    detector.run()

if __name__ == "__main__":
    main()