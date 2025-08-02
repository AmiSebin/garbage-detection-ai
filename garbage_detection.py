import cv2
import torch
from ultralytics import YOLO

class GarbageDetector:
    def __init__(self, model_path='yolov8s.pt'):

        self.model = YOLO(model_path)
        self.cap = cv2.VideoCapture(0)
        
        # 웹캠 해상도 설정 (성능 최적화를 위해)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # GPU 사용 가능한지 확인
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Using device: {self.device}")
        
        # 쓰레기 관련 클래스 ID들 (COCO 데이터셋 기준)
        # 일반적인 쓰레기로 분류될 수 있는 객체들
        self.garbage_classes = {
            39: 'bottle',           # 병
            40: 'wine glass',       # 와인잔
            41: 'cup',              # 컵
            42: 'fork',             # 포크
            43: 'knife',            # 나이프
            44: 'spoon',            # 숟가락
            45: 'bowl',             # 그릇
            46: 'banana',           # 바나나 (음식 쓰레기)
            47: 'apple',            # 사과 (음식 쓰레기)
            67: 'cell phone',       # 휴대폰 (전자 쓰레기)
            73: 'laptop',           # 노트북 (전자 쓰레기)
            76: 'keyboard',         # 키보드 (전자 쓰레기)
            # 추가적인 클래스들은 필요에 따라 추가 가능
        }
    
    def detect_garbage(self, frame):
        """
        프레임에서 쓰레기 탐지
        
        Args:
            frame: 입력 프레임
            
        Returns:
            annotated_frame: 탐지 결과가 표시된 프레임
        """
        # YOLO 모델로 객체 탐지 수행
        results = self.model(frame, device=self.device, conf=0.3)
        
        # 탐지 결과를 프레임에 그리기
        annotated_frame = frame.copy()
        
        for result in results:
            boxes = result.boxes
            if boxes is not None:
                for box in boxes:
                    # 바운딩 박스 좌표
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    confidence = box.conf[0].cpu().numpy()
                    class_id = int(box.cls[0].cpu().numpy())
                    class_name = self.model.names[class_id]
                    
                    # 쓰레기 관련 객체이거나 모든 객체를 쓰레기로 간주하는 경우
                    # (커스텀 모델을 사용하는 경우 모든 탐지된 객체를 쓰레기로 간주)
                    if class_id in self.garbage_classes or 'best.pt' in str(self.model.ckpt_path):
                        # 바운딩 박스 그리기 (빨간색)
                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                        
                        # 라벨 텍스트 준비
                        if class_id in self.garbage_classes:
                            label = f"Garbage ({self.garbage_classes[class_id]}): {confidence:.2f}"
                        else:
                            label = f"Garbage ({class_name}): {confidence:.2f}"
                        
                        # 라벨 배경 그리기
                        (text_width, text_height), baseline = cv2.getTextSize(
                            label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2
                        )
                        cv2.rectangle(
                            annotated_frame, 
                            (x1, y1 - text_height - 10), 
                            (x1 + text_width, y1), 
                            (0, 0, 255), 
                            -1
                        )
                        
                        # 라벨 텍스트 그리기 (흰색)
                        cv2.putText(
                            annotated_frame, 
                            label, 
                            (x1, y1 - 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 
                            0.5, 
                            (255, 255, 255), 
                            2
                        )
        
        return annotated_frame
    
    def run(self):
        """
        실시간 쓰레기 탐지 실행
        """
        print("쓰레기 탐지를 시작합니다. ESC 키를 눌러 종료하세요.")
        print(f"모델: {self.model.ckpt_path}")
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                print("웹캠에서 프레임을 읽을 수 없습니다.")
                break
            
            # 쓰레기 탐지 수행
            annotated_frame = self.detect_garbage(frame)
            
            # FPS 계산 및 표시
            fps_text = f"Press ESC to exit"
            cv2.putText(
                annotated_frame, 
                fps_text, 
                (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 
                0.7, 
                (255, 255, 255), 
                2
            )
            
            # 결과 표시
            cv2.imshow('Garbage Detection', annotated_frame)
            
            # ESC 키로 종료
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC 키
                break
        
        # 리소스 정리
        self.cap.release()
        cv2.destroyAllWindows()
        print("프로그램이 종료되었습니다.")

def main():
    """
    메인 함수
    """
    # 기본 YOLOv8n 모델 사용 (또는 커스텀 모델 'best.pt' 사용)
    # 커스텀 모델을 사용하려면 아래 주석을 해제하고 모델 경로를 수정하세요
    # detector = GarbageDetector('best.pt')
    
    detector = GarbageDetector('yolov8s.pt')
    detector.run()

if __name__ == "__main__":
    main()