# AutoCAR 사용자 추종 프로젝트 개발 로그

- 작성일: 2026-07-15
- 장치 프로젝트 경로: `/home/soda/Project/python/notebook`
- 대상 장비: Hanback AutoCAR Prime
- 문서 목적: 개발 내용, 장치 검증 결과, 장애 대응 내역 및 남은 검증 항목 기록

> 이 문서에서 `완료`는 실제 AutoCAR 장치에서 확인된 항목을 뜻한다. `적용 후 재검증` 항목은 코드나 설정 변경 절차를 작성했지만, 장치 재시작 후 최종 결과 확인이 아직 필요한 항목이다.

## 1. 개발 목표

- AutoCAR Prime에서 동작하는 온디바이스 사용자 추종 프로그램 개발
- ROS 없이 POP 라이브러리와 장치 기본 제어 API 사용
- 사람 검출, 손 흔들기 인증, 주인 재식별 및 추종 구현
- LiDAR 장애물 감지와 Bluetooth MAC 기반 사용자 인증 연동
- 카메라 PAN/TILT가 주인 방향을 따라가도록 제어
- 노트북 WebView 대시보드에서 영상, LiDAR, 상태 및 차량 제어 제공
- Jupyter, tmux, systemd 환경에서 운용 및 디버깅 가능하도록 구성

## 2. 장치 환경

| 항목 | 확인 내용 | 상태 |
|---|---|---|
| 장비 | AutoCAR Prime, NVIDIA Jetson Xavier 계열, aarch64 | 완료 |
| OS | Ubuntu 22.04로 전달받았으나 실제 장치 커널은 L4T R32.4.3 계열 | 실제 장치 기준 사용 |
| Python | 3.6.x | 완료 |
| CUDA | 10.2 계열 | 완료 |
| PyTorch | `1.4.0.post4` | 완료 |
| torchvision | `0.5.0a0` 계열 | 완료 |
| OpenCV | 4.3.0 계열 | 완료 |
| POP | 설치 및 장치 제어 사용 가능 | 완료 |
| ROS1 | 미설치, 사용하지 않음 | 완료 |
| 프로젝트 경로 | `/home/soda/Project/python/notebook` | 완료 |

환경 확인 중 Numba가 다음 경고를 출력했다.

```text
Insufficiently recent colorama version found. Numba requires colorama >= 0.3.9
```

이는 경고이며 프로그램 중단 오류는 아니지만, 같은 Python 3.6 환경에서 `colorama >= 0.3.9`인지 확인할 필요가 있다.

## 3. 주요 아키텍처 결정

### 3.1 영상 및 사람 검출

- 모든 영상 처리 크기는 32의 배수만 허용한다.
- 장치 해상도와 추론 해상도는 `320 x 320`으로 사용한다.
- 기존 YOLOv5 로컬 PyTorch 로더는 장치의 구형 PyTorch와 호환 문제가 있어 운영 경로에서 제외했다.
- 장치 내장 POP 모델을 사용하는 `Pilot.Object_Follow` 방식으로 전환했다.
- 장치 기본 모델은 POP 경로의 `yolov4-tiny`를 사용한다.
- `Pilot.Camera(width=320, height=320)`와 `Pilot.Object_Follow(camera)` 조합의 사람 검출을 확인했다.
- 최초 모델 로딩과 최초 추론은 느릴 수 있으나, 이후 추론 자체는 정상 작동하는 것을 확인했다.

### 3.2 상태 흐름

```text
IDLE
  -> WAIT_GESTURE
  -> REGISTER_OWNER
  -> FOLLOW_OWNER
  -> SEARCH_OWNER
  -> REAUTHENTICATION
```

- 대시보드에서 추종을 시작한다.
- Bluetooth 인증 장치가 연결돼 있어야 추종을 시작할 수 있다.
- 손 흔들기를 감지한 사람을 주인으로 등록한다.
- 주인을 잃으면 5초 동안 검색한다.
- 5초 안에 찾지 못하면 재인증 상태로 전환한다.
- 재인증에는 다시 손 흔들기를 사용한다.
- 얼굴 인식은 사용하지 않는다.

