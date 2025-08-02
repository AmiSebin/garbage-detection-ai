"""
통합 하수구 쓰레기 감지 및 자동 덮개 제어 시스템
- 쓰레기 감지 (YOLO + 웹캠)
- 위험도 분석 (FastAPI 백엔드)  
- MODI Plus 자동 덮개 제어
"""

import os
import sys
import time
import threading
import subprocess
from datetime import datetime

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    from modi_sewer_controller import MODISewerController
    MODI_CONTROLLER_AVAILABLE = True
except ImportError as e:
    print(f"❌ MODI 컨트롤러를 불러올 수 없습니다: {e}")
    MODI_CONTROLLER_AVAILABLE = False


class IntegratedSewerSystem:
    """통합 하수구 관리 시스템"""
    
    def __init__(self):
        self.backend_process = None
        self.detection_process = None
        self.modi_controller = None
        self.system_running = False
        
        # 설정값
        self.danger_threshold = 70.0  # 위험도 임계값 (%)
        self.server_url = "http://localhost:8000"
        self.backend_port = 8000
        
    def log_message(self, message: str, level: str = "INFO"):
        """통합 시스템 로그 메시지"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        colors = {
            "INFO": "\033[96m",     # 시안색
            "SUCCESS": "\033[92m",  # 초록색
            "WARNING": "\033[93m",  # 노란색
            "ERROR": "\033[91m",    # 빨간색
            "SYSTEM": "\033[95m"    # 마젠타색
        }
        color = colors.get(level, "\033[0m")
        reset = "\033[0m"
        print(f"{color}[통합시스템 {timestamp}] {level}: {message}{reset}")
        
    def start_backend_server(self):
        """FastAPI 백엔드 서버 시작"""
        self.log_message("FastAPI 백엔드 서버를 시작합니다...", "SYSTEM")
        
        try:
            backend_path = os.path.join(current_dir, "backend", "app.py")
            if not os.path.exists(backend_path):
                self.log_message("backend/app.py 파일을 찾을 수 없습니다.", "ERROR")
                return False
                
            # 백엔드 서버 실행
            self.backend_process = subprocess.Popen([
                sys.executable, backend_path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # 서버 시작 대기
            self.log_message("서버 시작을 기다리는 중...", "INFO")
            time.sleep(5)
            
            # 서버 상태 확인
            import requests
            try:
                response = requests.get(f"{self.server_url}/health", timeout=3)
                if response.status_code == 200:
                    self.log_message("✅ 백엔드 서버가 성공적으로 시작되었습니다.", "SUCCESS")
                    return True
                else:
                    self.log_message(f"서버 응답 오류: {response.status_code}", "ERROR")
                    return False
            except Exception as e:
                self.log_message(f"서버 연결 확인 실패: {e}", "ERROR")
                return False
                
        except Exception as e:
            self.log_message(f"백엔드 서버 시작 오류: {e}", "ERROR")
            return False
    
    def start_garbage_detection(self):
        """쓰레기 감지 시스템 시작"""
        self.log_message("쓰레기 감지 시스템을 시작합니다...", "SYSTEM")
        
        try:
            detection_path = os.path.join(current_dir, "garbage_detection.py")
            if not os.path.exists(detection_path):
                self.log_message("garbage_detection.py 파일을 찾을 수 없습니다.", "ERROR")
                return False
            
            # 감지 시스템을 별도 스레드에서 실행 (비블로킹)
            def run_detection():
                try:
                    import subprocess
                    self.detection_process = subprocess.Popen([
                        sys.executable, detection_path
                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    
                    # 프로세스 완료 대기
                    self.detection_process.wait()
                    
                except Exception as e:
                    self.log_message(f"감지 시스템 실행 오류: {e}", "ERROR")
            
            detection_thread = threading.Thread(target=run_detection)
            detection_thread.daemon = True
            detection_thread.start()
            
            self.log_message("✅ 쓰레기 감지 시스템이 시작되었습니다.", "SUCCESS")
            return True
            
        except Exception as e:
            self.log_message(f"감지 시스템 시작 오류: {e}", "ERROR")
            return False
    
    def start_modi_controller(self):
        """MODI Plus 컨트롤러 시작"""
        if not MODI_CONTROLLER_AVAILABLE:
            self.log_message("MODI 컨트롤러를 사용할 수 없습니다.", "WARNING")
            return False
            
        self.log_message("MODI Plus 컨트롤러를 초기화합니다...", "SYSTEM")
        
        try:
            self.modi_controller = MODISewerController(
                server_url=self.server_url,
                danger_threshold=self.danger_threshold
            )
            
            if self.modi_controller.initialize_modi():
                # 모니터링을 별도 스레드에서 시작
                def start_monitoring():
                    self.modi_controller.start_monitoring()
                
                monitoring_thread = threading.Thread(target=start_monitoring)
                monitoring_thread.daemon = True
                monitoring_thread.start()
                
                self.log_message("✅ MODI Plus 컨트롤러가 시작되었습니다.", "SUCCESS")
                return True
            else:
                self.log_message("MODI Plus 초기화에 실패했습니다.", "ERROR")
                return False
                
        except Exception as e:
            self.log_message(f"MODI 컨트롤러 시작 오류: {e}", "ERROR")
            return False
    
    def start_system(self):
        """전체 시스템 시작"""
        self.log_message("🚰 통합 하수구 관리 시스템을 시작합니다!", "SYSTEM")
        self.log_message("=" * 60, "SYSTEM")
        
        # 1단계: 백엔드 서버 시작
        if not self.start_backend_server():
            self.log_message("백엔드 서버 시작에 실패했습니다.", "ERROR")
            return False
        
        # 2단계: 쓰레기 감지 시스템 시작
        if not self.start_garbage_detection():
            self.log_message("쓰레기 감지 시스템 시작에 실패했습니다.", "ERROR")
            return False
        
        # 3단계: MODI Plus 컨트롤러 시작 (선택적)
        modi_success = self.start_modi_controller()
        if not modi_success:
            self.log_message("MODI Plus 없이 시스템을 계속 실행합니다.", "WARNING")
        
        self.system_running = True
        self.log_message("🎯 통합 시스템이 성공적으로 시작되었습니다!", "SUCCESS")
        
        # 시스템 상태 요약
        self.print_system_status()
        
        return True
    
    def print_system_status(self):
        """현재 시스템 상태 출력"""
        self.log_message("📊 시스템 상태 요약:", "INFO")
        self.log_message(f"   🌐 백엔드 서버: {'실행 중' if self.backend_process else '중지'}", "INFO")
        self.log_message(f"   📹 쓰레기 감지: {'실행 중' if self.detection_process else '중지'}", "INFO")
        self.log_message(f"   🤖 MODI Plus: {'연결됨' if self.modi_controller and self.modi_controller.modi_connected else '연결 안됨'}", "INFO")
        self.log_message(f"   🌍 대시보드: {self.server_url}", "INFO")
        self.log_message(f"   ⚠️ 위험도 임계값: {self.danger_threshold}%", "INFO")
    
    def stop_system(self):
        """전체 시스템 중지"""
        self.log_message("시스템을 중지합니다...", "SYSTEM")
        
        # MODI 컨트롤러 중지
        if self.modi_controller:
            try:
                self.modi_controller.close()
                self.log_message("MODI Plus 컨트롤러가 중지되었습니다.", "INFO")
            except Exception as e:
                self.log_message(f"MODI 컨트롤러 중지 오류: {e}", "ERROR")
        
        # 감지 프로세스 중지
        if self.detection_process:
            try:
                self.detection_process.terminate()
                self.detection_process.wait()
                self.log_message("쓰레기 감지 시스템이 중지되었습니다.", "INFO")
            except Exception as e:
                self.log_message(f"감지 시스템 중지 오류: {e}", "ERROR")
        
        # 백엔드 서버 중지
        if self.backend_process:
            try:
                self.backend_process.terminate()
                self.backend_process.wait()
                self.log_message("백엔드 서버가 중지되었습니다.", "INFO")
            except Exception as e:
                self.log_message(f"백엔드 서버 중지 오류: {e}", "ERROR")
        
        self.system_running = False
        self.log_message("✅ 시스템이 완전히 중지되었습니다.", "SUCCESS")
    
    def run_interactive_mode(self):
        """대화형 모드 실행"""
        print("\n🎮 대화형 제어 모드")
        print("=" * 40)
        print("사용 가능한 명령:")
        print("  status  - 시스템 상태 확인") 
        print("  close   - 수동으로 덮개 닫기")
        print("  open    - 수동으로 덮개 열기")
        print("  threshold <값> - 위험도 임계값 변경")
        print("  restart - 시스템 재시작")
        print("  quit    - 프로그램 종료")
        print()
        
        while self.system_running:
            try:
                command = input("명령 입력> ").strip().lower()
                
                if command in ['quit', 'exit', 'q']:
                    break
                elif command == 'status':
                    self.print_system_status()
                    if self.modi_controller:
                        modi_status = self.modi_controller.get_status()
                        print("\n🤖 MODI Plus 상태:")
                        for key, value in modi_status.items():
                            print(f"   {key}: {value}")
                elif command == 'close':
                    if self.modi_controller:
                        self.modi_controller.control_motor("close")
                    else:
                        print("❌ MODI Plus 컨트롤러가 연결되지 않았습니다.")
                elif command == 'open':
                    if self.modi_controller:
                        self.modi_controller.control_motor("open")
                    else:
                        print("❌ MODI Plus 컨트롤러가 연결되지 않았습니다.")
                elif command.startswith('threshold'):
                    try:
                        new_threshold = float(command.split()[1])
                        self.danger_threshold = new_threshold
                        if self.modi_controller:
                            self.modi_controller.danger_threshold = new_threshold
                        print(f"✅ 위험도 임계값이 {new_threshold}%로 변경되었습니다.")
                    except (IndexError, ValueError):
                        print("❌ 올바른 형식: threshold <숫자>")
                elif command == 'restart':
                    print("🔄 시스템을 재시작합니다...")
                    self.stop_system()
                    time.sleep(3)
                    self.start_system()
                else:
                    print("❓ 알 수 없는 명령입니다.")
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ 명령 처리 오류: {e}")


def check_dependencies():
    """필요한 의존성 확인"""
    print("🔍 시스템 의존성을 확인합니다...")
    
    required_files = [
        "backend/app.py",
        "garbage_detection.py"
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print("❌ 다음 파일들이 누락되었습니다:")
        for file_path in missing_files:
            print(f"   - {file_path}")
        return False
    
    # Python 패키지 확인
    try:
        import cv2
        import ultralytics
        import fastapi
        import requests
        print("✅ 필수 Python 패키지가 모두 설치되어 있습니다.")
    except ImportError as e:
        print(f"❌ 필수 패키지 누락: {e}")
        print("다음 명령으로 설치하세요:")
        print("pip install opencv-python ultralytics fastapi uvicorn requests")
        return False
    
    # MODI Plus 확인 (선택적)
    try:
        import modi
        print("✅ MODI Plus SDK가 설치되어 있습니다.")
    except ImportError:
        print("⚠️ MODI Plus SDK가 설치되지 않았습니다. (pip install pymodi)")
        print("MODI Plus 없이도 감지 시스템은 작동합니다.")
    
    return True


def main():
    """메인 실행 함수"""
    print("🏗️ 통합 하수구 쓰레기 감지 및 자동 덮개 제어 시스템")
    print("=" * 70)
    print("기능:")
    print("  🔍 실시간 쓰레기 감지 (YOLO + 웹캠)")
    print("  📊 위험도 분석 및 모니터링")
    print("  🌐 웹 대시보드 제공")
    print("  🤖 MODI Plus 자동 덮개 제어")
    print()
    
    # 의존성 확인
    if not check_dependencies():
        print("❌ 시스템 요구사항이 충족되지 않았습니다.")
        return
    
    # 통합 시스템 초기화
    system = IntegratedSewerSystem()
    
    try:
        # 시스템 시작
        if system.start_system():
            print(f"\n🌍 웹 대시보드: {system.server_url}")
            print("📱 브라우저에서 위 주소로 접속하여 실시간 모니터링이 가능합니다.")
            print()
            
            # 대화형 모드 실행
            system.run_interactive_mode()
        else:
            print("❌ 시스템 시작에 실패했습니다.")
    
    except KeyboardInterrupt:
        print("\n⏹️ 사용자에 의해 프로그램이 중단되었습니다.")
    
    finally:
        # 시스템 정리
        system.stop_system()
        print("👋 프로그램을 종료합니다.")


if __name__ == "__main__":
    main()