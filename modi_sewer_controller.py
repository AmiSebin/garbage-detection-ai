"""
MODI Plus 럭스로보 모듈을 사용한 하수구 덮개 자동 제어 시스템
쓰레기 위험도가 일정 수준 이상일 때 네트워크 모듈을 통해 모터 모듈에 신호를 보내 덮개를 닫습니다.
"""

import time
import requests
import threading
from datetime import datetime
from typing import Dict, Any, Optional

try:
    import modi_plus
    MODI_AVAILABLE = True
    print("✅ MODI Plus SDK를 성공적으로 불러왔습니다.")
except ImportError:
    MODI_AVAILABLE = False
    print("❌ MODI Plus SDK를 찾을 수 없습니다. 'pip install pymodi-plus' 명령으로 설치하세요.")


class MODISewerController:
    """MODI Plus를 사용한 하수구 덮개 자동 제어 시스템"""
    
    def __init__(self, server_url: str = "http://localhost:8000", danger_threshold: float = 70.0):
        """
        MODI 하수구 제어 시스템 초기화
        
        Args:
            server_url: 쓰레기 감지 백엔드 서버 URL
            danger_threshold: 하수구 덮개를 닫을 위험도 임계값 (기본: 70%)
        """
        self.server_url = server_url
        self.danger_threshold = danger_threshold
        
        # MODI 모듈 초기화
        self.bundle = None
        self.network_module = None
        self.motor_module = None
        self.modi_connected = False
        
        # 상태 관리
        self.cover_closed = False
        self.last_risk_score = 0.0
        self.last_check_time = datetime.now()
        self.monitoring_active = False
        
        # 모터 제어 설정 (더 큰 동작 범위)
        self.close_angle = 180  # 덮개를 닫을 각도 (180도 - 완전히 닫기)
        self.open_angle = 0     # 덮개를 열 각도 (0도 - 완전히 열기)
        self.motor_speed = 40   # 모터 속도 (0-100, 더 빠르게)
        self.rotation_time = 1.7  # DC 모터 회전 시간 (초)
        
        # 로그 기록
        self.log_history = []
        
    def initialize_modi(self) -> bool:
        """MODI Plus 모듈들을 초기화합니다."""
        if not MODI_AVAILABLE:
            self.log_message("❌ MODI SDK가 설치되지 않았습니다.", "ERROR")
            return False
            
        try:
            # MODI Plus bundle 연결 (공식 API 사용)
            self.bundle = modi_plus.MODIPlus()
            self.log_message("🔌 MODI Plus 연결을 시도합니다...", "INFO")
            
            # 연결 확인 (MODIPlus 객체는 생성과 동시에 연결됨)
            time.sleep(2)  # 모듈 탐지 대기
                
            print()  # 줄바꿈
            self.log_message("✅ MODI Plus 연결 성공!", "SUCCESS")
            
            # 모듈 검색
            self.find_modules()
            
            if self.network_module and self.motor_module:
                self.modi_connected = True
                self.log_message("🎯 모든 MODI 모듈이 준비되었습니다.", "SUCCESS")
                return True
            else:
                self.log_message("❌ 필요한 모듈을 찾을 수 없습니다.", "ERROR")
                return False
                
        except Exception as e:
            self.log_message(f"❌ MODI 초기화 오류: {e}", "ERROR")
            return False
    
    def find_modules(self):
        """연결된 MODI 모듈들을 찾습니다."""
        try:
            modules = self.bundle.modules
            self.log_message(f"🔍 {len(modules)}개의 모듈을 발견했습니다.", "INFO")
            
            # MODI Plus 공식 API 사용하여 모듈 찾기
            # 네트워크 모듈 찾기
            if hasattr(self.bundle, 'networks') and len(self.bundle.networks) > 0:
                self.network_module = self.bundle.networks[0]
                self.log_message(f"📡 네트워크 모듈 발견", "SUCCESS")
            
            # 모터 모듈 찾기  
            if hasattr(self.bundle, 'motors') and len(self.bundle.motors) > 0:
                self.motor_module = self.bundle.motors[0]
                self.log_message(f"⚙️ 모터 모듈 발견", "SUCCESS")
            elif hasattr(self.bundle, 'servos') and len(self.bundle.servos) > 0:
                self.motor_module = self.bundle.servos[0]
                self.log_message(f"⚙️ 서보 모듈 발견", "SUCCESS")
            
            # 일반적인 방법으로도 확인
            for module in modules:
                module_type = type(module).__name__
                self.log_message(f"   - {module_type}", "INFO")
                
                # 추가 네트워크 모듈 확인
                if 'network' in module_type.lower() and not self.network_module:
                    self.network_module = module
                    self.log_message(f"📡 네트워크 모듈 추가 발견: {module_type}", "SUCCESS")
                
                # 추가 모터 모듈 확인  
                if ('motor' in module_type.lower() or 'servo' in module_type.lower()) and not self.motor_module:
                    self.motor_module = module
                    self.log_message(f"⚙️ 모터 모듈 추가 발견: {module_type}", "SUCCESS")
                    
        except Exception as e:
            self.log_message(f"❌ 모듈 검색 오류: {e}", "ERROR")
    
    def log_message(self, message: str, level: str = "INFO"):
        """로그 메시지를 기록하고 출력합니다."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message
        }
        self.log_history.append(log_entry)
        
        # 최근 100개 로그만 유지
        if len(self.log_history) > 100:
            self.log_history.pop(0)
        
        # 레벨별 색상 출력
        colors = {
            "INFO": "\033[94m",     # 파란색
            "SUCCESS": "\033[92m",  # 초록색
            "WARNING": "\033[93m",  # 노란색
            "ERROR": "\033[91m",    # 빨간색
            "DANGER": "\033[95m"    # 마젠타색
        }
        color = colors.get(level, "\033[0m")
        reset = "\033[0m"
        
        print(f"{color}[{timestamp}] {level}: {message}{reset}")
    
    def get_risk_status(self) -> Optional[Dict[str, Any]]:
        """백엔드 서버에서 현재 위험도 상태를 가져옵니다."""
        try:
            response = requests.get(f"{self.server_url}/status", timeout=5)
            if response.status_code == 200:
                return response.json()
            else:
                self.log_message(f"서버 응답 오류: {response.status_code}", "WARNING")
                return None
        except requests.exceptions.RequestException as e:
            self.log_message(f"서버 연결 오류: {e}", "WARNING")
            return None
    
    def send_network_signal(self, command: str, data: Any = None) -> bool:
        """네트워크 모듈을 통해 신호를 전송합니다."""
        if not self.network_module:
            self.log_message("네트워크 모듈이 연결되지 않았습니다.", "ERROR")
            return False
        
        try:
            # 네트워크 모듈을 통해 데이터 전송
            signal_data = {
                "command": command,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
            
            # MODI Plus 네트워크 모듈로 신호 전송
            # 실제 네트워크 모듈은 보통 send_data나 직접적인 속성 설정을 사용
            try:
                # 단순한 신호 전송 (명령어를 숫자로 변환)
                signal_value = 1 if command == "DANGER_ALERT" else 0
                
                if hasattr(self.network_module, 'send_data'):
                    self.network_module.send_data(signal_value)
                    self.log_message(f"📡 네트워크 신호 전송: {command} (값: {signal_value})", "INFO")
                    return True
                elif hasattr(self.network_module, 'value'):
                    self.network_module.value = signal_value
                    self.log_message(f"📡 네트워크 값 설정: {command} (값: {signal_value})", "INFO")
                    return True
                else:
                    self.log_message("네트워크 모듈 제어 방법을 찾을 수 없습니다.", "WARNING")
                    return False
            except Exception as e:
                self.log_message(f"네트워크 신호 전송 중 오류: {e}", "ERROR")
                return False
                
        except Exception as e:
            self.log_message(f"네트워크 신호 전송 오류: {e}", "ERROR")
            return False
    
    def control_motor(self, action: str) -> bool:
        """모터 모듈을 제어하여 하수구 덮개를 열거나 닫습니다."""
        if not self.motor_module:
            self.log_message("모터 모듈이 연결되지 않았습니다.", "ERROR")
            return False
        
        try:
            # 모터 모듈의 속성들을 먼저 확인
            motor_attrs = [attr for attr in dir(self.motor_module) if not attr.startswith('_')]
            self.log_message(f"🔍 모터 모듈 사용 가능한 속성: {motor_attrs}", "INFO")
            
            if action == "close":
                target_angle = self.close_angle
                self.log_message(f"🔒 하수구 덮개를 닫습니다... (목표: {target_angle}°)", "WARNING")
            elif action == "open":
                target_angle = self.open_angle
                self.log_message(f"🔓 하수구 덮개를 엽니다... (목표: {target_angle}°)", "INFO")
            else:
                self.log_message(f"알 수 없는 동작: {action}", "ERROR")
                return False
            
            # MODI Plus 모터 제어 - 다양한 방법 시도
            motor_controlled = False
            
            # 방법 1: degree 속성 (서보 모터)
            if hasattr(self.motor_module, 'degree'):
                try:
                    old_degree = getattr(self.motor_module, 'degree', 'unknown')
                    self.log_message(f"현재 각도: {old_degree}도 → 목표 각도: {target_angle}도", "INFO")
                    self.motor_module.degree = target_angle
                    time.sleep(1)  # 설정 후 잠시 대기
                    new_degree = getattr(self.motor_module, 'degree', 'unknown')
                    self.log_message(f"✅ 서보 모터 각도 설정 완료: {new_degree}도", "SUCCESS")
                    motor_controlled = True
                except Exception as e:
                    self.log_message(f"서보 모터 제어 오류: {e}", "ERROR")
            
            # 방법 2: speed 속성 (DC 모터)
            elif hasattr(self.motor_module, 'speed'):
                try:
                    if action == "close":
                        self.log_message(f"DC 모터 시작: 속도 {self.motor_speed}, {self.rotation_time}초간 회전", "INFO")
                        self.motor_module.speed = self.motor_speed
                        time.sleep(self.rotation_time)
                        self.motor_module.speed = 0
                        self.log_message("DC 모터 정지", "INFO")
                    elif action == "open":
                        self.log_message(f"DC 모터 시작: 속도 -{self.motor_speed}, {self.rotation_time}초간 역방향 회전", "INFO")
                        self.motor_module.speed = -self.motor_speed
                        time.sleep(self.rotation_time)
                        self.motor_module.speed = 0
                        self.log_message("DC 모터 정지", "INFO")
                    motor_controlled = True
                except Exception as e:
                    self.log_message(f"DC 모터 제어 오류: {e}", "ERROR")
            
            # 방법 3: set_degree 메서드
            elif hasattr(self.motor_module, 'set_degree'):
                try:
                    self.log_message(f"set_degree 메서드 사용: {target_angle}도", "INFO")
                    self.motor_module.set_degree(target_angle)
                    motor_controlled = True
                except Exception as e:
                    self.log_message(f"set_degree 메서드 오류: {e}", "ERROR")
            
            # 방법 4: set_speed 메서드
            elif hasattr(self.motor_module, 'set_speed'):
                try:
                    speed_value = self.motor_speed if action == "close" else -self.motor_speed
                    self.log_message(f"set_speed 메서드 사용: {speed_value}", "INFO")
                    self.motor_module.set_speed(speed_value)
                    time.sleep(self.rotation_time)
                    self.motor_module.set_speed(0)  # 정지
                    motor_controlled = True
                except Exception as e:
                    self.log_message(f"set_speed 메서드 오류: {e}", "ERROR")
            
            # 방법 5: 직접 속성 설정 시도
            else:
                self.log_message("표준 제어 방법을 찾을 수 없어 직접 속성 설정을 시도합니다.", "WARNING")
                try:
                    # 가능한 모든 속성에 값 설정 시도
                    for attr_name in ['degree', 'angle', 'position', 'speed', 'velocity']:
                        if hasattr(self.motor_module, attr_name):
                            if attr_name in ['degree', 'angle', 'position']:
                                setattr(self.motor_module, attr_name, target_angle)
                                self.log_message(f"✅ {attr_name} 속성에 {target_angle} 설정", "SUCCESS")
                                motor_controlled = True
                                break
                            elif attr_name in ['speed', 'velocity']:
                                speed_val = self.motor_speed if action == "close" else -self.motor_speed
                                setattr(self.motor_module, attr_name, speed_val)
                                time.sleep(self.rotation_time)
                                setattr(self.motor_module, attr_name, 0)
                                self.log_message(f"✅ {attr_name} 속성으로 모터 제어 완료", "SUCCESS")
                                motor_controlled = True
                                break
                except Exception as e:
                    self.log_message(f"직접 속성 설정 오류: {e}", "ERROR")
            
            if not motor_controlled:
                self.log_message("❌ 모든 모터 제어 방법이 실패했습니다.", "ERROR")
                self.log_message("💡 모터 모듈 타입을 확인하거나 연결을 점검하세요.", "WARNING")
                return False
            
            # 상태 업데이트
            self.cover_closed = (action == "close")
            
            # 동작 완료 대기
            time.sleep(1)
            
            self.log_message(f"✅ 덮개 {action} 동작 완료", "SUCCESS")
            return True
            
        except Exception as e:
            self.log_message(f"모터 제어 오류: {e}", "ERROR")
            return False
    
    def process_risk_level(self, risk_data: Dict[str, Any]):
        """위험도 데이터를 처리하고 필요시 덮개를 제어합니다."""
        risk_score = risk_data.get('risk_score', 0.0)
        risk_level = risk_data.get('risk_level', 'safe')
        
        self.last_risk_score = risk_score
        self.last_check_time = datetime.now()
        
        # 위험도가 임계값을 초과하고 덮개가 열려있는 경우
        if risk_score >= self.danger_threshold and not self.cover_closed:
            self.log_message(f"🚨 위험도 {risk_score:.1f}%로 임계값({self.danger_threshold}%)을 초과!", "DANGER")
            self.log_message("덮개 자동 닫기 시퀀스를 시작합니다...", "DANGER")
            
            # 1단계: 네트워크 모듈을 통해 경고 신호 전송
            self.send_network_signal("DANGER_ALERT", {
                "risk_score": risk_score,
                "risk_level": risk_level,
                "action": "CLOSE_COVER"
            })
            
            # 2단계: 모터 모듈로 덮개 닫기
            if self.control_motor("close"):
                self.log_message("🛡️ 하수구 덮개가 안전하게 닫혔습니다.", "SUCCESS")
                
                # 서버에 덮개 닫힘 상태 알림 (선택적)
                try:
                    requests.post(f"{self.server_url}/cover_status", json={
                        "status": "closed",
                        "timestamp": datetime.now().isoformat(),
                        "risk_score": risk_score
                    }, timeout=3)
                except:
                    pass  # 서버 알림 실패해도 계속 진행
            else:
                self.log_message("❌ 덮개 닫기에 실패했습니다!", "ERROR")
        
        # 위험도가 안전 수준으로 내려가고 덮개가 닫혀있는 경우 (자동 열기)
        elif risk_score < (self.danger_threshold * 0.5) and self.cover_closed:
            safe_threshold = self.danger_threshold * 0.5
            self.log_message(f"📉 위험도 {risk_score:.1f}%로 안전 수준({safe_threshold:.1f}%) 이하로 감소", "INFO")
            self.log_message("덮개 자동 열기를 고려합니다...", "INFO")
            
            # 안전 확인을 위해 5초 더 대기
            time.sleep(5)
            
            # 다시 한번 위험도 확인
            updated_status = self.get_risk_status()
            if updated_status and updated_status.get('risk_score', 0) < safe_threshold:
                # 네트워크 신호 전송
                self.send_network_signal("SAFE_STATUS", {
                    "risk_score": risk_score,
                    "action": "OPEN_COVER"
                })
                
                # 덮개 열기
                if self.control_motor("open"):
                    self.log_message("🌊 하수구 덮개가 다시 열렸습니다.", "SUCCESS")
                else:
                    self.log_message("❌ 덮개 열기에 실패했습니다!", "ERROR")
    
    def start_monitoring(self):
        """백그라운드에서 지속적으로 위험도를 모니터링합니다."""
        self.monitoring_active = True
        self.log_message("🔄 하수구 위험도 모니터링을 시작합니다...", "INFO")
        
        while self.monitoring_active:
            try:
                # 서버에서 현재 상태 가져오기
                risk_data = self.get_risk_status()
                
                if risk_data:
                    self.process_risk_level(risk_data)
                else:
                    self.log_message("⚠️ 서버에서 위험도 데이터를 가져올 수 없습니다.", "WARNING")
                
                # 5초마다 확인
                time.sleep(5)
                
            except KeyboardInterrupt:
                self.log_message("모니터링이 사용자에 의해 중단되었습니다.", "INFO")
                break
            except Exception as e:
                self.log_message(f"모니터링 오류: {e}", "ERROR")
                time.sleep(10)  # 오류 발생시 10초 후 재시도
    
    def stop_monitoring(self):
        """모니터링을 중단합니다."""
        self.monitoring_active = False
        self.log_message("⏹️ 모니터링을 중단합니다.", "INFO")
    
    def get_status(self) -> Dict[str, Any]:
        """현재 시스템 상태를 반환합니다."""
        return {
            "modi_connected": self.modi_connected,
            "cover_closed": self.cover_closed,
            "last_risk_score": self.last_risk_score,
            "danger_threshold": self.danger_threshold,
            "last_check_time": self.last_check_time.isoformat(),
            "monitoring_active": self.monitoring_active,
            "network_module_available": self.network_module is not None,
            "motor_module_available": self.motor_module is not None
        }
    
    def close(self):
        """시스템을 정리하고 MODI 연결을 종료합니다."""
        self.stop_monitoring()
        
        if self.bundle:
            try:
                self.bundle.close()
                self.log_message("🔌 MODI Plus 연결이 종료되었습니다.", "INFO")
            except Exception as e:
                self.log_message(f"MODI 연결 종료 오류: {e}", "ERROR")


def main():
    """메인 실행 함수"""
    print("🏗️ MODI Plus 하수구 덮개 자동 제어 시스템")
    print("=" * 60)
    
    # 시스템 초기화
    controller = MODISewerController(
        server_url="http://localhost:8000",
        danger_threshold=70.0  # 위험도 70% 이상이면 덮개 닫기
    )
    
    try:
        # MODI Plus 초기화
        if controller.initialize_modi():
            print("\n🎯 시스템이 준비되었습니다!")
            print("📋 제어 명령:")
            print("   - 'status': 현재 상태 확인")
            print("   - 'close': 수동으로 덮개 닫기")
            print("   - 'open': 수동으로 덮개 열기")
            print("   - 'threshold <값>': 위험도 임계값 변경")
            print("   - 'monitor': 자동 모니터링 시작")
            print("   - 'stop': 모니터링 중단")
            print("   - 'quit': 프로그램 종료")
            print()
            
            # 모니터링 자동 시작
            monitoring_thread = threading.Thread(target=controller.start_monitoring)
            monitoring_thread.daemon = True
            monitoring_thread.start()
            
            # 사용자 명령 처리
            while True:
                try:
                    command = input("명령 입력> ").strip().lower()
                    
                    if command == 'quit' or command == 'exit':
                        break
                    elif command == 'status':
                        status = controller.get_status()
                        print("\n📊 현재 시스템 상태:")
                        for key, value in status.items():
                            print(f"   {key}: {value}")
                        print()
                    elif command == 'close':
                        controller.control_motor("close")
                    elif command == 'open':
                        controller.control_motor("open")
                    elif command.startswith('threshold'):
                        try:
                            new_threshold = float(command.split()[1])
                            controller.danger_threshold = new_threshold
                            print(f"✅ 위험도 임계값이 {new_threshold}%로 변경되었습니다.")
                        except (IndexError, ValueError):
                            print("❌ 올바른 형식: threshold <숫자>")
                    elif command == 'monitor':
                        if not controller.monitoring_active:
                            monitoring_thread = threading.Thread(target=controller.start_monitoring)
                            monitoring_thread.daemon = True
                            monitoring_thread.start()
                        else:
                            print("✅ 모니터링이 이미 실행 중입니다.")
                    elif command == 'stop':
                        controller.stop_monitoring()
                    else:
                        print("❓ 알 수 없는 명령입니다. 도움말을 참고하세요.")
                        
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"❌ 명령 처리 오류: {e}")
        else:
            print("❌ MODI Plus 초기화에 실패했습니다.")
            print("💡 다음 사항을 확인하세요:")
            print("   1. MODI Plus가 컴퓨터에 연결되어 있는지")
            print("   2. 네트워크 모듈과 모터 모듈이 연결되어 있는지")
            print("   3. pymodi 라이브러리가 설치되어 있는지 (pip install pymodi)")
    
    except KeyboardInterrupt:
        print("\n⏹️ 프로그램이 중단되었습니다.")
    
    finally:
        # 정리 작업
        controller.close()
        print("👋 프로그램을 종료합니다.")


if __name__ == "__main__":
    main()