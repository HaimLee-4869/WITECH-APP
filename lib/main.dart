import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/theme.dart';
import 'screens/home_screen.dart';

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
      // 라우팅은 Navigator.push 정도로 충분하다. 화면이 5개뿐이고 딥링크나
      // 중첩 라우트가 없어서 라우터 패키지를 들일 이유가 없다. (SPEC 13장)
      home: const HomeScreen(),
    );
  }
}
