plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "pt.uminho.sa"
    compileSdk = 34

    defaultConfig {
        applicationId = "pt.uminho.sa"
        minSdk = 26              // Android 8.0 — cobre praticamente todos os dispositivos atuais
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true       // permite aceder às views por nome sem findViewById
    }
}

dependencies {
    // AndroidX base
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.recyclerview)
    implementation(libs.androidx.swiperefreshlayout)
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)

    // Google Play Services Location — usado para geofencing
    implementation(libs.play.services.location)

    // Coroutines — para fazer pedidos HTTP fora da main thread
    implementation(libs.kotlinx.coroutines.android)

    // WorkManager — periodic job que verifica a API e dispara alertas
    implementation(libs.androidx.work.runtime.ktx)

    // Testes (opcional para já)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
