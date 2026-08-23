import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/theme.dart';
import 'screens/auth_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 세로 모드 고정. (SPEC 1장)
  // AndroidManifest에도 screenOrientation="portrait"을 걸어 두었다. 둘 다 두는
  // 이유는 매니페스트가 앱 시작 전 회전을 막고, 여기가 런타임 회전을 막기 때문.
  await SystemChrome.setPreferredOrientations(const [
    DeviceOrientation.portraitUp,
  ]);

  runApp(const ProviderScope(child: SignIdApp()));
}

class SignIdApp extends StatelessWidget {
  const SignIdApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sign-ID',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      // TODO(routing): 홈 화면을 만들면 진입점을 홈으로 바꾼다. (작업 순서 8단계)
      home: const AuthScreen(),
    );
  }
}
