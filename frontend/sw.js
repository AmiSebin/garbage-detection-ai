// Service Worker for Push Notifications
const CACHE_NAME = 'garbage-detection-v1';

// Service Worker 설치
self.addEventListener('install', (event) => {
    console.log('Service Worker 설치됨');
    self.skipWaiting();
});

// Service Worker 활성화
self.addEventListener('activate', (event) => {
    console.log('Service Worker 활성화됨');
    event.waitUntil(self.clients.claim());
});

// Push 메시지 수신
self.addEventListener('push', (event) => {
    console.log('Push 메시지 수신:', event);
    
    let notificationData = {
        title: '하수도 막힘 감지 시스템',
        body: 'Push 알림이 도착했습니다.',
        icon: '/favicon.ico',
        badge: '/favicon.ico',
        data: {
            url: '/'
        }
    };

    if (event.data) {
        try {
            const data = event.data.json();
            console.log('Push 데이터:', data);
            
            // 알림 레벨에 따른 아이콘과 메시지 설정
            if (data.level === 'danger') {
                notificationData.title = '🚨 하수구 위험 경고!';
                notificationData.body = data.message || '막힘 위험이 높습니다. 즉시 확인하세요.';
                notificationData.requireInteraction = true; // 사용자가 직접 닫을 때까지 유지
                notificationData.vibrate = [200, 100, 200, 100, 200]; // 진동 패턴
            } else if (data.level === 'caution') {
                notificationData.title = '🟠 하수구 경고';
                notificationData.body = data.message || '막힘 위험이 증가하고 있습니다.';
                notificationData.vibrate = [200, 100, 200];
            } else if (data.level === 'warning') {
                notificationData.title = '⚠️ 하수구 주의';
                notificationData.body = data.message || '쓰레기 축적량이 증가하고 있습니다.';
                notificationData.vibrate = [200];
            } else {
                notificationData.title = '📊 하수구 상태 업데이트';
                notificationData.body = data.message || '상태가 업데이트되었습니다.';
            }

            // 추가 데이터 설정
            if (data.risk_score) {
                notificationData.body += `\n위험도: ${data.risk_score.toFixed(1)}%`;
            }
            
            notificationData.data = {
                url: '/',
                level: data.level,
                risk_score: data.risk_score,
                timestamp: new Date().toISOString()
            };

        } catch (error) {
            console.error('Push 데이터 파싱 오류:', error);
        }
    }

    const options = {
        body: notificationData.body,
        icon: notificationData.icon,
        badge: notificationData.badge,
        data: notificationData.data,
        requireInteraction: notificationData.requireInteraction || false,
        vibrate: notificationData.vibrate || [200],
        actions: [
            {
                action: 'view',
                title: '대시보드 보기',
                icon: '/favicon.ico'
            },
            {
                action: 'close',
                title: '닫기'
            }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(notificationData.title, options)
    );
});

// 알림 클릭 처리
self.addEventListener('notificationclick', (event) => {
    console.log('알림 클릭됨:', event.notification.data);
    
    event.notification.close();

    if (event.action === 'view' || event.action === '') {
        // 대시보드 열기
        event.waitUntil(
            clients.matchAll({
                type: 'window',
                includeUncontrolled: true
            }).then((clientList) => {
                // 이미 열린 탭이 있으면 포커스
                for (const client of clientList) {
                    if (client.url.includes('/') && 'focus' in client) {
                        return client.focus();
                    }
                }
                // 새 탭 열기
                if (clients.openWindow) {
                    return clients.openWindow('/');
                }
            })
        );
    }
});

// 알림 닫기 처리
self.addEventListener('notificationclose', (event) => {
    console.log('알림 닫힘:', event.notification.data);
});