### 3.3 차량 및 카메라 제어

- 차량 이동은 POP 차량 제어 함수와 `forward()`, `backward()` 계열 API를 사용한다.
- 조향값은 `-1.0 ~ 1.0` 범위로 제한한다.
- 카메라 PAN/TILT가 등록된 주인의 영상 중심 오차를 따라가도록 제어기를 추가했다.
- PAN/TILT 이동은 데드밴드, 최대 이동량 및 갱신 주기를 적용해 흔들림을 줄였다.
- 카메라가 회전한 각도는 차량 조향과 LiDAR-카메라 방향 결합에 보상한다.
- 대시보드에서 추종 및 수동운전 공통 속도 제한을 변경할 수 있도록 API와 슬라이더를 추가했다.

카메라 추적 기본값은 다음과 같다.

```json
{
  "enabled": true,
  "pan_center": 90.0,
  "tilt_center": 45.0,
  "pan_min": 20.0,
  "pan_max": 160.0,
  "tilt_min": 0.0,
  "tilt_max": 90.0,
  "pan_gain_deg": 6.0,
  "tilt_gain_deg": 4.0,
  "max_step_deg": 3.0,
  "deadband_x": 0.12,
  "deadband_y": 0.12,
  "update_interval_seconds": 0.12,
  "pan_direction": 1.0,
  "tilt_direction": -1.0
}
```

PAN/TILT 실제 방향이 반대라면 다음 값으로 보정한다.

- 좌우 반대: `pan_direction = -1.0`
- 상하 반대: `tilt_direction = 1.0`

## 4. LiDAR

| 항목 | 확인 내용 | 상태 |
|---|---|---|
| 장치 | RPLIDAR 계열 | 완료 |
| 포트 | `/dev/ttyUSB0` | 완료 |
| baud rate | `115200` | 완료 |
| `256000` | descriptor 오류로 사용하지 않음 | 완료 |
| 상태 | model 40, firmware 1.28, hardware 7, health Good | 완료 |
| 장애물 정지 | 전방 장애물 정지 및 해제 후 복구 확인 | 완료 |

LiDAR 전방각은 장치 장착 방향에 따라 보정해야 한다. Windows 작업본의 기본값보다 실제 장치의 `config/autocar.json` 값과 현장 측정값을 우선한다.

주인 거리는 다음 조건에서만 표시된다.

1. 대시보드 상태가 `FOLLOW_OWNER`이다.
2. 카메라가 주인 후보를 선택했다.
3. 주인 중심 방향과 LiDAR 점의 각도 매칭에 성공했다.

따라서 `IDLE` 상태의 주인 거리가 `--`로 보이는 것은 정상이다. `FOLLOW_OWNER`에서도 `--`가 계속되면 `front_angle_deg`, `clockwise`, 카메라 FOV 및 `association_window_deg`를 실제 장착 방향으로 교정해야 한다. 매칭 범위를 과도하게 넓히면 주변 장애물을 주인 거리로 잘못 사용할 수 있으므로 현장 교정 없이 임의 확대하지 않는다.

## 5. Bluetooth 인증

- 인증 장치 MAC은 `/home/soda/Project/python/notebook/config/autocar.json`의 `bluetooth.owner_mac`에 저장한다.
- 확인된 MAC은 `F0:D7:93:3A:32:08`이다.
- BlueZ 기준 `Paired: True`, `Connected: True`, `Trusted: True`를 확인했다.
- Bluetooth 연결 해제 시 차량 즉시 정지 동작을 확인했다.

### 5.1 발생 장애

기존 모니터가 1초마다 `bluetoothctl info <MAC>`을 새 프로세스로 실행하면서 다음 오류가 발생했다.

```text
WARNING autocar.adapters.bluetooth: Bluetooth status failed:
[Errno 12] Cannot allocate memory
```

