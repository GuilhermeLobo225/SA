package pt.uminho.sa

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import pt.uminho.sa.data.Config

/**
 * Classe Application — corre uma vez quando a app arranca.
 *
 * O único trabalho aqui é registar o canal de notificações que vamos usar
 * quando o GeofenceBroadcastReceiver dispara um alerta de entrada/saída de
 * uma biblioteca (PL8). Desde a API 26 (Android 8.0) os canais são
 * obrigatórios — sem isto as notificações não aparecem.
 */
class SaApp : Application() {

    override fun onCreate() {
        super.onCreate()
        criarCanalGeofence()
    }

    private fun criarCanalGeofence() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val canal = NotificationChannel(
                Config.NOTIF_CHANNEL_GEOFENCE,
                getString(R.string.geofence_channel_name),
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = getString(R.string.geofence_channel_desc)
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(canal)
        }
    }
}
