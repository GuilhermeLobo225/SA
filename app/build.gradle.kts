// Build script ao nível do projeto.
// Declara os plugins disponíveis para os módulos (aplicados com apply false aqui).
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
}