당시 메모리는 약 7.6 GiB 중 3.5 GiB를 사용 가능했으므로 단순 물리 RAM 고갈로 보기는 어려웠다. CUDA/PyTorch가 실행 중인 프로세스에서 반복적으로 subprocess를 만드는 구조가 원인이었다.

### 5.2 조치

- `bluetoothctl` 반복 실행을 제거했다.
- `org.bluez.Device1`의 `Connected` 속성을 D-Bus로 직접 조회하도록 변경했다.
- 장치에서 Python `dbus` 모듈 사용 가능 여부와 실제 연결값 `True`를 확인했다.
- 변경 후에는 새 프로세스를 매초 생성하지 않는다.

## 6. WebView 대시보드

구현 기능:

- 사용자 검출 영상
- LiDAR 점 지도
- 상태, 사유, FPS 및 연결 상태 표시
- 추종 시작/정지
- 인증 사용자 수동운전
- 비상정지 및 복구
- 차량 속도 제한 설정
- 카메라 PAN/TILT 현재값 표시

대시보드 상태와 LiDAR의 기본 폴링 주기는 500 ms였다. 지연 개선을 위해 250 ms로 낮추는 변경 절차를 작성했다. 장치 적용 여부는 재시작 후 브라우저 `Ctrl+F5`와 개발자 도구를 통해 재확인해야 한다.

실제 AI 루프는 약 4~5 FPS로 관찰됐다. 따라서 현재 구조에서 새 검출 결과의 최소 지연은 약 0.2~0.25초이다. 설정상 스트림이 15 FPS여도 분석 완료 프레임은 AI 처리속도보다 빠르게 갱신되지 않는다. 실제 영상 자체를 15 FPS에 가깝게 보여주려면 카메라 표시 루프와 AI 추론 루프를 분리해야 한다.

## 7. 추종거리 설정 변경

사용자가 최종 지정한 거리 정책은 다음과 같다.

```json
{
  "target_distance_m": 0.3,
  "stop_distance_m": 0.2,
  "emergency_distance_m": 0.1
}
```

- 목표 추종 간격: 0.3 m
- 일반 정지 거리: 0.2 m
- 최소 안전거리/비상정지 거리: 0.1 m

이 값은 설정 변경 절차까지 작성했다. 장치 재시작 후 실제 `config/autocar.json` 값과 물리 주행 결과를 다시 확인해야 한다.

> 주의: 정확한 RPLIDAR 모델의 최소 측정거리가 확정되지 않았다. 센서가 0.1 m를 안정적으로 측정하지 못할 수 있으므로, 최초 검증은 바퀴를 들어 올리고 속도 제한을 5 이하로 설정한 상태에서 수행한다.

## 8. 프로세스 중복 실행 장애

### 8.1 증상

- 카메라와 LiDAR 대시보드 갱신 지연
- LiDAR가 ONLINE에서 OFFLINE으로 변경
- 다음 로그가 반복됨

```text
Check bit not equal to 1
read failed: device reports readiness to read but returned no data
device disconnected or multiple access on port?
Too many bytes in the input buffer
```

### 8.2 원인

동시에 두 개의 AutoCAR 프로세스가 실행되고 있었다.

```text
PID 2065  /usr/bin/python3 -m autocar.main
PID 31680 /usr/bin/python3 -m autocar.main
```

두 프로세스가 `/dev/ttyUSB0`과 카메라를 동시에 사용하면서 LiDAR 데이터가 손상되고 화면 갱신이 불안정해졌다.

### 8.3 조치

- `/proc/*/cmdline`에서 정확히 `autocar.main`을 실행하는 PID만 찾도록 실행/종료 함수를 작성했다.
- 실행 전에 기존 PID가 있으면 새 프로세스를 만들지 않는다.
- 종료 시 먼저 `SIGTERM`으로 차량 정지와 정상 종료를 요청한다.
- 5초 안에 종료되지 않으면 남은 AutoCAR PID에만 `SIGKILL`을 적용한다.
- 재실행 전 AutoCAR PID가 0개인지, 실행 후 정확히 1개인지 확인한다.

