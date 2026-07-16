# AutoCAR 사용자 추종 프로젝트 통합 개발로그

- 최초 작성일: 2026-07-15
- 최종 정리일: 2026-07-16
- 장비: Hanback AutoCAR Prime
- 장비 프로젝트 경로: `/home/soda/Project/python/notebook`
- 현재 배포 버전: `v0.7.2`
- 최신 패키지: `outputs/KNU_RC_DEVICE_Y_POSE_v0.7.2.zip`

## 날짜별 개발 타임라인

| 날짜 | 개발 단계 | 주요 결과 |
|---|---|---|
| 2026-07-13 | 요구사항 및 기본 구조 수립 | ROS 없는 AutoCAR 서비스, 온디바이스 AI, WebView 대시보드 방향 확정 |
| 2026-07-14 | 실제 장비 환경 검증 및 인수인계 | 장비 경로·POP·YOLO·차량·LiDAR·Bluetooth·운영환경 확인, 남은 검증 분리 |
| 2026-07-15 | 성능 개선부터 Y 포즈 인증까지 집중 개발 | v0.3.0~v0.7.2 구현, 현장 오류 재현 및 누적 패키지 생성 |
| 2026-07-16 | 문서 통합 및 날짜별 재정리 | 개발로그 통합, 완료·미완료 검증과 최신 배포본 명시 |

---

### 2026-07-13 — 요구사항 정리와 기본 아키텍처

#### 요구사항

- AutoCAR Prime에서 ROS1 없이 동작
- 온디바이스 YOLO, CNN/Pose, 한국어 TTS 사용
- 노트북 WebView 대시보드 제공
- 카메라, LiDAR, Bluetooth, 차량, PAN/TILT를 하나의 서비스로 통합
- 주피터에서 설치·실행·종료·로그 확인
- systemd와 tmux를 이용한 운영·디버깅 구조 준비

#### 주요 결정

- 장비 설치 경로를 `/home/soda/Project/python/notebook`으로 통일
- 영상 입력 크기는 32의 배수만 허용
- 얼굴인식은 사용하지 않음
- Bluetooth 등록 MAC 연결 해제 시 즉시 정지
- LiDAR 최소 비상 안전거리를 0.1m로 설정
- 대시보드 수동운전은 인증된 사용자만 허용
- 대시보드 시작과 자율 추종은 상호 배타적으로 제어

#### 초기 산출물

- AutoCAR Python 패키지 기본 구조
- 장치별 adapter 구조
- 상태 머신과 대시보드 API
- systemd 및 tmux 보조 스크립트

---

### 2026-07-14 — 실제 장비 검증과 인수인계

#### 확인 완료

- Python 3.6.x, CUDA 10.2, OpenCV 4.3, POP 환경 확인
- ROS1 미설치 및 미사용 확정
- 로컬 YOLOv5 PyTorch 모델 사용 확정
- 차량 `forward()`, `backward()` 계열 제어 방향 확인
- 카메라와 PAN/TILT 사용 가능 확인
- RPLIDAR 계열 장치와 `/dev/ttyUSB*` 연결 경로 확인 진행
- BlueZ D-Bus를 통한 MAC 연결 확인 방식 확정
- 한국어 TTS와 필수 안내문구 확정
- 대시보드 필수 기능과 인증 정책 확정

#### 인수인계 기준

- 완료된 장비 검증은 반복하지 않음
- 남은 필수 검증부터 진행
- 차량 시험은 안전을 위해 바퀴를 띄운 상태에서 수행
- 실제 하드웨어 설정과 사용자별 보정값은 장비 config에 보존

#### 당시 남은 핵심 검증

- LiDAR baud rate와 회전 방향 확정
- 카메라 flip 및 PAN/TILT 방향 보정
- 실제 추종 속도와 조향 실측
- TTS 장비 출력 확인
- systemd/tmux 장시간 운용 확인

---

### 2026-07-15 — 집중 구현 및 현장 오류 해결

#### 1단계: 성능·지연 개선 (`v0.3.0`~`v0.3.1`)

