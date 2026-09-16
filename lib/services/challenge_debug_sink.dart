/// Challenge 판정 로그를 서버로 보낸다.
///
/// 실기기 화면의 진단 패널은 프레임마다 바뀌어 읽을 수 없다. 같은 값을 PC에서
/// 보려고 `POST /debug/challenge`로 흘리고, 백엔드가
/// `backend/logs/challenge_debug.log`와 콘솔에 남긴다.
///
/// **Challenge 판정에 영향을 주지 않는다.**
/// - 실패해도 조용히 버린다(fire and forget). 로그를 못 보내는 것이 인증을
///   막을 이유가 없다.
/// - 프레임마다 왕복하지 않는다. 14fps면 초당 14번이 된다. 모아서 보낸다.
/// - 버퍼가 넘치면 **오래된 줄부터** 버린다. 최근 상황이 더 중요하다.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';

class ChallengeDebugSink {
  final ApiClient _api;

  /// 이 주기마다 모아서 보낸다.
  final Duration flushInterval;

  /// 버퍼 상한. 서버가 죽어 있어도 메모리가 늘지 않게 한다.
  final int maxBuffered;

  /// 한 번에 보낼 줄 수 상한. 서버 스키마와 맞춘다.
  static const int _maxPerRequest = 200;

  final String sessionId;
  final List<String> _buffer = <String>[];
  Timer? _timer;
  bool _sending = false;
  bool _closed = false;

  /// 보내지 못하고 버린 줄 수. 로그가 중간에 비면 이 수로 알 수 있다.
  int dropped = 0;

  ChallengeDebugSink(
    this._api, {
    required this.sessionId,
    this.flushInterval = const Duration(milliseconds: 400),
    this.maxBuffered = 600,
  });

  void add(String line) {
    if (_closed) return;
    _buffer.add(line);
    if (_buffer.length > maxBuffered) {
      // 오래된 쪽을 버린다. 실패 직전 상황이 남아야 한다.
      dropped += _buffer.length - maxBuffered;
      _buffer.removeRange(0, _buffer.length - maxBuffered);
    }
    _timer ??= Timer.periodic(flushInterval, (_) => unawaited(flush()));
  }

  Future<void> flush() async {
    if (_sending || _buffer.isEmpty) return;
    _sending = true;
    final List<String> batch =
        _buffer.take(_maxPerRequest).toList(growable: false);
    try {
      await _api.sendChallengeDebug(sessionId: sessionId, lines: batch);
      _buffer.removeRange(0, batch.length);
    } catch (e) {
      // 서버가 없거나 엔드포인트가 꺼져 있을 수 있다. Challenge는 계속 돈다.
      debugPrint('challenge debug 로그 전송 실패 (무시): $e');
      _buffer.removeRange(0, batch.length);
      dropped += batch.length;
    } finally {
      _sending = false;
    }
  }

  /// 세션이 끝나면 남은 줄을 마저 보내고 멈춘다.
  Future<void> close() async {
    _closed = true;
    _timer?.cancel();
    _timer = null;
    // 마지막 결과 줄까지 도착해야 한 세션을 통째로 볼 수 있다.
    while (_buffer.isNotEmpty) {
      final int before = _buffer.length;
      await flush();
      if (_buffer.length >= before) break; // 더 못 보낸다
    }
  }
}
