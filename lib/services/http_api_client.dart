import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../core/config.dart';
import '../models/api_error.dart';
import '../models/auth_log.dart';
import '../models/enroll.dart';
import '../models/server_config.dart';
import '../models/verify.dart';
import 'api_client.dart';

/// 실제 백엔드 연동. (backend/README 3장 API 목록)
///
/// `kUseMockApi = false`로 바꾸면 이 구현이 주입된다.
/// 서버 주소는 코드에 넣지 않고 빌드 시 주입한다. (SPEC 13장)
///
/// ```
/// flutter run --dart-define=SIGNID_API_BASE=http://192.168.0.10:8000
/// ```
class HttpApiClient implements ApiClient {
  final String baseUrl;
  final http.Client _client;
  final Duration timeout;

  HttpApiClient({String? baseUrl, http.Client? client, this.timeout = kApiTimeout})
    : baseUrl = _normalize(baseUrl ?? kApiBaseUrl),
      _client = client ?? http.Client();

  static String _normalize(String url) =>
      url.endsWith('/') ? url.substring(0, url.length - 1) : url;

  Uri _uri(String path, [Map<String, String>? query]) {
    if (baseUrl.isEmpty) {
      throw const ApiNotConfiguredException(
        '서버 주소가 설정되지 않았습니다. '
        '--dart-define=SIGNID_API_BASE=http://<호스트>:8000 으로 빌드해주세요.',
      );
    }
    return Uri.parse('$baseUrl$path').replace(queryParameters: query);
  }

  /// 성공이면 본문(JSON)을, 실패면 [ApiException]을 던진다.
  dynamic _decode(http.Response res) {
    final body = res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    if (res.statusCode >= 200 && res.statusCode < 300) return body;
    throw ApiException.fromResponse(res.statusCode, body);
  }

  Future<dynamic> _post(String path, Map<String, dynamic> payload) async {
    final res = await _client
        .post(
          _uri(path),
          headers: const {'Content-Type': 'application/json; charset=utf-8'},
          body: jsonEncode(payload),
        )
        .timeout(timeout);
    return _decode(res);
  }

  Future<dynamic> _get(String path, [Map<String, String>? query]) async {
    final res = await _client.get(_uri(path, query)).timeout(timeout);
    return _decode(res);
  }

  @override
  Future<ServerConfig> fetchConfig() async {
    final json = await _get('/config');
    return ServerConfig.fromJson(json as Map<String, dynamic>);
  }

  @override
  Future<VerifyResponse> verify(VerifyRequest req) async {
    final json = await _post('/verify', req.toJson());
    return VerifyResponse.fromJson(json as Map<String, dynamic>);
  }

  @override
  Future<EnrollResponse> enroll(EnrollRequest req) async {
    final json = await _post('/enroll', req.toJson());
    return EnrollResponse.fromJson(json as Map<String, dynamic>);
  }

  @override
  Future<List<AuthLog>> fetchAuthLogs() async {
    // 관리자 화면 표는 최근 것부터 보여준다. 서버가 최신순으로 준다.
    final json = await _get('/logs', const {'limit': '100', 'offset': '0'});
    final items = (json as Map<String, dynamic>)['items'] as List<dynamic>;
    return items
        .map((e) => AuthLog.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  @override
  Future<List<MonthlyStat>> fetchMonthlyStats() async {
    final json = await _get('/stats/monthly', const {'months': '5'});
    return (json as List<dynamic>)
        .map((e) => MonthlyStat.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }
}