- YOLO 입력 320x320 적용
- 대시보드 영상 5 FPS 적용
- 처리되지 못한 오래된 프레임 폐기
- 최신 프레임 단일 슬롯 구조 적용
- 주기적 메모리 정리와 제한된 이력 구조 적용
- 추론, 전체 처리, JPEG, 프레임 나이 및 API RTT 지연 측정 추가

#### 2단계: 카메라 기반 추종 (`v0.4.0`)

- 카메라 캡처 30 FPS, YOLO·제어 목표 8 FPS로 분리
- LiDAR 주인 거리를 속도 계산에서 제외
- 사용자 바운딩박스 높이 비율로 속도 계산
- PAN 오프셋과 화면 X 좌표를 이용해 차량 조향
- LiDAR는 전방 장애물 안전정지와 거리 참고표시에 유지

#### 3단계: 사용자 외형 등록 (`v0.5.0`)

- 화면 중앙의 같은 사람을 1.5초 유지하면 등록 후보로 선택
- 상의 HSV 2x3 공간 패턴 저장
- CDS 채널 7을 이용한 조도 보정
- 밝기 변형 패턴을 함께 저장해 조도 변화 대응
- 이동 최소속도 50, 대시보드 범위 50~99 적용

#### 4단계: Pose 인증 도입 (`v0.6.0`)

- NVIDIA `trt_pose` ResNet18 224x224 모델 설치
- Pose CUDA 원시 출력 확인
- 스켈레톤 손 흔들기 인증 구현
- 인증할 때만 Pose를 목표 4 FPS로 실행

#### 5단계: PyTorch 1.4 및 YOLO 호환 (`v0.6.1`~`v0.6.3`)

- PyTorch 1.4에서 로컬 `torch.hub source=local` 미지원 문제 해결
- YOLOv5 `hubconf.py` 직접 로딩 방식 적용
- 누락 Arial.ttf 대신 시스템 글꼴을 오프라인 제공
- YOLO의 torch/torchvision 자동 업그레이드 차단
- PyTorch 1.4용 SiLU 호환 계층 추가
- 잘못 설치된 사용자 torch 1.10.2와 torchvision 0.11.3 제거 절차 정리

#### 6단계: Pose 네이티브 충돌 제거 (`v0.6.4`)

- 제스처 실행 시 프로세스 `-11` 종료 확인
- 사용 가능 메모리 6.5GB로 OOM이 아님을 확인
- 원인을 `trt_pose.ParseObjects` C++ 확장 충돌로 분리
- 다중인물 PAF 연결을 제거하고 관절 heatmap 최고점을 순수 PyTorch로 추출
- 초기 카메라 TILT를 35도로 변경하고 시작 직후 실제 각도 명령 전송

#### 7단계: Y 포즈 인증 (`v0.7.0`~`v0.7.2`)

- 손 흔들기를 정적 Y 포즈로 변경
- 정면 사용자에서 COCO 좌우가 화면과 반대로 보이는 문제 수정
- 저해상도에서 팔꿈치가 누락되는 문제를 고려해 팔꿈치를 선택사항으로 변경
- 양쪽 어깨와 손목을 필수 관절로 유지
- 6개 Pose 샘플 중 4개 이상 성공하도록 조정
- 손목 높이·간격 조건을 실제 장비 영상에 맞게 조정
- 실패 원인을 대시보드 상태 문자열로 표시

#### 2026-07-15 최종 결과

- 최신 배포본 `v0.7.2` 생성
- Python 및 JavaScript 문법 검사 통과
- 단위 테스트 29개 통과
- 누적 설치 시뮬레이션 통과
- 실제 장비에서 Y 포즈 `matched → FOLLOW_OWNER` 최종 검증은 남음

---

### 2026-07-16 — 문서 통합과 다음 검증 준비

#### 문서 작업

- 기존 상세 개발로그 보존
- 환경·아키텍처·문제 해결·버전 이력을 통합 문서로 정리
- 날짜별 타임라인을 별도 구성해 개발 흐름을 명확히 표시
- 완료 항목과 남은 필수 장비 검증을 분리

