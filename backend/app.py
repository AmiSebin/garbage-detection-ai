"""
하수도 막힘 실시간 감지 FastAPI 백엔드
서버와 프론트엔드 분리 버전
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from collections import deque
from datetime import datetime, timedelta
import asyncio
import json
import logging
import math
import cv2
import base64
import numpy as np

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="하수도 막힘 감지 시스템 API", version="2.0.0")

# CORS 설정 (프론트엔드 분리로 인해 필요)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발용 - 실제 배포시에는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 데이터 모델 ====================

class DetectionData(BaseModel):
    timestamp: str
    garbage_type: str
    confidence: float
    bbox: List[int]  # [x1, y1, x2, y2]
    area: float
    location: str = "main_pipe"

class AlertData(BaseModel):
    level: str  # "safe", "warning", "danger"
    message: str
    timestamp: datetime
    risk_score: float

class StatusResponse(BaseModel):
    risk_level: str
    risk_score: float
    total_detections: int
    last_detection: Optional[str]
    alerts_today: int
    pipe_status: str
    blockage_percentage: Optional[float] = 0.0
    garbage_volume: Optional[float] = 0.0
    flow_restriction: Optional[str] = "없음"
    accumulated_areas: Optional[int] = 0

class BlockageAnalysis(BaseModel):
    blockage_percentage: float
    garbage_volume: float
    flow_restriction: str
    accumulated_areas: int
    total_area: float

class AIAnalysis(BaseModel):
    """AI 분석 결과"""
    risk_assessment: str  # "low", "medium", "high", "critical"
    confidence_level: float  # AI 분석 신뢰도 (0-1)
    reasoning: str  # AI 분석 근거
    recommendations: List[str]  # AI 권장사항
    false_positive_probability: float  # 오탐지 확률
    trend_analysis: str  # 추세 분석
    severity_score: float  # AI 심각도 점수 (0-100)

# ==================== 전역 상태 ====================

current_status = {
    "risk_score": 0.0,
    "risk_level": "safe",
    "total_detections": 0,
    "last_detection": None,
    "alerts_today": 0,
    "pipe_status": "정상 - 원활한 흐름",
    "accumulation_rate": 0.0,
    "blockage_percentage": 0.0,
    "garbage_volume": 0.0,
    "flow_restriction": "없음",
    "accumulated_areas": 0
}

recent_detections: deque = deque(maxlen=100)
recent_alerts: deque = deque(maxlen=50)
connected_clients: List[WebSocket] = []

# 비디오 스트리밍
current_frame = None
camera_active = False

# 위험도 임계값 (더 보수적으로 조정)
RISK_THRESHOLDS = {
    "safe": (0, 60),      # 60% 미만: 안전 (더 관대하게)
    "warning": (60, 80),  # 60-80%: 주의 (범위 축소)
    "danger": (80, 100)   # 80% 이상: 위험 (더 엄격하게)
}

# AI 분석 가중치 (더 보수적으로)
AI_WEIGHTS = {
    "low": 0.2,           # AI가 낮은 위험으로 판단시 가중치 대폭 감소
    "medium": 0.5,        # AI가 중간 위험으로 판단시 가중치 감소
    "high": 0.8,          # AI가 높은 위험으로 판단시 가중치 제한
    "critical": 1.0       # AI가 매우 위험으로 판단시도 보수적 접근
}

# 감지 신뢰도 임계값 (더 엄격하게)
MIN_CONFIDENCE_THRESHOLD = 0.7  # 70% 이상 신뢰도만 처리 (더 엄격)
MIN_AREA_THRESHOLD = 2000       # 최소 면적 증가 (더 큰 객체만)
MIN_DETECTIONS_FOR_WARNING = 5  # 경고 발생을 위한 최소 감지 횟수 증가
MIN_DETECTIONS_FOR_DANGER = 8   # 위험 발생을 위한 최소 감지 횟수

# ==================== 분석 함수들 ====================

def is_duplicate_detection(new_detection: DetectionData, threshold_seconds: int = 10) -> bool:
    """중복 감지인지 확인"""
    if not recent_detections:
        return False
    
    try:
        new_time = datetime.fromisoformat(new_detection.timestamp.replace('Z', '+00:00'))
        new_bbox = new_detection.bbox
        new_center = ((new_bbox[0] + new_bbox[2]) // 2, (new_bbox[1] + new_bbox[3]) // 2)
        
        for detection in list(recent_detections)[-5:]:
            try:
                det_time = datetime.fromisoformat(detection.timestamp.replace('Z', '+00:00'))
                time_diff = (new_time - det_time).total_seconds()
                
                if time_diff < threshold_seconds:
                    det_bbox = detection.bbox
                    det_center = ((det_bbox[0] + det_bbox[2]) // 2, (det_bbox[1] + det_bbox[3]) // 2)
                    distance = math.sqrt((new_center[0] - det_center[0])**2 + (new_center[1] - det_center[1])**2)
                    
                    if distance < 50 and detection.garbage_type == new_detection.garbage_type:
                        return True
            except:
                continue
                
    except:
        pass
    
    return False

def analyze_pipe_blockage(detections: List[DetectionData]) -> BlockageAnalysis:
    """하수구 막힘 정도 분석"""
    if not detections:
        return BlockageAnalysis(
            blockage_percentage=0.0,
            garbage_volume=0.0,
            flow_restriction="없음",
            accumulated_areas=0,
            total_area=0
        )
    
    now = datetime.now()
    recent_hour = now - timedelta(hours=1)
    
    # 최근 1시간 내 감지 필터링
    recent_detections_list = []
    for d in detections:
        try:
            detection_time = datetime.fromisoformat(d.timestamp.replace('Z', '+00:00'))
            if detection_time >= recent_hour:
                recent_detections_list.append(d)
        except:
            recent_detections_list.append(d)
    
    # 축적 영역 분석
    blockage_areas = {}
    total_area = 0
    
    for detection in recent_detections_list:
        bbox = detection.bbox
        area_key = f"{bbox[0]//100}_{bbox[1]//100}"
        
        if area_key not in blockage_areas:
            blockage_areas[area_key] = {
                "count": 0,
                "total_area": 0,
                "max_confidence": 0,
                "garbage_types": set()
            }
        
        blockage_areas[area_key]["count"] += 1
        blockage_areas[area_key]["total_area"] += detection.area
        blockage_areas[area_key]["max_confidence"] = max(
            blockage_areas[area_key]["max_confidence"], 
            detection.confidence
        )
        blockage_areas[area_key]["garbage_types"].add(detection.garbage_type)
        total_area += detection.area
    
    # 막힘 정도 계산
    pipe_width = 640
    pipe_height = 480
    total_pipe_area = pipe_width * pipe_height
    
    blockage_percentage = min((total_area / total_pipe_area) * 100, 100)
    
    # 흐름 제한 수준 결정
    if blockage_percentage < 10:
        flow_restriction = "미미함"
    elif blockage_percentage < 30:
        flow_restriction = "경미함"
    elif blockage_percentage < 60:
        flow_restriction = "보통"
    elif blockage_percentage < 80:
        flow_restriction = "심각함"
    else:
        flow_restriction = "매우 심각함"
    
    # 용적 추정
    estimated_depth = 5  # cm
    garbage_volume = (total_area / 10000) * estimated_depth  # cm³
    
    return BlockageAnalysis(
        blockage_percentage=round(blockage_percentage, 1),
        garbage_volume=round(garbage_volume, 2),
        flow_restriction=flow_restriction,
        accumulated_areas=len(blockage_areas),
        total_area=total_area
    )

def is_valid_detection(detection: DetectionData) -> bool:
    """감지가 유효한지 검사"""
    # 신뢰도 체크
    if detection.confidence < MIN_CONFIDENCE_THRESHOLD:
        return False
    
    # 최소 면적 체크
    if detection.area < MIN_AREA_THRESHOLD:
        return False
    
    # 바운딩 박스 유효성 체크
    bbox = detection.bbox
    if len(bbox) != 4 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return False
    
    return True

def calculate_risk_score_with_ai(detections: List[DetectionData]) -> tuple[float, AIAnalysis]:
    """AI 분석을 포함한 신뢰성 높은 위험도 점수 계산"""
    current_risk = current_status.get("risk_score", 0)
    
    if not detections:
        # 쓰레기가 없으면 위험도 자연 감소 (더 빠르게)
        decay_rate = 2.0  # 분당 2% 감소
        time_since_last = get_time_since_last_detection()
        decay_amount = min(decay_rate * time_since_last, current_risk)
        base_score = max(0, current_risk - decay_amount)
        
        ai_analysis = AIAnalysis(
            risk_assessment="low",
            confidence_level=0.9,
            reasoning="감지된 쓰레기가 없어 안전한 상태입니다. 위험도가 자연적으로 감소하고 있습니다.",
            recommendations=["정기적인 모니터링을 계속하세요."],
            false_positive_probability=0.0,
            trend_analysis="개선",
            severity_score=0.0
        )
        return base_score, ai_analysis
    
    # 유효한 감지만 필터링
    valid_detections = [d for d in detections if is_valid_detection(d)]
    
    if not valid_detections:
        base_score = max(0, current_status.get("risk_score", 0) - 1)
        ai_analysis = AIAnalysis(
            risk_assessment="low",
            confidence_level=0.7,
            reasoning="유효한 감지가 없어 안전한 상태입니다.",
            recommendations=["카메라 시스템을 점검하세요."],
            false_positive_probability=0.5,
            trend_analysis="불확실",
            severity_score=0.0
        )
        return base_score, ai_analysis
    
    # AI 분석 수행
    blockage_analysis = analyze_pipe_blockage(valid_detections)
    ai_analysis = analyze_with_ai(valid_detections, blockage_analysis)
    
    # 동적 위험도 변화 계산
    dynamic_change = calculate_dynamic_risk_change(valid_detections, current_risk)
    
    # 기본 점수 계산 (더 보수적으로)
    blockage_score = blockage_analysis.blockage_percentage * 0.3  # 막힘률 가중치 더 감소
    volume_score = min(blockage_analysis.garbage_volume / 40, 8)  # 용적 점수 더 감소
    areas_score = min(blockage_analysis.accumulated_areas * 1.5, 6)  # 영역 점수 더 감소
    
    # 신뢰도 가중치
    avg_confidence = sum(d.confidence for d in valid_detections) / len(valid_detections)
    confidence_multiplier = min(avg_confidence / 0.8, 1.0)  # 80% 이상일 때 최대 배율
    
    # AI 분석 가중치 적용
    ai_weight = AI_WEIGHTS.get(ai_analysis.risk_assessment, 1.0)
    
    # 오탐지 확률을 고려한 보정
    false_positive_correction = 1.0 - (ai_analysis.false_positive_probability * 0.5)
    
    # 최소 감지 개수 체크 (더 엄격하게)
    if len(valid_detections) < MIN_DETECTIONS_FOR_WARNING:
        base_score = min(15, current_risk)  # 더 낮은 제한
    elif len(valid_detections) < MIN_DETECTIONS_FOR_DANGER and ai_analysis.risk_assessment in ["low", "medium"]:
        base_score = min(25, current_risk)  # 위험도 제한
    else:
        base_score = blockage_score + volume_score + areas_score
    
    # AI 분석이 낮은 위험으로 판단하면 점수 감소 (더 엄격하게)
    if ai_analysis.risk_assessment == "low":
        final_score = base_score * 0.1 * ai_weight * confidence_multiplier * false_positive_correction
    elif ai_analysis.risk_assessment == "medium":
        final_score = base_score * 0.3 * ai_weight * confidence_multiplier * false_positive_correction
    elif ai_analysis.risk_assessment == "high":
        final_score = base_score * 0.6 * ai_weight * confidence_multiplier * false_positive_correction
    else:  # critical
        final_score = base_score * 0.8 * ai_weight * confidence_multiplier * false_positive_correction
    
    # AI 심각도 점수와 결합 (더 보수적으로)
    combined_score = (final_score * 0.4) + (ai_analysis.severity_score * 0.2)
    
    # 동적 변화 적용 (더 보수적으로)
    if dynamic_change < 0:  # 감소하는 경우
        # 감소량을 더 크게 적용
        combined_score = max(0, current_risk + dynamic_change * 2.0)
    else:  # 증가하는 경우
        # 증가량을 더 제한적으로 적용
        combined_score = min(75, current_risk + dynamic_change * 0.5)
    
    # 상태 업데이트
    current_status.update({
        "blockage_percentage": blockage_analysis.blockage_percentage,
        "garbage_volume": blockage_analysis.garbage_volume,
        "flow_restriction": blockage_analysis.flow_restriction,
        "accumulated_areas": blockage_analysis.accumulated_areas,
        "ai_analysis": ai_analysis.model_dump()
    })
    
    # 점수 제한 (더 보수적으로)
    return min(combined_score, 70), ai_analysis  # 최대 70%로 제한

def calculate_risk_score(detections: List[DetectionData]) -> float:
    """기존 호환성을 위한 래퍼 함수"""
    score, _ = calculate_risk_score_with_ai(detections)
    return score

def get_risk_level(score: float) -> str:
    """위험도 레벨 결정"""
    if score >= RISK_THRESHOLDS["danger"][0]:
        return "danger"
    elif score >= RISK_THRESHOLDS["warning"][0]:
        return "warning"
    else:
        return "safe"

def get_pipe_status(risk_level: str) -> str:
    """파이프 상태 텍스트"""
    status_map = {
        "safe": "정상 - 원활한 흐름",
        "warning": "주의 - 축적량 증가",
        "danger": "위험 - 막힘 가능성 높음"
    }
    return status_map.get(risk_level, "알 수 없음")

def get_time_since_last_detection() -> float:
    """마지막 감지로부터 경과 시간 (분)"""
    if not recent_detections:
        return 10.0  # 기본값: 10분
    
    try:
        last_detection = recent_detections[-1]
        last_time = datetime.fromisoformat(last_detection.timestamp.replace('Z', '+00:00'))
        now = datetime.now()
        time_diff = (now - last_time).total_seconds() / 60  # 분 단위
        return max(0.1, time_diff)  # 최소 0.1분
    except:
        return 5.0  # 오류시 기본값

def calculate_dynamic_risk_change(detections: List[DetectionData], current_risk: float) -> float:
    """동적 위험도 변화 계산"""
    if not detections:
        # 쓰레기가 없으면 자연 감소
        time_since_last = get_time_since_last_detection()
        decay_rate = 1.5  # 분당 1.5% 감소
        decay_amount = min(decay_rate * time_since_last, current_risk)
        return -decay_amount
    
    # 최근 감지 분석 (최근 5분)
    now = datetime.now()
    recent_detections_5min = []
    
    for d in detections[-10:]:  # 최근 10개만 확인
        try:
            det_time = datetime.fromisoformat(d.timestamp.replace('Z', '+00:00'))
            minutes_ago = (now - det_time).total_seconds() / 60
            if minutes_ago <= 5:  # 5분 이내
                recent_detections_5min.append(d)
        except:
            continue
    
    if not recent_detections_5min:
        # 최근 5분 내 감지가 없으면 감소
        time_since_last = get_time_since_last_detection()
        decay_rate = 1.0  # 분당 1% 감소
        decay_amount = min(decay_rate * time_since_last, current_risk)
        return -decay_amount
    
    # 최근 감지가 있으면 위험도 증가 (더 보수적으로)
    recent_count = len(recent_detections_5min)
    avg_confidence = sum(d.confidence for d in recent_detections_5min) / len(recent_detections_5min)
    
    # 신뢰도가 높고 감지가 많을수록 위험도 증가 (더 제한적으로)
    increase_rate = min(recent_count * 2 * avg_confidence, 8)  # 최대 8% 증가
    
    return increase_rate

def analyze_with_ai(detections: List[DetectionData], blockage_analysis: BlockageAnalysis) -> AIAnalysis:
    """AI 기반 위험도 분석"""
    if not detections:
        return AIAnalysis(
            risk_assessment="low",
            confidence_level=0.9,
            reasoning="감지된 쓰레기가 없어 안전한 상태입니다.",
            recommendations=["정기적인 모니터링을 계속하세요."],
            false_positive_probability=0.0,
            trend_analysis="안정적",
            severity_score=0.0
        )
    
    # 최근 감지 분석 (최근 10개)
    recent_detections = detections[-10:] if len(detections) > 10 else detections
    now = datetime.now()
    
    # 시간 분포 분석
    time_distribution = []
    for d in recent_detections:
        try:
            det_time = datetime.fromisoformat(d.timestamp.replace('Z', '+00:00'))
            minutes_ago = (now - det_time).total_seconds() / 60
            time_distribution.append(minutes_ago)
        except:
            continue
    
    # 신뢰도 분석
    avg_confidence = sum(d.confidence for d in recent_detections) / len(recent_detections)
    high_confidence_count = sum(1 for d in recent_detections if d.confidence > 0.8)
    confidence_ratio = high_confidence_count / len(recent_detections)
    
    # 쓰레기 유형 분석
    garbage_types = {}
    for d in recent_detections:
        garbage_types[d.garbage_type] = garbage_types.get(d.garbage_type, 0) + 1
    
    # AI 분석 로직
    risk_factors = []
    severity_score = 0.0
    
    # 동적 변화 분석
    current_risk = current_status.get("risk_score", 0)
    previous_risk = current_status.get("previous_risk_score", current_risk)
    risk_change = current_risk - previous_risk
    
    # 1. 막힘률 분석 (더 엄격하게)
    if blockage_analysis.blockage_percentage > 80:
        risk_factors.append("막힘률이 80%를 초과하여 매우 심각한 상황")
        severity_score += 40
    elif blockage_analysis.blockage_percentage > 60:
        risk_factors.append("막힘률이 60%를 초과하여 심각한 상황")
        severity_score += 25
    elif blockage_analysis.blockage_percentage > 40:
        risk_factors.append("막힘률이 40%를 초과하여 주의가 필요")
        severity_score += 10
    elif blockage_analysis.blockage_percentage > 20:
        risk_factors.append("막힘률이 20%를 초과하여 모니터링 필요")
        severity_score += 5
    
    # 2. 신뢰도 분석 (더 엄격하게)
    if avg_confidence < 0.8:
        risk_factors.append("평균 신뢰도가 낮아 오탐지 가능성 높음")
        severity_score -= 15  # 신뢰도가 낮으면 위험도 대폭 감소
    elif avg_confidence > 0.95:
        risk_factors.append("매우 높은 신뢰도로 정확한 감지")
        severity_score += 8
    elif avg_confidence > 0.85:
        risk_factors.append("높은 신뢰도로 정확한 감지")
        severity_score += 3
    
    # 3. 시간 분포 분석 (더 엄격하게)
    if time_distribution:
        recent_count = sum(1 for t in time_distribution if t <= 5)  # 5분 이내
        if recent_count >= 5:
            risk_factors.append("최근 5분 내 다수 감지로 급속한 축적")
            severity_score += 25
        elif recent_count >= 3:
            risk_factors.append("최근 5분 내 여러 감지로 축적 증가")
            severity_score += 15
        elif recent_count >= 1:
            risk_factors.append("최근 감지로 지속적 모니터링 필요")
            severity_score += 5
    
    # 4. 쓰레기 유형 분석 (더 엄격하게)
    dangerous_types = ["plastic_bag", "cloth", "paper", "organic"]
    dangerous_count = sum(garbage_types.get(t, 0) for t in dangerous_types)
    if dangerous_count >= 5:
        risk_factors.append("막힘 위험이 높은 쓰레기 다수 감지")
        severity_score += 20
    elif dangerous_count >= 3:
        risk_factors.append("막힘 위험이 높은 쓰레기 여러 개 감지")
        severity_score += 10
    
    # 5. 축적 영역 분석 (더 엄격하게)
    if blockage_analysis.accumulated_areas >= 8:
        risk_factors.append("다수의 축적 영역으로 분산된 막힘")
        severity_score += 15
    elif blockage_analysis.accumulated_areas >= 5:
        risk_factors.append("여러 축적 영역으로 막힘 위험")
        severity_score += 8
    
    # 6. 동적 변화 분석 (더 엄격하게)
    if risk_change > 10:
        risk_factors.append("위험도가 급속히 증가하는 상황")
        severity_score += 20
    elif risk_change > 5:
        risk_factors.append("위험도가 점진적으로 증가")
        severity_score += 10
    elif risk_change < -10:
        risk_factors.append("위험도가 급속히 감소하는 개선 상황")
        severity_score -= 15
    elif risk_change < -5:
        risk_factors.append("위험도가 점진적으로 감소")
        severity_score -= 8
    
    # 7. 추세 분석 (더 엄격하게)
    if len(detections) >= 30:  # 더 많은 데이터 필요
        recent_15 = detections[-15:]
        older_15 = detections[-30:-15]
        recent_avg = sum(d.area for d in recent_15) / len(recent_15)
        older_avg = sum(d.area for d in older_15) / len(older_15)
        
        if recent_avg > older_avg * 2.0:  # 더 큰 증가 필요
            risk_factors.append("쓰레기 크기가 급속히 증가하는 추세")
            severity_score += 15
        elif recent_avg > older_avg * 1.5:
            risk_factors.append("쓰레기 크기가 증가하는 추세")
            severity_score += 8
        elif recent_avg < older_avg * 0.3:  # 더 큰 감소 필요
            risk_factors.append("쓰레기 크기가 급속히 감소하는 추세")
            severity_score -= 10
        elif recent_avg < older_avg * 0.5:
            risk_factors.append("쓰레기 크기가 감소하는 추세")
            severity_score -= 5
    
    # 오탐지 확률 계산 (더 엄격하게)
    false_positive_prob = 0.0
    if avg_confidence < 0.8:
        false_positive_prob = 0.4
    if len(recent_detections) < 5:
        false_positive_prob += 0.3
    if len(recent_detections) < 3:
        false_positive_prob += 0.2
    
    # 위험도 평가 (더 엄격하게)
    if severity_score >= 70:  # 임계값 상향 조정
        risk_assessment = "critical"
        if risk_change > 10:
            reasoning = "다중 위험 요소가 복합적으로 작용하여 매우 위험한 상황이며, 위험도가 급속히 증가하고 있습니다."
        else:
            reasoning = "다중 위험 요소가 복합적으로 작용하여 매우 위험한 상황"
    elif severity_score >= 50:  # 임계값 상향 조정
        risk_assessment = "high"
        if risk_change > 5:
            reasoning = "여러 위험 요소가 확인되어 높은 위험도이며, 위험도가 증가하는 추세입니다."
        else:
            reasoning = "여러 위험 요소가 확인되어 높은 위험도"
    elif severity_score >= 25:  # 임계값 상향 조정
        risk_assessment = "medium"
        if risk_change < -5:
            reasoning = "일부 위험 요소가 확인되어 주의가 필요하지만, 위험도가 감소하는 개선 추세입니다."
        else:
            reasoning = "일부 위험 요소가 확인되어 주의가 필요"
    else:
        risk_assessment = "low"
        if risk_change < -10:
            reasoning = "대부분의 지표가 안전 범위 내에 있으며, 위험도가 급속히 감소하는 좋은 상황입니다."
        elif risk_change < -5:
            reasoning = "대부분의 지표가 안전 범위 내에 있으며, 위험도가 감소하는 개선 추세입니다."
        else:
            reasoning = "대부분의 지표가 안전 범위 내에 있음"
    
    # 권장사항 생성
    recommendations = []
    if risk_assessment in ["critical", "high"]:
        recommendations.append("즉시 정비팀에 연락하여 점검을 요청하세요.")
        recommendations.append("해당 구간의 물 흐름을 모니터링하세요.")
    if blockage_analysis.blockage_percentage > 30:
        recommendations.append("정기적인 청소 일정을 앞당기세요.")
    if avg_confidence < 0.7:
        recommendations.append("카메라 렌즈를 점검하고 정확도를 높이세요.")
    if len(recent_detections) < 5:
        recommendations.append("더 많은 데이터를 수집하여 분석 정확도를 높이세요.")
    
    # 동적 추세 분석
    current_risk = current_status.get("risk_score", 0)
    previous_risk = current_status.get("previous_risk_score", current_risk)
    risk_change = current_risk - previous_risk
    
    if risk_change > 5:
        trend_analysis = "급속 악화"
    elif risk_change > 2:
        trend_analysis = "악화"
    elif risk_change < -5:
        trend_analysis = "급속 개선"
    elif risk_change < -2:
        trend_analysis = "개선"
    elif abs(risk_change) <= 2:
        trend_analysis = "안정"
    else:
        trend_analysis = "불안정"
    
    # 이전 위험도 저장
    current_status["previous_risk_score"] = current_risk
    
    return AIAnalysis(
        risk_assessment=risk_assessment,
        confidence_level=min(avg_confidence, 0.95),
        reasoning=reasoning,
        recommendations=recommendations,
        false_positive_probability=false_positive_prob,
        trend_analysis=trend_analysis,
        severity_score=min(severity_score, 100.0)
    )

def update_status(detections_list: List[DetectionData]):
    """전역 상태 업데이트 (AI 분석 포함)"""
    risk_score, ai_analysis = calculate_risk_score_with_ai(detections_list)
    current_status["risk_score"] = risk_score
    current_status["risk_level"] = get_risk_level(risk_score)
    current_status["pipe_status"] = get_pipe_status(current_status["risk_level"])
    current_status["total_detections"] = len(detections_list)
    current_status["ai_analysis"] = ai_analysis.model_dump()
    
    if detections_list:
        current_status["last_detection"] = detections_list[-1].timestamp
        current_status["accumulation_rate"] = len(detections_list)

async def broadcast_to_clients(data: Dict[str, Any]):
    """WebSocket 브로드캐스트"""
    if not connected_clients:
        return
    
    message = json.dumps(data, default=str)
    disconnected = []
    
    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception as e:
            logger.warning(f"클라이언트 전송 실패: {e}")
            disconnected.append(client)
    
    for client in disconnected:
        if client in connected_clients:
            connected_clients.remove(client)

# ==================== API 엔드포인트 ====================

@app.post("/detect", summary="쓰레기 감지 데이터 처리")
async def process_detection(data: DetectionData):
    """쓰레기 감지 데이터 처리 - 신뢰성 검증 및 중복 방지"""
    try:
        # 1단계: 유효성 검사
        if not is_valid_detection(data):
            logger.debug(f"유효하지 않은 감지 무시: {data.garbage_type} (신뢰도: {data.confidence:.2f}, 면적: {data.area})")
            return {
                "success": True,
                "invalid": True,
                "reason": f"Low confidence ({data.confidence:.2f}) or small area ({data.area})",
                "risk_score": current_status["risk_score"],
                "risk_level": current_status["risk_level"]
            }
        
        # 2단계: 중복 감지 확인
        if is_duplicate_detection(data):
            logger.debug(f"중복 감지 무시: {data.garbage_type}")
            return {
                "success": True,
                "duplicate": True,
                "risk_score": current_status["risk_score"],
                "risk_level": current_status["risk_level"]
            }
        
        # 3단계: 새로운 감지 저장
        recent_detections.append(data)
        logger.info(f"🗑️ 유효한 쓰레기 감지: {data.garbage_type} (신뢰도: {data.confidence:.2f}, 면적: {data.area})")
        
        # 4단계: 상태 업데이트
        detections_list = list(recent_detections)
        previous_risk_score = current_status.get("risk_score", 0)
        update_status(detections_list)
        
        previous_level = current_status.get("previous_level", "safe")
        current_level = current_status["risk_level"]
        current_status["previous_level"] = current_level
        
        # 5단계: 유의미한 변화 확인 (더 엄격하게)
        risk_change = abs(current_status["risk_score"] - previous_risk_score)
        significant_change = (risk_change >= 10.0) or (current_level != previous_level and current_level != "safe")
        
        # 알림 생성
        alert = None
        if current_level in ["warning", "danger"] and current_level != previous_level:
            blockage_info = current_status.get("blockage_percentage", 0)
            flow_restriction = current_status.get("flow_restriction", "알 수 없음")
            garbage_volume = current_status.get("garbage_volume", 0)
            
            detailed_message = (
                f"{'⚠️' if current_level == 'warning' else '🚨'} "
                f"하수구 {'주의보' if current_level == 'warning' else '위험'}!\n"
                f"• 막힘률: {blockage_info}%\n"
                f"• 흐름 제한: {flow_restriction}\n"
                f"• 축적 쓰레기량: {garbage_volume}cm³\n"
                f"• 위험도: {current_status['risk_score']:.1f}%"
            )
            
            alert = AlertData(
                level=current_level,
                message=detailed_message,
                timestamp=datetime.now(),
                risk_score=current_status['risk_score']
            )
            
            recent_alerts.appendleft(alert)
            current_status["alerts_today"] += 1
            logger.warning(f"🚨 알림 발생: {detailed_message}")
        
        # 유의미한 변화시만 브로드캐스트
        if significant_change:
            broadcast_data = {
                "type": "detection",
                "data": data.model_dump(),
                "status": current_status,
                "alert": alert.model_dump() if alert else None,
                "blockage_analysis": {
                    "blockage_percentage": current_status.get("blockage_percentage", 0),
                    "garbage_volume": current_status.get("garbage_volume", 0),
                    "flow_restriction": current_status.get("flow_restriction", "알 수 없음"),
                    "accumulated_areas": current_status.get("accumulated_areas", 0)
                },
                "ai_analysis": current_status.get("ai_analysis", {})
            }
            
            await broadcast_to_clients(broadcast_data)
        
        return {
            "success": True,
            "duplicate": False,
            "significant_change": significant_change,
            "risk_score": current_status["risk_score"],
            "risk_level": current_level,
            "blockage_percentage": current_status.get("blockage_percentage", 0),
            "flow_restriction": current_status.get("flow_restriction", "알 수 없음"),
            "alert_created": alert is not None
        }
        
    except Exception as e:
        logger.error(f"감지 처리 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status", response_model=StatusResponse)
async def get_status():
    """현재 시스템 상태 조회"""
    return StatusResponse(**current_status)

@app.get("/blockage-analysis", response_model=BlockageAnalysis)
async def get_blockage_analysis():
    """현재 하수구 막힘 분석 결과"""
    detections_list = list(recent_detections)
    return analyze_pipe_blockage(detections_list)

@app.get("/detections")
async def get_recent_detections(limit: int = 20):
    """최근 감지 기록 조회"""
    detections = list(recent_detections)[-limit:]
    return {
        "detections": [d.model_dump() for d in detections],
        "total": len(recent_detections),
        "limit": limit
    }

@app.get("/alerts")
async def get_recent_alerts(limit: int = 10):
    """최근 알림 조회"""
    alerts = list(recent_alerts)[:limit]
    return {
        "alerts": [a.model_dump() for a in alerts],
        "total": len(recent_alerts),
        "limit": limit
    }

@app.post("/reset")
async def reset_system():
    """시스템 상태 초기화"""
    global current_status
    
    recent_detections.clear()
    recent_alerts.clear()
    
    current_status = {
        "risk_score": 0.0,
        "risk_level": "safe",
        "total_detections": 0,
        "last_detection": None,
        "alerts_today": 0,
        "pipe_status": "정상 - 원활한 흐름",
        "accumulation_rate": 0.0,
        "blockage_percentage": 0.0,
        "garbage_volume": 0.0,
        "flow_restriction": "없음",
        "accumulated_areas": 0
    }
    
    await broadcast_to_clients({
        "type": "reset",
        "status": current_status
    })
    
    return {"success": True, "message": "시스템이 초기화되었습니다."}

# ==================== 비디오 스트리밍 ====================

from fastapi.responses import StreamingResponse

@app.get("/video_feed")
async def video_feed():
    """실시간 비디오 스트리밍"""
    def generate():
        while True:
            if current_frame is not None:
                ret, buffer = cv2.imencode('.jpg', current_frame)
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                # 기본 이미지
                black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(black_frame, 'Camera not active', (200, 240), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret, buffer = cv2.imencode('.jpg', black_frame)
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            import time
            time.sleep(0.033)  # ~30 FPS
    
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/update_frame")
async def update_frame(frame_data: dict):
    """카메라 프레임 업데이트"""
    global current_frame, camera_active
    
    try:
        frame_base64 = frame_data.get('frame')
        if frame_base64:
            frame_bytes = base64.b64decode(frame_base64)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is not None:
                current_frame = frame
                camera_active = True
                return {"success": True, "message": "Frame updated"}
        
        return {"success": False, "message": "Invalid frame data"}
        
    except Exception as e:
        logger.error(f"프레임 업데이트 오류: {e}")
        return {"success": False, "message": str(e)}

# ==================== WebSocket ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """실시간 데이터 스트리밍"""
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"새 클라이언트 연결. 총 연결: {len(connected_clients)}")
    
    try:
        # 연결 즉시 현재 상태 전송
        initial_data = {
            "type": "initial",
            "status": current_status,
            "recent_detections": [d.model_dump() for d in list(recent_detections)[-5:]],
            "recent_alerts": [a.model_dump() for a in list(recent_alerts)[:3]],
            "ai_analysis": current_status.get("ai_analysis", {})
        }
        await websocket.send_text(json.dumps(initial_data, default=str))
        
        # 연결 유지
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
                
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        logger.info(f"클라이언트 연결 해제. 남은 연결: {len(connected_clients)}")
    except Exception as e:
        logger.error(f"WebSocket 오류: {e}")
        if websocket in connected_clients:
            connected_clients.remove(websocket)

# ==================== 헬스체크 ====================

@app.get("/health")
async def health_check():
    """서버 상태 확인"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "connected_clients": len(connected_clients),
        "camera_active": camera_active,
        "total_detections": len(recent_detections),
        "version": "2.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")