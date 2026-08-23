import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/core/hand_connections.dart';
import 'package:signid/core/theme.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/services/fake_landmark_source.dart';
import 'package:signid/widgets/capture_ring.dart';
import 'package:signid/widgets/hand_overlay_painter.dart';

void main() {
  test('FakeLandmarkSource가 21점 프레임을 실제 경과 시간과 함께 흘린다', () async {
    final source = FakeLandmarkSource();
    addTearDown(source.dispose);

    final collected = <HandFrame>[];
    final sub = source.frames.listen(collected.add);
    addTearDown(sub.cancel);

    await source.start();
    await Future<void>.delayed(const Duration(milliseconds: 600));
    await source.stop();

    expect(collected.length, greaterThan(10));
    for (final f in collected) {
      expect(f.landmarks.length, kLandmarkCount);
      expect(f.isComplete, isTrue);
      for (final lm in f.landmarks) {
        expect(lm.x, inInclusiveRange(0.0, 1.0));
        expect(lm.y, inInclusiveRange(0.0, 1.0));
      }
    }

    // tMs는 단조 증가해야 하고, 인덱스×33 같은 균등 간격이 아니어야 한다.
    for (var i = 1; i < collected.length; i++) {
      expect(collected[i].tMs, greaterThan(collected[i - 1].tMs));
    }
    final gaps = <int>{
      for (var i = 1; i < collected.length; i++)
        collected[i].tMs - collected[i - 1].tMs,
    };
    expect(gaps.length, greaterThan(1),
        reason: '모든 간격이 동일하면 실제 타임스탬프가 아니라 계산된 값이다');
  });

  test('HandOverlayPainter가 실제로 픽셀을 그린다', () async {
    const size = Size(240, 240);
    final frame = HandFrame(
      tMs: 0,
      landmarks: List.generate(
        kLandmarkCount,
        (i) => Landmark(0.3 + (i % 5) * 0.1, 0.2 + (i ~/ 5) * 0.15, 0),
      ),
      handedness: 'Right',
      score: 0.95,
    );

    final recorder = ui.PictureRecorder();
    HandOverlayPainter(frame: frame).paint(Canvas(recorder), size);
    final image = await recorder
        .endRecording()
        .toImage(size.width.toInt(), size.height.toInt());
    final bytes = await image.toByteData(format: ui.ImageByteFormat.rawRgba);

    var painted = 0;
    for (var i = 3; i < bytes!.lengthInBytes; i += 4) {
      if (bytes.getUint8(i) != 0) painted++;
    }
    expect(painted, greaterThan(500), reason: '뼈대와 점이 그려져야 한다');
  });

  testWidgets('CaptureRing이 진행률 아크와 함께 렌더링된다', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: const Scaffold(
          body: Center(
            child: CaptureRing(
              diameter: 280,
              borderColor: AppColors.ring,
              progress: 0.4,
              child: SizedBox.expand(),
            ),
          ),
        ),
      ),
    );
    expect(find.byType(CaptureRing), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