#### 현재 기준점

- 기준 버전: `v0.7.2`
- 기준 인증 방식: 중앙 사용자 선택 후 Y 포즈
- 기준 TILT: 35도
- 기준 Pose 처리: C++ `ParseObjects` 미사용
- 다음 작업: 실제 장비에서 대시보드 실패 사유를 확인하며 `FOLLOW_OWNER` 전환 검증

---

## 1. 프로젝트 목표

AutoCAR Prime에서 ROS 없이 온디바이스 AI 기반 사용자 인증 및 추종 기능을 구현한다.

주요 기능은 다음과 같다.

- 전방 카메라와 YOLOv5를 이용한 사람 검출
- Pose 스켈레톤 기반 주인 인증
- 등록된 옷 색상·공간 패턴과 CDS 조도를 이용한 주인 재식별
- 카메라 PAN/TILT를 이용한 사용자 방향 추적
- 카메라상 사용자 크기를 이용한 추종 속도 계산
- LiDAR를 이용한 주인 거리 참고값과 전방 장애물 안전정지
- Bluetooth MAC 연결 상태를 이용한 사용자 인증 보조 및 연결 해제 시 즉시 정지
- 한국어 TTS 안내
- 노트북 WebView 대시보드에서 영상, LiDAR, 상태, 수동운전, 속도 제한 및 비상정지 제공
- 주피터에서 설치·실행·로그 확인·종료 가능

## 2. 확인된 장비 환경

| 항목 | 확인값 |
|---|---|
| OS | Ubuntu 22.04 / SODA OS 기반 환경 |
| Python | 3.6.x |
| PyTorch | `1.4.0.post4` |
| Torchvision | `0.5.0a0+85b8fbf` |
| CUDA | `10.2.89` |
| cuDNN | `8.0.0.180-1` |
| TensorRT | `7.1.3.0` |
| OpenCV | `4.3.0` |
| POP | 설치 및 사용 가능 |
| ROS1 | 미설치, 사용하지 않음 |
| YOLO | 로컬 YOLOv5 v6.0, PyTorch 모델 |
| Pose | NVIDIA `trt_pose` ResNet18 224x224 |
| LiDAR | RPLIDAR 계열, `/dev/ttyUSB0`에서 동작 확인 |
| Bluetooth | BlueZ D-Bus, 등록 MAC 방식 |

Pose 모델 경로는 다음과 같다.

```text
/home/soda/Project/python/notebook/models/resnet18_baseline_att_224x224_A_epoch_249.pth
```

장비에서 확인한 Pose 원시 출력은 정상이다.

```text
cmap: (1, 18, 56, 56)
paf:  (1, 42, 56, 56)
```

## 3. 현재 소프트웨어 구조

```text
CameraAdapter ──> YOLO PersonDetector ──> IoU Tracker
                       │
                       ├─> 중앙 사용자 선택
                       ├─> trt_pose 관절 heatmap
                       └─> 옷 HSV 2x3 공간 패턴

CDS ────────────────> 등록/현재 밝기 보정
LiDAR ──────────────> 주인 거리 참고 + 장애물 안전정지
Bluetooth ──────────> MAC 연결 인증 + 연결 해제 비상정지

Owner Profile ──────> 사용자 재식별
Camera Controller ──> PAN/TILT 추적
Driving Controller ─> 카메라 사용자 크기 기반 속도 + 화면/PAN 기반 조향

Flask/Waitress ─────> 인증 대시보드, MJPEG, 상태 API, 수동운전
```

주요 모듈은 다음과 같다.