정상 종료가 5초 안에 끝나지 않은 사례가 있었다. 카메라 `capture.release()` 또는 LiDAR 종료 처리의 블로킹 가능성이 있으므로 종료 경로 개선이 남아 있다.

## 9. 실행 환경과 인증정보

운영 인증정보는 명령행에 매번 직접 쓰지 않고 다음 파일에 한 번 저장한다.

```text
/home/soda/Project/python/notebook/config/autocar.env
```

저장 항목:

```bash
KNU_RC_SECRET_KEY='...'
KNU_RC_USER='...'
KNU_RC_PASSWORD='...'
```

- 파일 권한은 `0600`으로 제한한다.
- 값은 개발 로그나 Git 저장소에 기록하지 않는다.
- 실행 스크립트 `/home/soda/Project/python/notebook/run-autocar.sh`가 환경파일과 `config/autocar.json`을 로드한다.
- 대시보드는 `http://<AutoCAR-IP>:8080`으로 접속한다.

Jupyter에서는 등록된 `start_autocar()`와 `stop_autocar()` 함수를 사용한다. 프로그램 실행 후 `autocar.main` PID가 정확히 하나인지 반드시 확인한다.

## 10. 패키지 및 배포 산출물

장치의 POP 카메라/검출기 및 현재 설정을 보존한 상태로 카메라 추적과 속도 제어 기능을 병합했다.

| 파일 | 용도 | SHA-256 |
|---|---|---|
| `outputs/KNU_RC_DEVICE_CAMERA_SPEED_v0.2.0.zip` | 장치 전용 업데이트 | `EEA978D12BD6903578973F689D5509BE9EB8152DDB51E0DBF3B4CB081EFC0CE4` |
| `outputs/install_device_camera_speed.py` | Jupyter 설치 스크립트 | `2EFFF6004ADB527F454FB43297E980EC765C34501EE3F254F553406630339DC2` |

설치기는 기존 파일과 설정을 `backups/`에 보관하고, 필요한 파일만 교체하며, 기존 POP/카메라/LiDAR/Bluetooth/TTS 설정을 유지한다.

Bluetooth D-Bus 변경과 2026-07-15 이후 현장 조정값은 위 v0.2.0 패키지 생성 이후 변경 사항이다. 다음 배포본을 만들 때 반드시 포함해야 한다.

## 11. 완료된 검증

- AutoCAR Prime 장치 환경 및 주요 라이브러리 확인
- POP 기반 사람 검출과 실제 카메라 입력 확인
- 320 x 320 영상 및 32배수 제한 확인
- 실제 차량 전진과 조향 방향 확인
- LiDAR `/dev/ttyUSB0`, 115200 baud 및 health 확인
- 장애물 정지와 장애물 제거 후 상태 복구 확인
- Bluetooth 연결 및 연결 해제 즉시 정지 확인
- 대시보드 로그인과 인증 사용자 수동운전 확인
- 사용자 추종, 사용자 분실 시 정지, 5초 검색 후 재인증 확인
- 대시보드 비상정지 확인
- 카메라 PAN/TILT 추적 및 속도 설정 기능 코드 병합
- 로컬 단위 테스트 13개 통과
- Python 3.6 문법 및 대시보드 JavaScript 문법 검사 통과
- Bluetooth D-Bus 연결 조회 확인
- 중복 실행으로 인한 LiDAR 장애 원인 확인

## 12. 남은 필수 검증

