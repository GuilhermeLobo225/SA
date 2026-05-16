package pt.uminho.sa

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import pt.uminho.sa.alerts.AlertsScheduler
import pt.uminho.sa.data.Config

/**
 * Classe Application — corre uma vez quando a app arranca.
 *
 * Responsabilidades:
 *   1. Registar os canais de notificações usados pela app (obrigatório
 *      desde a API 26 — Android 8.0).
 *   2. Re-aplicar o estado dos alertas configuráveis, para que o WorkManager
 *      volte a enfileirar o trabalho se o utilizador o tinha ativo antes
 *      de um reboot ou kill do processo.
 */
class SaApp : Application() {

    override fun onCreate() {
        super.onCreate()
        criarCanais()
        // Re-agendar o worker dos alertas se o utilizador o deixou ativo.
        AlertsScheduler.apply(this)
    }

    private fun criarCanais() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(
                Config.NOTIF_CHANNEL_GEOFENCE,
                getString(R.string.geofence_channel_name),
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply { description = getString(R.string.geofence_channel_desc) }
        )
        nm.createNotificationChannel(
            NotificationChannel(
                Config.NOTIF_CHANNEL_ALERTS,
                getString(R.string.alerts_channel_name),
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply { description = getString(R.string.alerts_channel_desc) }
        )
    }
}