| 파일 | 역할 |
|---|---|
| `autocar/service.py` | 전체 장치와 상태 제어 통합 |
| `autocar/state_machine.py` | 추종 상태 전이 |
| `autocar/adapters/vision.py` | YOLO 및 Pose 추론 |
| `autocar/wave.py` | Y 포즈와 기존 제스처 판정기 |
| `autocar/owner.py` | 옷 색상·밝기 패턴 등록 및 재식별 |
| `autocar/controller.py` | 차량 속도·조향 및 카메라 추적 |
| `autocar/adapters/lidar.py` | LiDAR 연결, 장애물 및 참고 거리 |
| `autocar/adapters/bluetooth.py` | BlueZ D-Bus MAC 연결 확인 |
| `autocar/adapters/cds.py` | POP CDS 조도 입력 |
| `autocar/web/app.py` | 대시보드 API와 인증 |

## 4. 현재 상태 흐름

```text
INIT
  └─> IDLE
        ├─> WAIT_OWNER
        │     └─> VERIFY_GESTURE
        │            ├─> REGISTER_OWNER
        │            └─> FOLLOW_OWNER
        │                   ├─> SEARCH_OWNER
        │                   ├─> BLOCKED
        │                   └─> REAUTHENTICATION
        ├─> MANUAL
        └─> EMERGENCY
```

현재 인증 및 추종 순서는 다음과 같다.

1. 대시보드에서 추종 시작
2. Bluetooth, 카메라, LiDAR 및 Pose 준비상태 확인
3. 화면 중앙의 같은 사람을 1.5초 유지
4. Y 포즈 인증과 동시에 옷/CDS 패턴 수집
5. 사용자 프로필 확정
6. 카메라 기반 추종 시작
7. 주인을 잃으면 즉시 정지 후 5초간 검색
8. 검색 실패 시 TTS 안내 후 재인증

## 5. 현재 카메라·추론 설정

| 설정 | 값 |
|---|---:|
| 카메라 캡처 | 30 FPS |
| YOLO 추론·제어 목표 | 8 FPS |
| 대시보드 영상 | 5 FPS |
| YOLO 입력 | 320x320 |
| Pose 입력 | 224x224 |
| Pose 인증 추론 | 4 FPS |
| 초기 PAN | 90도 |
| 초기 TILT | 35도 |

영상 크기는 장비 요구조건에 따라 32의 배수만 허용한다. 카메라는 최신 프레임 하나만
유지하고 처리되지 못한 과거 프레임은 폐기한다. Pose는 인증 단계에서만 실행하며 일반
추종 중에는 실행하지 않는다.

## 6. 현재 Y 포즈 인증 정책

손 흔들기보다 저 FPS에서 안정적인 정적 Y 포즈를 사용한다.

```text
 \ O /
   |
  / \
```

판정 조건은 다음과 같다.

- 필수 관절: 양쪽 어깨와 양쪽 손목
- 팔꿈치는 저해상도 검출 누락을 고려해 선택사항
- 두 손목이 어깨보다 어깨너비의 0.15배 이상 높아야 함
- 두 손목이 몸 중심의 서로 반대편에 있어야 함
- 손목 사이 간격이 어깨너비의 1.2배 이상이어야 함
- Pose 6개 샘플 중 4개 이상 조건을 만족해야 함
- 약 1.2초 동안 유지
- 인증 제한시간 5초
- 예상 추종 시작시간 약 3~5초

COCO의 left/right는 사람의 해부학적 방향이므로, 정면 촬영 시 화면 좌우가 바뀌는 점을
반영해 손목 이름별 화면 방향을 가정하지 않는다.

실패 시 대시보드 상태 사유에 다음과 같은 원인을 표시한다.

```text
Y pose: missing-left_wrist
Y pose: left-wrist-not-high
Y pose: wrists-not-opposite
Y pose: wrists-too-close
Y pose: matched
```

## 7. 사용자 프로필 등록

- 얼굴인식은 사용하지 않는다.
- 중앙 사용자 선택 후 상의 영역을 2x3 격자로 나눈다.
- 각 구역의 HSV 색상·공간 패턴을 저장한다.
- 등록 샘플은 20프레임이다.
- 밝기 배율 0.60, 0.80, 1.00, 1.20, 1.40의 예상 패턴을 함께 저장한다.
- POP `Cds(7).read()`를 약 0.25초 주기로 읽는다.
- 등록 조도와 현재 조도의 비율 및 역비율을 모두 비교한다.
- CDS가 불안정해도 저장된 밝기 변형 패턴으로 재식별할 수 있다.

