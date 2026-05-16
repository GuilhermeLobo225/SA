package pt.uminho.sa.alerts

import android.content.Context
import androidx.core.content.edit

/**
 * Estado configurável dos alertas que o utilizador define.
 *
 *  - enabled              : interruptor global. Se off, o worker não dispara.
 *  - occupancyEnabled     : alerta de "tem lugar" quando a ocupação cai abaixo
 *                            do limiar (em percentagem 0..100).
 *  - occupancyThresholdPct: limiar em % para o alerta de ocupação.
 *  - temperatureEnabled   : alerta quando a temperatura sai do intervalo
 *                            ASHRAE 55 (20–26 °C).
 *  - noiseEnabled         : alerta quando o ruído está classificado como
 *                            "elevado" ou "muito_elevado" (ou >55 dB rel.).
 */
data class AlertConfig(
    val enabled: Boolean              = false,
    val occupancyEnabled: Boolean     = true,
    val occupancyThresholdPct: Int    = 50,
    val temperatureEnabled: Boolean   = false,
    val noiseEnabled: Boolean         = false
) {
    val anyRuleActive: Boolean
        get() = occupancyEnabled || temperatureEnabled || noiseEnabled
}

/**
 * Wrapper minimalista sobre SharedPreferences para ler/escrever o `AlertConfig`.
 *
 * Optámos por SharedPreferences em vez de DataStore para manter consistência
 * com o resto da app (sem dependências adicionais) — o estado é trivial.
 */
object AlertPreferences {

    private const val PREFS = "alerts_prefs"
    private const val K_ENABLED      = "enabled"
    private const val K_OCC_EN       = "occ_enabled"
    private const val K_OCC_THRESH   = "occ_threshold"
    private const val K_TEMP_EN      = "temp_enabled"
    private const val K_NOISE_EN     = "noise_enabled"

    fun load(context: Context): AlertConfig {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return AlertConfig(
            enabled              = p.getBoolean(K_ENABLED,    false),
            occupancyEnabled     = p.getBoolean(K_OCC_EN,     true),
            occupancyThresholdPct = p.getInt(K_OCC_THRESH,   50).coerceIn(0, 100),
            temperatureEnabled   = p.getBoolean(K_TEMP_EN,    false),
            noiseEnabled         = p.getBoolean(K_NOISE_EN,   false)
        )
    }

    fun save(context: Context, config: AlertConfig) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit {
            putBoolean(K_ENABLED,    config.enabled)
            putBoolean(K_OCC_EN,     config.occupancyEnabled)
            putInt    (K_OCC_THRESH, config.occupancyThresholdPct.coerceIn(0, 100))
            putBoolean(K_TEMP_EN,    config.temperatureEnabled)
            putBoolean(K_NOISE_EN,   config.noiseEnabled)
        }
    }
}
