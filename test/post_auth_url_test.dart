/// 인증 성공 후 "계속하기"로 넘어가는 주소는 서버가 정한다.
///
/// 이 인증이 **2차 인증**으로 쓰인다는 것을 보여주는 흐름이다. 주소를 앱에 박으면
/// 바꿀 때마다 다시 배포해야 한다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/models/server_config.dart';

void main() {
  ServerConfig configWithUrl(String? url) => ServerConfig.fromJson(
        <String, dynamic>{
          'enrollmentTakes': 3,
          'enrollmentGestures': 1,
          'captureDurationMs': 4000,
          'handRequired': 'right',
          'modelVersion': 'shared-dual-head-v1.1.0',
          if (url != null) 'postAuthUrl': url,
        },
      );

  test('서버가 준 주소를 그대로 쓴다', () {
    final ServerConfig c = configWithUrl('https://www.naver.com');
    expect(c.postAuthUrl, 'https://www.naver.com');
    expect(c.hasPostAuthUrl, isTrue);
  });

  test('주소를 바꾸면 앱 재배포 없이 따라간다', () {
    expect(
      configWithUrl('https://portal.example.com/sso').postAuthUrl,
      'https://portal.example.com/sso',
    );
  });

  test('서버가 주소를 안 주면 버튼을 숨긴다', () {
    // 오래된 서버에 붙었을 때 빈 주소로 브라우저를 열면 안 된다.
    expect(configWithUrl(null).hasPostAuthUrl, isFalse);
    expect(configWithUrl('').hasPostAuthUrl, isFalse);
  });

  group('https가 아니면 열지 않는다', () {
    // 외부 브라우저로 여는 주소다. 다른 스킴은 무엇이 열릴지 알 수 없다.
    // 서버도 https만 받지만(422), 앱이 받은 값을 다시 한 번 본다.
    for (final String bad in <String>[
      'http://example.com',
      'javascript:alert(1)',
      'intent://scan/#Intent;scheme=zxing;end',
      'file:///etc/passwd',
      'example.com',
    ]) {
      test(bad, () {
        expect(configWithUrl(bad).hasPostAuthUrl, isFalse);
      });
    }
  });

  test('fallback에는 주소가 없다', () {
    // 서버 응답 전에는 버튼이 뜨지 않아야 한다.
    expect(ServerConfig.fallback.hasPostAuthUrl, isFalse);
  });
}
