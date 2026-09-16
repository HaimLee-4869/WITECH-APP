import 'dart:math';

/// 사용자 1명. (backend/README 3장 `GET /users`)
///
/// **요청에는 [id], 화면에는 [name].** 둘을 섞으면 서버가 404 `user_not_found`를
/// 돌려준다. 실기기에서 이름("홍길동")을 userId로 보내 등록·인증이 전부 막혔었다.
class AppUser {
  /// 서버 `users.id`. `/verify`·`/enroll`의 `userId`로 보내는 값.
  final String id;

  /// 표시용 이름.
  final String name;

  final String? department;

  /// 현재 모델 버전으로 등록된 제스처 ID 목록.
  final List<String> enrolledGestures;

  const AppUser({
    required this.id,
    required this.name,
    this.department,
    this.enrolledGestures = const <String>[],
  });

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
    id: json['id'] as String,
    name: json['name'] as String? ?? json['id'] as String,
    department: json['department'] as String?,
    enrolledGestures: [
      for (final g in json['enrolledGestures'] as List<dynamic>? ?? const [])
        g as String,
    ],
  );

  @override
  String toString() => 'AppUser($id, $name)';
}

/// 새 사용자에게 붙일 서버 ID를 만든다. 영문 소문자 + 숫자.
///
/// 로그인이 없어 사용자가 ID를 정하지 않으므로 앱이 만든다. 이름은 한글이라
/// ID로 쓸 수 없다(서버 패턴은 `^[A-Za-z0-9_.\-]{1,64}$`이고, 한글 이름을 그대로
/// 보내면 거절된다). 시각 기반 접두사 + 난수라 같은 기기에서 충돌하지 않는다.
/// 서버가 409 `user_exists`를 주면 호출자가 다시 만들어 재시도한다.
String newUserId([Random? random]) {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  final rnd = random ?? Random();
  final stamp = DateTime.now().millisecondsSinceEpoch.toRadixString(36);
  final suffix = List.generate(4, (_) => chars[rnd.nextInt(chars.length)]).join();
  return 'u$stamp$suffix';
}