## 8. 추종 및 안전 정책

### 8.1 속도

- 정지 명령: 0
- 움직이는 최소 추종 속도: 50
- 대시보드 설정 범위: 50~99
- 카메라 바운딩박스 높이 비율로 속도 계산
- 목표 사용자 높이 비율: 0.72
- 현재 프레임 강제정지 높이 비율: 0.88
- LiDAR 주인 거리는 속도 계산에 사용하지 않음

최소 속도 50 정책 때문에 정지 직전 속도 변화가 클 수 있으므로 바퀴를 띄운 상태에서
초기 시험해야 한다.

### 8.2 조향과 카메라

- 화면 X 좌표와 PAN 오프셋을 함께 사용해 차량 조향
- TILT는 카메라 상하 추적에만 사용
- 프로그램 시작 시 PAN 90도, TILT 35도 명령 전송
- 추종 시작 및 재인증 시 카메라 중심 복귀

### 8.3 LiDAR

- LiDAR 주인 거리는 대시보드 참고값으로만 표시
- 주인 거리가 검출되지 않아도 카메라 추종은 계속 수행
- 전방 장애물 0.2m 미만이면 정지
- 전방 장애물 0.1m 이하이면 비상정지
- 추종 중 LiDAR 오프라인은 안전을 위해 비상정지

## 9. 주요 문제와 해결 기록

### 9.1 Python·주피터 실행

- `ROOT`가 문자열이면 `ROOT / "run-autocar.sh"`에서 TypeError 발생
- `ROOT = Path("/home/soda/Project/python/notebook")`로 통일
- 실행 셸만 종료되고 `autocar.main`이 남는 문제는 프로세스 그룹 종료로 수정
- 로그는 `autocar-start.log`에 기록해 시작 실패 원인을 확인

### 9.2 Bluetooth

- 대시보드에서 Bluetooth 연결을 인식하지 못하는 문제 확인
- BlueZ D-Bus에서 등록 MAC의 Paired, Connected, Trusted가 모두 True임을 확인
- `Errno 12 Cannot allocate memory`는 실제 전체 RAM 부족이 아니라 기존 프로세스 및
  D-Bus 호출 상태를 함께 점검하도록 변경
- 연결 해제 시 차량은 즉시 비상정지

### 9.3 영상·LiDAR 대시보드 지연

- 카메라 추론 크기를 320x320으로 유지
- 카메라 30 FPS, 추론 8 FPS, 대시보드 5 FPS로 역할 분리
- 최신 프레임 단일 슬롯으로 오래된 프레임 폐기
- JPEG, 추론, 전체 처리, 프레임 나이 및 API RTT 지연 telemetry 추가
- 주기적 `gc.collect()`와 제한된 이력 구조로 장시간 메모리 누적 방지

### 9.4 LiDAR 거리 때문에 1.5m에서 정지

- 2D LiDAR가 주인 다리를 놓치면 주인 거리 계산이 사라지는 구조 확인
- LiDAR 주인 거리를 추종 속도에서 완전히 분리
- 카메라상 사용자 크기만으로 전진 속도 계산
- LiDAR는 장애물 안전정지와 거리 참고표시에만 유지

### 9.5 업데이트 ZIP 파일 누락

- 설치 ZIP에 `autocar/adapters/cds.py`가 빠져 시작 실패
- 이후 패키지를 AutoCAR 실행 코드 전체를 포함하는 누적 패키지로 변경
- 장비별 `config/autocar.json`, 모델, YOLO 저장소는 보존하고 필요한 설정만 병합

### 9.6 PyTorch 1.4와 로컬 YOLOv5

