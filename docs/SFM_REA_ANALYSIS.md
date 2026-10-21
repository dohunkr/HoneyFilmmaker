# SFM 내부 인터페이스 역분석 결과 (REA, ifm.dll)

대상: `game/bin/tools/ifm.dll` (SFM 엔진, 17,160,704 bytes, PE x86)
SHA-256: `12504c248047e181d31a8500fb6693d1a2d3c805e841fc2227e41aa4e2d2b47e`
분석 도구: REA 6.5.0 (엔진 없이 PE 문자열/정적 경로 확인)

## 결정적 발견

### 1. 모델은 시퀀스가 있어야 로드된다
```
MDL file contains no sequences
MDL file contains no activities
```
`sfm.CreateModel()`이 `None`을 반환하는 직접적 원인.
→ 로드 대상 .mdl에는 반드시 `$sequence` 데이터가 있어야 함.

`game/tf/models/player/hwm/scout.mdl`은 **형제 `scout_animations.mdl`이 없다** → 시퀀스 0개 → 로드 실패.
`game/tf/models/player/scout.mdl`은 **형제 `scout_animations.mdl`이 존재** → 시퀀스 존재 → 로드 가능.

### 2. 가상 경로 형식
```
contentdir:models
%s\%s.mdl          (디렉터리 + 파일명)
makefiledir:models\dmx
```
→ 가상 경로는 `models/<file>.mdl` 형태. `models/player/hwm/...`가 아니라 **파일 직속**이 유효.

### 3. 모델 생성은 MDL Picker 다이얼로그를 거친다
```
CQMDLPickerDialog
CQMDLPickerDialogHelper::SelectModelAndCreateAnimationSetWithDialogAccepted()
CQMDLPickerDialogHelper::SelectModelAndCreateAnimationSetWithDialogCanceled()
Create Animation Set for New Model        (CreateAnimationSetForNewModel)
```
→ SFM 내부의 모델 생성 경로는 MDL Picker → `SelectModelAndCreateAnimationSetWithDialogAccepted`.
   이 함수가 실제 GameModel을 만든다. 스크립트 `sfm.CreateModel()`은 이 경로의 축약형이며,
   필요한 컨텍스트(선택된 셰이빙셋/다이얼로그 상태)가 없으면 `None`을 준다.

### 4. 애니메이션셋 이름 규칙
```
%s_GameModel
```
→ GameModel은 `<name>_GameModel` 형태로 이름 붙는다.

### 5. SFM은 QC/스튜디오 파이프라인도 쓴다
```
%1/../bin/studiomdl.exe
scustomqc / bcustomqc
ERROR! Can't Get QC - Can't Compute DmeGameModel name and dir: %1
```
→ 커스텀 모델은 QC로 컴파일되어야 함. 표준 TF2 모델은 이 경로가 아님.

## 결론

1. `sfm.CreateModel(path)`는 **경로만으로 동작하지 않는다**. 컨텍스트 + 시퀀스 있는 모델이 필요.
2. 확실히 동작하는 경로는 **GUI MDL Picker** (`Animation Set Editor [+] → Create Animation Set for New Model`).
3. 따라서 자동 배치는 **GUI를 Qt로 자동 조작**하는 방식으로 구현한다
   (`src/bridge/honey_gui_place.py`, `sfm_init.py`에 내장).
4. fast path로는 시퀀스 있는 일반 모델(`models/player/scout.mdl`)을 먼저 시도한다.

## 사용한 경로 (검증됨)
| 역할 | 경로 | 시퀀스 |
|---|---|---|
| SEORIN | `models/player/scout.mdl` | `scout_animations.mdl` 있음 |
| IMUGYEOM | `models/player/soldier.mdl` | 있음 |
| MUMYEONG | `models/bots/soldier_boss/bot_soldier_boss.mdl` | 있음 |
| (함정) | `models/player/hwm/scout.mdl` | **없음 → 로드 불가** |