1. AutoCAR 프로세스 단일 실행 잠금 적용 및 재부팅 후 중복 실행 방지 확인
2. `target_distance_m=0.3`, `stop_distance_m=0.2`, `emergency_distance_m=0.1` 실제 장치 설정 확인
3. 저속에서 실제 추종 간격과 제동 오차 측정
4. RPLIDAR의 정확한 모델명과 0.1 m 측정 가능 여부 확인
5. `FOLLOW_OWNER` 상태에서 주인 거리 표시 확인
6. LiDAR 전방각과 카메라 PAN 각도 결합 교정
7. 대시보드 250 ms 갱신 적용 여부 및 지연 재측정
8. 영상 표시와 AI 추론 루프 분리 필요성 판단
9. 정상 종료가 지연되는 카메라/LiDAR 종료 경로 개선
10. `knu-rc.service` systemd 설치 및 `active` 상태 확인
11. 재부팅 후 systemd 자동 시작 확인
12. systemd와 tmux 상호 배타 실행 확인
13. 30~60분 연속 추종 soak test 수행
14. 카메라 실패, LiDAR 분리, Bluetooth 미연결 상태의 fail-safe 재검증
15. 로그 순환, 설정 백업 및 복구 절차 검증

## 13. 다음 작업 권장 순서

1. 물리 전원을 끄거나 바퀴를 들어 올린다.
2. AutoCAR 프로세스가 없는지 확인한다.
3. 거리 설정과 대시보드 변경 내용을 확인한다.
4. 프로그램을 하나만 실행한다.
5. 대시보드 속도를 5 이하로 제한한다.
6. Bluetooth, 카메라 및 LiDAR ONLINE 상태를 확인한다.
7. 손 흔들기로 주인을 등록하고 `FOLLOW_OWNER` 상태를 확인한다.
8. 주인 거리 표시와 0.3 m 추종 간격을 실제 자로 측정한다.
9. 문제가 없으면 속도를 5, 10, 15 순서로 단계적으로 높인다.
10. 결과를 기록한 뒤 systemd/tmux 및 장시간 시험으로 진행한다.

## 14. 2026-07-15 장시간 성능 및 메모리 관리 업데이트

장시간 실행 후 추론과 손 흔들기 인식이 느려지는 현상에 대응하기 위해 v0.3.0 업데이트를 작성했다.

### 변경 내용

- 카메라와 추론 크기를 320x320으로 고정
- 대시보드 MJPEG 스트림을 15 FPS에서 5 FPS로 변경
- 상태와 LiDAR 대시보드 폴링을 500 ms에서 250 ms로 변경
- 카메라 프레임은 큐를 쌓지 않고 최신 프레임 한 장만 덮어쓰는 기존 구조 유지
- 사라진 track ID의 손 흔들기 시계열 삭제
- 사라진 track ID의 96x96 모션 비교 프레임 삭제
- 주인 등록 완료 후 임시 특징 샘플 배열 해제
- 300초마다 Python 순환 객체 GC 수행
- CUDA 캐시는 자동으로 강제 해제하지 않음
- 프로세스 RSS 메모리와 정리 횟수를 telemetry 및 대시보드에 표시
- 목표거리와 비상거리를 HTML 고정 문구 대신 실제 설정에서 표시
- 목표/정지/비상거리 기본값과 적용값을 0.3/0.2/0.1 m로 통일

### 검증 결과

- Python 3.6 문법 검사 통과
- 대시보드 JavaScript 문법 검사 통과
- 단위 테스트 15개 통과
- 장치 전용 설치 시뮬레이션 통과
- POP `PersonDetector(..., camera_adapter=self.camera)` 생성자 보존 확인
- 기존 detector backend, Bluetooth MAC, LiDAR 및 TTS 설정을 덮어쓰지 않는 선택 병합 확인

### 산출물

| 파일 | SHA-256 |
|---|---|
| `outputs/KNU_RC_DEVICE_PERFORMANCE_MEMORY_v0.3.0.zip` | `20ACCDD43DF51279A0318E5F387A37ABA8253787A6FB1D9FD2C97155902B5E15` |
| `outputs/install_device_performance_memory.py` | `BB216E4D9054C99BDF937FBCE0B1CFE1D45B11CF2A6427C45A43BDC134D5BCA4` |

장치 적용 후 30~60분 soak test로 FPS, RSS 메모리, 제스처 인식시간 및 LiDAR 안정성을 비교해야 한다.