- PyTorch 1.4는 `torch.hub.load(..., source="local")`을 지원하지 않음
- YOLOv5 `hubconf.py`의 `custom()`을 직접 불러오는 호환 로더 추가
- YOLOv5의 Arial.ttf 다운로드 URL이 HTTP 308을 반환하는 문제 해결
- 시스템 DejaVu Sans 등을 `/home/soda/.config/Ultralytics/Arial.ttf`에 자동 배치
- YOLO가 실행 중 torch와 torchvision을 자동 업그레이드하지 못하도록 차단
- PyTorch 1.4에 없는 `torch.nn.SiLU` 호환 모듈 추가

잘못 설치된 사용자 버전은 다음과 같았다.

```text
torch 1.10.2
torchvision 0.11.3
```

이 버전이 `/home/soda/.local`에 남아 `libgomp ... cannot allocate memory in static TLS block`
오류를 발생시켰다. 사용자 경로의 잘못된 패키지를 제거하고 `/usr/local`의 JetPack용
PyTorch 1.4로 복구했다.

### 9.7 Pose 인증 시 프로세스 `-11` 종료

- Y 포즈 실행 시 대시보드 연결과 AutoCAR 프로세스가 함께 종료
- 종료 코드 `-11`, 사용 가능 메모리 6.5GB로 OOM이 아님을 확인
- Python 예외 없이 종료되어 `trt_pose.ParseObjects` C++ 확장 충돌로 판정
- 중앙 단일 사용자 crop에서는 PAF 다중인물 연결이 필요하지 않으므로 C++ 파서 제거
- 각 관절 heatmap의 최고점을 순수 PyTorch 연산으로 추출
- 이후 Pose 인증이 전체 웹 서버를 종료시키는 네이티브 호출 경로 제거

### 9.8 Y 포즈가 통과하지 않는 문제

- 정면 사용자에서 COCO left/right가 화면 좌우와 반대로 나타나는 문제 수정
- 224x224 입력과 저각도 카메라에서 팔꿈치가 자주 누락되는 문제 확인
- 팔꿈치를 필수 관절에서 제외하고 양쪽 어깨·손목 기반으로 변경
- 판정 조건을 실제 장비 영상에 맞게 조정
- 실패 원인을 상태 문자열로 노출

## 10. 버전별 요약

| 버전 | 주요 변경 |
|---|---|
| v0.1.0 | 기본 AutoCAR 서비스, 대시보드, 장치 어댑터 구성 |
| v0.2.0 | 카메라 PAN/TILT 추적과 대시보드 속도 설정 |
| v0.3.0 | 최신 프레임 폐기, 메모리 관리, 320x320·5 FPS 대시보드 |
| v0.3.1 | 로컬 지연 측정 telemetry 추가 |
| v0.4.0 | 카메라 30 FPS, YOLO 8 FPS, 카메라 크기 기반 추종 |
| v0.5.0 | 중앙 사용자 선택, 옷 패턴, CDS 보정, 최소 속도 50 |
| v0.6.0 | `trt_pose` 스켈레톤 손 흔들기 인증 |
| v0.6.1 | PyTorch 1.4 로컬 YOLO hubconf 호환 |
| v0.6.2 | YOLO 오프라인 글꼴 제공 |
| v0.6.3 | YOLO 자동 업그레이드 차단 및 SiLU 호환 |
| v0.6.4 | C++ Pose 파서 제거, heatmap 관절 추출, TILT 35도 |
| v0.7.0 | 손 흔들기에서 정적 Y 포즈로 변경 |
| v0.7.1 | 정면 사용자 COCO 좌우 반전 수정 |
| v0.7.2 | 팔꿈치 선택사항, 판정 완화, 실시간 실패 사유 추가 |

## 11. 최신 배포 파일

| 파일 | SHA-256 |
|---|---|
| `outputs/KNU_RC_DEVICE_Y_POSE_v0.7.2.zip` | `3CE11F59AED4E873293CFDFAEEEFF3C1C11D305A59D2160C9D87F9ECE3531447` |
| `outputs/install_device_skeleton_wave.py` | `469E4FEAF263F4CB9B0893A9E9957E71673CEEEC01BE3645AF0D62E7852487E2` |

