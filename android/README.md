# unifi 안드로이드 앱 (TWA)

https://unifi.kacarong.kr 를 그대로 띄우는 껍데기 앱이다. 화면·기능은 전부 사이트에
있으므로 **사이트를 고치면 앱을 다시 만들 필요가 없다.** 앱을 다시 빌드하는 건
아이콘·이름·주소를 바꿀 때뿐이다.

- Chrome(또는 TWA 지원 브라우저)이 있으면 주소창 없는 전체 화면(TWA)으로 열린다.
  없으면 앱 안 WebView 로 연다.
- 전체 화면이 되려면 사이트의 `/.well-known/assetlinks.json`
  (`server/static/.well-known/assetlinks.json`) 에 서명 키 SHA-256 이 들어 있어야 한다.
  맞지 않으면 위에 주소창이 붙은 채로 열린다.

## 빌드

```bash
cd android
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64   # JDK 25 는 AGP 가 못 읽는다
./gradlew assembleRelease
# → app/build/outputs/apk/release/app-release.apk
```

안드로이드 SDK 경로는 `local.properties` 의 `sdk.dir` 또는 `ANDROID_HOME` 으로 준다.

## 서명

`android/keystore.properties` (커밋 금지) 가 있으면 릴리스 APK 에 서명한다.

```properties
storeFile=/절대/경로/release.keystore
storePassword=...
keyAlias=unifi
keyPassword=...
```

**같은 키로 계속 서명해야** 기존 설치본 위에 업데이트가 되고 assetlinks 도 맞는다.
키를 바꾸면 assetlinks.json 의 지문도 같이 바꿔야 한다.

```bash
keytool -list -v -keystore <keystore> | grep SHA256
```

업데이트 APK 를 낼 때는 `app/build.gradle.kts` 의 `versionCode` 를 올린다.
