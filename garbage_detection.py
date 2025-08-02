# 실행 전 라이브러리 설치 필요
# pip install ultralytics opencv-python torch torchvision requests

# 다음 명령어로 실행
# source venv/bin/activate && python garbage_detection.py

import base64
import time
from collections import defaultdict, deque
from datetime import datetime

import cv2
import requests
import torch
from ultralytics import YOLO


class GarbageDetector:
    def __init__(self, model_path='yolo11m.pt', server_url="http://localhost:8000"):

        self.model = YOLO(model_path)
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1440)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 30)  # 높은 프레임 레이트 설정
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 버퍼 크기 최소화로 지연 감소

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Using device: {self.device}")

        # 서버 연결 설정
        self.server_url = server_url
        self.server_connected = False
        self.test_server_connection()

        # 감지 통계
        self.detection_stats = {
            'total_detections': 0,
            'last_detection_time': None,
            'current_risk_score': 0,
            'current_risk_level': 'safe'
        }

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

        self.confidence_threshold = 0.1  # 낮은 신뢰도로 더 많은 객체 감지
        self.detection_history = defaultdict(lambda: deque(maxlen=30))  # 1초 * 30fps = 30프레임으로 단축
        self.stable_detections = {}
        self.min_detection_frames = 1  # 1프레임만으로도 즉시 감지
        self.max_missing_frames = 3  # 빠른 객체 제거로 겹침 방지
        self.frame_skip = 0
        self.process_every_n_frames = 1  # 매 프레임마다 처리로 더 빠른 인식
        self.last_stable_detections = []
        
        # 겹쳐진 객체 감지를 위한 추가 설정
        self.overlap_threshold = 0.3  # 더 낮은 겹침 임계값으로 더 많은 객체 허용
        self.multi_scale_detection = True

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
                timeout=1  # 더 빠른 응답
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('significant_change', False):
                    print(f"🚨 위험도 변화: {result.get('risk_score', 0):.1f}% ({result.get('risk_level', 'safe')})")
                elif result.get('duplicate', False):
                    print(f"🔄 중복 감지 무시")
                return result
            else:
                print(f"❌ 서버 응답 오류: {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            print("⏰ 서버 응답 시간 초과")
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
            # 프레임 크기 축소로 전송 속도 향상
            resized_frame = cv2.resize(frame, (320, 240))
            ret, buffer = cv2.imencode('.jpg', resized_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])  # 품질 향상하되 크기 축소
            if not ret:
                return False

            frame_base64 = base64.b64encode(buffer).decode('utf-8')

            response = requests.post(
                f"{self.server_url}/update_frame",
                json={"frame": frame_base64},
                timeout=0.05  # 더 짧은 타임아웃으로 빠른 응답
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
                    distance = ((center1[0] - center2[0]) ** 2 + (center1[1] - center2[1]) ** 2) ** 0.5

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

                # 감지가 처음 확정될 때마다 서버로 전송
                if sum(self.detection_history[track_id]) == self.min_detection_frames:
                    box = track_info['box']
                    area = (box[2] - box[0]) * (box[3] - box[1])

                    if 'category' in track_info:
                        garbage_type = f"{track_info['category']}_{track_info['class_name']}"
                    else:
                        garbage_type = f"other_{track_info['class_name']}"

                    detection_data = {
                        "timestamp": datetime.now().isoformat(),
                        "garbage_type": garbage_type,
                        "confidence": float(track_info['confidence']),
                        "bbox": [int(box[0]), int(box[1]), int(box[2]), int(box[3])],
                        "area": float(area),
                        "location": "main_pipe"
                    }

                    # 백그라운드에서 서버로 전송 (메인 루프에 영향 없도록)
                    import threading
                    def send_async():
                        result = self.send_detection_to_server(detection_data)
                        if result:
                            print(f"📤 감지 전송: {garbage_type} (신뢰도: {detection_data['confidence']:.2f})")
                            # 통계 업데이트
                            self.detection_stats['total_detections'] += 1
                            self.detection_stats['last_detection_time'] = datetime.now()
                            if isinstance(result, dict):
                                self.detection_stats['current_risk_score'] = result.get('risk_score', 0)
                                self.detection_stats['current_risk_level'] = result.get('risk_level', 'safe')
                                print(
                                    f"📊 위험도 업데이트: {result.get('risk_score', 0):.1f}% ({result.get('risk_level', 'safe')})")
                        else:
                            print(f"❌ 서버 응답 없음: {garbage_type}")

                    thread = threading.Thread(target=send_async)
                    thread.daemon = True
                    thread.start()

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
        # 이미지 품질 개선으로 겹쳐진 객체 인식 향상
        enhanced_frame = cv2.convertScaleAbs(frame, alpha=1.1, beta=10)  # 대비와 밝기 향상
        
        # 겹쳐진 쓰레기 전체 인식을 위한 설정
        # 멀티스케일 감지: 다양한 크기로 감지 시도
        results = self.model(enhanced_frame, device=self.device, conf=0.1, iou=0.2, verbose=False, 
                           agnostic_nms=True, max_det=100, augment=True)

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

                        if class_id in self.taco_classes and class_id != 0:  # 알루미늄 호일(0번) 제외
                            class_name, category, color = self.get_class_info(class_id)
                            label = f"{category.upper()}: {class_name} ({confidence:.2f})"
                            current_detections.append(
                                ([x1, y1, x2, y2], confidence, class_id, class_name, label, category, color))
                        else:
                            model_class_name = self.model.names.get(class_id, f'Unknown_{class_id}')
                            # 사람(person) 클래스 제외
                            if model_class_name.lower() != 'person':
                                label = f"OTHER: {model_class_name} ({confidence:.2f})"
                                current_detections.append(
                                    ([x1, y1, x2, y2], confidence, class_id, model_class_name, label, 'other',
                                     (128, 128, 128)))

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
            # 박스만 그리고 텍스트는 표시하지 않음
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), box_color, 2)

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

            # 서버로 현재 프레임 전송 (웹 대시보드용) - 성능 최적화
            if frame_count % 5 == 0 and self.server_connected:  # 5프레임마다 전송으로 딜레이 감소
                import threading
                try:
                    # 쓰레드 풀 대신 간단한 비동기 호출로 변경
                    def send_frame_async():
                        self.send_frame_to_server(annotated_frame)

                    thread = threading.Thread(target=send_frame_async)
                    thread.daemon = True
                    thread.start()
                except:
                    pass  # 쓰레드 생성 실패시 무시

            # 주기적 서버 상태 확인
            if time.time() - last_status_check > 30:  # 30초마다
                self.test_server_connection()
                last_status_check = time.time()

            # 상태 정보 표시
            status_color = (0, 255, 0) if self.server_connected else (0, 0, 255)
            status_text = f"Server: {'Connected' if self.server_connected else 'Disconnected'}"
            cv2.putText(annotated_frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
            cv2.putText(annotated_frame, f"Detections: {self.detection_stats['total_detections']}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(annotated_frame,
                        f"Risk: {self.detection_stats['current_risk_score']:.1f}% ({self.detection_stats['current_risk_level']})",
                        (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(annotated_frame, "Press ESC to exit", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255),
                        2)

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

    # 모델 선택 (가벼운 모델로 변경)
    model_path = 'yolo11m.pt'  # 가벼운 nano 모델

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