import java.util.Properties

plugins {
    id("com.android.application")
}

// 사이트 주소. 바꾸면 서버의 /.well-known/assetlinks.json 도 같은 도메인에서 나와야 한다.
val siteHost = "unifi.kacarong.kr"

// 릴리스 서명 정보는 레포 밖에 둔다 (android/keystore.properties, .gitignore 대상).
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "kr.kacarong.unifi"
    compileSdk = 36

    defaultConfig {
        applicationId = "kr.kacarong.unifi"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
        manifestPlaceholders["siteHost"] = siteHost
        manifestPlaceholders["siteUrl"] = "https://$siteHost/"
        // 이 앱이 사이트의 주인임을 선언한다. 사이트 쪽 assetlinks.json 과 짝이 맞아야
        // 주소창 없는 전체 화면(TWA)으로 열린다.
        resValue(
            "string", "asset_statements",
            "[{ \\\"relation\\\": [\\\"delegate_permission/common.handle_all_urls\\\"], " +
                "\\\"target\\\": { \\\"namespace\\\": \\\"web\\\", \\\"site\\\": \\\"https://$siteHost\\\" } }]",
        )
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.7.4")
}
