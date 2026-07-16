# KNU AutoCAR 사용자 추종 시스템

Hanback AutoCAR Prime에서 실행하는 온디바이스 사용자 추종 및 Web 대시보드 프로젝트다.

## 주요 기능

- `pop.Pilot.Object_Follow` 기반 사람 검출
- 최초 가장 가까운 사람의 옷 색상·패턴 등록
- 옷 패턴 기반 사용자 재식별 및 5초 소실 검색
- 카메라 PAN/TILT 사용자 방향 추적
- LiDAR 거리 표시와 0.1 m 비상 안전거리 적용
- Bluetooth MAC 연결 상태 인증
- 차량 속도 제한, 수동 운전 및 비상정지 대시보드
- 오래된 카메라 프레임 폐기, 추론 주기 제한 및 메모리 정리
- 카메라 30 FPS, 추론 8 FPS, 대시보드 5 FPS

현재 소스 버전은 `v0.9.1`이다.

## 저장소 구성

```text
autocar/               실행 프로그램
config/                공개 가능한 설정과 환경변수 예시
device_update/         기존 장비를 v0.9.1로 갱신하는 ZIP과 설치기
tests/                 하드웨어 비의존 단위 테스트
DEVELOPMENT_LOG.md     날짜별 개발 로그
requirements-py36.txt  Python 3.6 호환 보조 패키지
```

모델 파일, 실제 MAC 주소, 비밀번호, 실행 로그, 백업 및 Python 캐시는 저장소에 포함하지 않는다.

## 장비 경로

```text
/home/soda/Project/python/notebook
```

## Jupyter에서 기존 장비 갱신

저장소의 `device_update` 폴더에 있는 다음 두 파일을 장비 작업 경로에 업로드한다.

- `KNU_RC_DEVICE_POP_NEAREST_OWNER_v0.9.1.zip`
- `install_device_nearest_owner.py`

Jupyter 셀에서 실행한다.

```python
%cd /home/soda/Project/python/notebook
!python3 install_device_nearest_owner.py
```

설치 전 실행 중인 `python3 -m autocar.main` 프로세스를 먼저 종료해야 한다. 설치기는 기존 소스와 설정을 `backups/`에 자동 백업한다.

## Jupyter에서 프로그램 실행

```python
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/home/soda/Project/python/notebook")

app_process = subprocess.Popen(
    [sys.executable, "-m", "autocar.main"],
    cwd=str(ROOT),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    universal_newlines=True,
    preexec_fn=os.setsid,
)

time.sleep(5)
print("PID:", app_process.pid)
print("대시보드: http://장비-IP:8080")
```

환경변수를 지정하지 않을 때 초기 대시보드 로그인은 `admin` / `change-me`다. 외부 네트워크에서 운용할 때는 반드시 `config/autocar.env.example`을 참고해 별도 자격 증명을 설정한다.

## Jupyter에서 프로그램 종료

```python
if "app_process" in globals() and app_process.poll() is None:
    os.killpg(os.getpgid(app_process.pid), signal.SIGTERM)
    try:
        app_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(app_process.pid), signal.SIGKILL)
        app_process.wait(timeout=5)

print("종료 코드:", app_process.poll())
```

## 장비 설정

실차 구동 전 `config/autocar.json`을 확인한다.

- `runtime.simulation`: 실차에서는 `false`
- `bluetooth.enabled`: Bluetooth 인증 사용 시 `true`
- `bluetooth.owner_mac`: 등록 사용자 장치의 실제 MAC
- `camera.flip_method`: 장착 방향에 맞게 보정
- `camera_tracking.tilt_center`: 초기값 `0`
- `driving.min_follow_speed`: `50`
- `driving.emergency_distance_m`: `0.1`

첫 실차 시험은 바퀴를 지면에서 띄운 상태에서 진행한다.

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

상세 변경 이력과 확인이 남은 하드웨어 항목은 [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)를 참고한다.