## 12. 주피터 설치 및 실행

### 12.1 설치

장비 최상위 경로에 최신 ZIP과 설치기를 업로드한다.

```python
from pathlib import Path

ROOT = Path("/home/soda/Project/python/notebook")
installer = ROOT / "install_device_skeleton_wave.py"

exec(
    compile(installer.read_text(), str(installer), "exec"),
    {"__name__": "__main__"}
)
```

### 12.2 실행

```python
import subprocess
import time

log_path = ROOT / "autocar-start.log"
log_handle = open(str(log_path), "w")

app_process = subprocess.Popen(
    [str(ROOT / "run-autocar.sh")],
    cwd=str(ROOT),
    stdout=log_handle,
    stderr=subprocess.STDOUT,
    start_new_session=True
)

time.sleep(30)
log_handle.flush()

if app_process.poll() is None:
    print("AutoCAR 실행 성공, PID:", app_process.pid)
else:
    log_handle.close()
    print(log_path.read_text(errors="replace"))
```

대시보드는 노트북과 AutoCAR가 같은 네트워크일 때 다음 형식으로 접속한다.

```text
http://AutoCAR-IP:8080
```

장비에서 확인된 IP는 시점에 따라 다음 인터페이스에 존재했다.

```text
192.168.101.101
192.168.0.51
192.168.2.1
```

노트북과 같은 서브넷의 IP를 선택해야 한다. 서버가 정상 실행되면 `0.0.0.0:8080`에서
대기한다.

## 13. 검증 현황

### 완료

- Pose 모델 CUDA 원시 출력 확인
- PyTorch 1.4 및 Torchvision 0.5 복구 확인
- YOLOv5 v6.0 로컬 모델 로딩 확인
- 카메라 CSI 스트림 시작 확인
- LiDAR 스캔 시작 확인
- Waitress `0.0.0.0:8080` 서비스 확인
- BlueZ 등록 MAC의 Paired, Connected, Trusted 확인
- C++ Pose 파서 충돌 원인 분리 및 제거
- Python 문법 검사
- JavaScript 문법 검사
- 단위 테스트 29개 통과
- v0.7.2 누적 설치 시뮬레이션 통과

### 남은 필수 장비 검증

1. v0.7.2에서 실제 Y 포즈가 `matched` 후 `FOLLOW_OWNER`로 전환되는지 확인
2. 실패 시 대시보드의 `Y pose: ...` 사유 기록
3. 한 사람만 있는 환경과 두 사람이 겹치는 환경 비교
4. TILT 35도에서 머리·양손·허리가 모두 화면에 포함되는지 확인
5. Y 포즈 인증 후 옷 패턴 재식별 유지 여부 확인
6. 주인 소실 5초 후 재인증 및 TTS 확인
7. Bluetooth 연결 해제 즉시 차량 정지 확인
8. 장애물 0.2m 정지와 0.1m 비상정지 실측
9. LiDAR `Too many bytes in input buffer` 반복 발생 시 baud rate와 장치 점유 확인
10. 바퀴를 띄운 상태에서 속도 50~99 및 정지 전환 확인
11. 30~60분 연속 운전으로 FPS, Pose 지연, RSS, CUDA 메모리 및 대시보드 지연 확인

## 14. 현재 주의사항

- Jetson용 PyTorch는 임의로 pip 업그레이드하지 않는다.
- `/home/soda/.local`에 별도 torch/torchvision이 설치되면 `/usr/local`의 JetPack 버전을
  가릴 수 있다.
- YOLO, Pose 모델 및 `config/autocar.json`은 백업 후 변경한다.
- 최소 이동속도 50 정책 때문에 첫 차량 시험은 반드시 바퀴를 띄운 상태에서 수행한다.
- 물리적 전원 스위치와 대시보드 비상정지를 즉시 사용할 수 있게 유지한다.
- LiDAR 주인 거리는 참고값이며 주인 속도 계산에는 사용하지 않는다.
- 얼굴정보는 수집하거나 저장하지 않는다.
