# 프리미어 색보정 자동 반복 도구 (2026-08-02)

비블에게 프레임을 내보내 달라고 부탁하지 않고 **내가 직접 렌더해서 재고 고칠 수 있다.**

## 렌더가 되는 방법

`export_frame` 은 성공이라 답하고 **파일을 안 만든다.** 대신 이걸 쓴다:

```javascript
app.encoder.launchEncoder();
app.encoder.encodeSequence(seq, outPath, presetPath, app.encoder.ENCODE_IN_TO_OUT, 0, 1);
```

- 프리셋은 앱 내장 `.epr` (`/Applications/Adobe Premiere Pro 2026/.../MediaIO/systempresets/...`)
- in/out 은 **MCP `set_sequence_in_out_points`** 로 설정한다. ExtendScript 의
  `setInPoint`/`getInPoint` 는 이 버전에서 동작하지 않는다(undefined 반환)
- **in/out 이 풀린 채로 돌면 AME 가 전체 시퀀스를 렌더해 큐를 막는다.** 이후 렌더가
  전부 실패하므로 AME 를 종료해 큐를 비워야 한다

## 반드시 지킬 것

1. **프로그램 출력을 렌더할 것.** V2 가 V1 을 덮으므로 V1 만 렌더하면 실제 화면과 다르다.
   캠별로 보려면 `videoTracks[i].setMute()` 로 껐다 켠다
2. **매 반복마다 눈으로 볼 것.** 수치 98% 인데 화면이 청록이었던 적이 있다
   (밝기를 뺀 밸런스 지표가 축퇴해를 허용 + 노출 과다로 벽이 254 클리핑돼 측정 왜곡)
3. **기울기 반복 갱신 말고 격자 탐색.** 부호를 두 번 틀려 발산했다.
   색온도는 **올리면 R−B 가 올라간다**(= B 가 내려간다). 후보를 렌더해 재고 최고를 고르면
   부호 실수가 원천적으로 안 생긴다
4. **판정 기준을 중간에 바꾸지 말 것.** 피부→벽→전체화면으로 옮겨 다니다 cam02 노출이
   0.85→0.18 까지 깎였다

## QE 인덱스 주의

`qe.getVideoTrackAt(t).getItemAt(i)` 의 i 는 **clips[i] 와 다르다** — 빈 구간까지 세기 때문
(실측 V1 QE 46 vs clips 45, V2 47 vs 45). 전체 클립에 이펙트를 얹을 때는 **시작 시각으로
매칭**한다. 인덱스로 하면 엉뚱한 클립에 붙는다(실제로 마지막 컷에 잘못 붙었다).
