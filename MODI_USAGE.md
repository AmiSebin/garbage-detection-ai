# MODI Plus 하수구 자동 제어 시스템 사용법

## 📋 시스템 개요

이 시스템은 MODI Plus 럭스로보 모듈을 활용하여 하수구 주변 쓰레기를 감지하고, 위험도가 높아지면 자동으로 하수구 덮개를 닫는 지능형 방어 시스템입니다.

### 🔧 주요 구성요소

1. **쓰레기 감지**: YOLO AI 모델 + 웹캠으로 실시간 감지
2. **위험도 분석**: FastAPI 백엔드에서 복합적 위험도 계산
3. **MODI Plus 제어**: 네트워크 모듈 → 모터 모듈 신호 전달
4. **자동 덮개 제어**: 위험도 임계값 초과시 덮개 자동 닫기

## 🛠️ 설치 및 설정

### 1. 필수 소프트웨어 설치

```bash
# Python 패키지 설치
pip install opencv-python ultralytics fastapi uvicorn requests

# MODI Plus SDK 설치
pip install pymodi-plus
```

### 2. 하드웨어 연결

- **MODI Plus 네트워크 모듈**: 신호 전달용
- **MODI Plus 모터 모듈**: 하수구 덮개 제어용
- **웹캠**: 쓰레기 감지용
- **하수구 덮개 메커니즘**: 모터와 연결

### 3. 모듈 연결 확인

MODI Plus 모듈들이 올바르게 연결되었는지 확인:

```python
import modi_plus
bundle = modi_plus.MODIPlus()
print("연결된 모듈:", [type(m).__name__ for m in bundle.modules])
print("네트워크 모듈:", len(bundle.networks))
print("모터/서보 모듈:", len(bundle.motors + bundle.servos))
```

## 🚀 시스템 실행

### 방법 1: 통합 시스템 실행 (권장)

```bash
python integrated_sewer_system.py
```

이 방법은 모든 구성요소를 자동으로 시작합니다:
- FastAPI 백엔드 서버
- 쓰레기 감지 시스템  
- MODI Plus 컨트롤러
- 웹 대시보드

### 방법 2: 개별 구성요소 실행

```bash
# 1. 백엔드 서버 시작
python backend/app.py

# 2. 쓰레기 감지 시작 (새 터미널)
python garbage_detection.py

# 3. MODI 컨트롤러 시작 (새 터미널)
python modi_sewer_controller.py
```

## ⚙️ 설정 및 제어

### 위험도 임계값 설정

기본값: 70% (권장 범위: 60-80%)

```python
# 코드에서 변경
controller = MODISewerController(danger_threshold=75.0)

# 실행 중 변경
명령 입력> threshold 75
```

### 수동 제어 명령

```bash
# 시스템 상태 확인
명령 입력> status

# 수동으로 덮개 닫기
명령 입력> close

# 수동으로 덮개 열기  
명령 입력> open

# 위험도 임계값 변경
명령 입력> threshold 80

# 시스템 재시작
명령 입력> restart

# 프로그램 종료
명령 입력> quit
```

## 🔄 동작 원리

### 자동 제어 시퀀스

1. **쓰레기 감지**: 웹캠으로 실시간 모니터링
2. **위험도 계산**: AI가 복합적 요소로 위험도 산출
3. **임계값 초과**: 위험도 ≥ 70% 달성시
4. **네트워크 신호**: 네트워크 모듈로 경고 신호 전송
5. **덮개 제어**: 모터 모듈이 덮개를 90도 회전하여 닫기
6. **안전 확인**: 위험도 < 35% 감소시 덮개 자동 열기

### 위험도 계산 요소

- **감지 개수**: 더 많은 쓰레기 = 높은 위험도
- **신뢰도**: AI 감지 정확도
- **쓰레기 크기**: 면적이 클수록 위험
- **쓰레기 종류**: 막힘 위험성에 따른 가중치
- **시간적 패턴**: 지속적 축적 여부

## 📊 모니터링 및 로그

### 웹 대시보드

브라우저에서 `http://localhost:8000` 접속:
- 실시간 위험도 그래프
- 감지된 쓰레기 목록
- 시스템 상태 모니터링
- 알림 및 이벤트 로그

### 로그 파일

시스템 동작 로그가 자동으로 기록됩니다:
- 감지 이벤트
- 위험도 변화
- 덮개 제어 동작
- 오류 및 경고

## 🔧 문제 해결

### 일반적인 문제

**1. MODI Plus 연결 실패**
```
❌ MODI Plus 연결 실패 - 시간 초과
```
- 해결: USB 연결 확인, 모듈 전원 확인, 드라이버 재설치

**2. 모터 모듈을 찾을 수 없음**
```
❌ 필요한 모듈을 찾을 수 없습니다.
```
- 해결: 모터 모듈 연결 확인, 모듈 펌웨어 업데이트

**3. 웹캠 인식 실패**
```
웹캠에서 프레임을 읽을 수 없습니다.
```
- 해결: 웹캠 연결 확인, 다른 프로그램에서 사용 중인지 확인

**4. 서버 연결 오류**
```
❌ 서버 연결 실패: Connection refused
```
- 해결: 백엔드 서버 먼저 실행, 포트 8000 사용 가능한지 확인

### 디버깅 모드

상세한 로그를 보려면:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## ⚠️ 안전 주의사항

1. **수동 오버라이드**: 긴급시 수동으로 덮개 제어 가능
2. **전원 안전**: 모터 동작 중 전원 차단 금지  
3. **정기 점검**: 모터 모듈과 덮개 메커니즘 정기 점검
4. **백업 시스템**: 네트워크 장애시 로컬 제어 가능

## 📈 성능 최적화

### 권장 설정

- **위험도 임계값**: 70% (도시 지역), 60% (위험 지역)
- **모터 속도**: 50 (안전성 우선), 80 (속도 우선)
- **감지 신뢰도**: 0.1 이상 (더 민감한 감지)

### 하드웨어 요구사항

- **CPU**: Intel i5 이상 (실시간 AI 처리)
- **RAM**: 8GB 이상
- **GPU**: CUDA 지원 (선택적, 성능 향상)
- **웹캠**: HD 해상도 이상

## 🔄 업데이트 및 확장

### 추가 기능

- 음성 알림 시스템
- SMS/이메일 알림  
- 다중 카메라 지원
- 클라우드 데이터 백업

### 모듈 확장

```python
# 추가 센서 모듈 연결 예제
if hasattr(module, 'get_distance'):
    distance_sensor = module
    
if hasattr(module, 'get_temperature'):
    temp_sensor = module
```

## 📞 지원 및 문의

시스템 관련 문제나 개선 제안은 다음을 참고하세요:

- MODI Plus 공식 문서: https://modi.luxrobo.com/
- YOLO 모델 정보: https://ultralytics.com/
- 이슈 리포트: 프로젝트 GitHub 페이지

---

**버전**: 1.0  
**최종 업데이트**: 2025-08-02  
**호환성**: MODI Plus SDK v2.0+, Python 3.8+